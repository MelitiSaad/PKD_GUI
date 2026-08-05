"""The editing brain (plane-aware).

Owns the active tool and turns interaction in any of the three orthogonal panes
into undoable :class:`EditCommand`s. Freehand strokes are gap-filled and
collapse into one undo step; fill and morphology run as single commands. The
plane geometry in ``core.planes`` maps every 2D interaction to the right voxels,
so painting is correct in axial, coronal, and sagittal alike.
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from PySide6.QtCore import QObject, Signal

from ..config import DEFAULT_BRUSH_RADIUS, MAX_BRUSH_RADIUS, MIN_BRUSH_RADIUS
from ..core import segops
from ..core.commands import StrokeRecorder, combine_commands
from ..core.history import History
from ..core.segops import disk_offsets
from ..core.label_policy import policy_for

PAINT_TOOLS = {"brush"}
BRUSH_MODES = ("normal", "threshold")
CLICK_TOOLS = {"fill"}


class ToolController(QObject):
    brushRadiusChanged = Signal(int)
    toolChanged = Signal(str)
    edited = Signal()

    def __init__(self, ortho, parent=None):
        super().__init__(parent)
        self.ortho = ortho
        self.image = None
        self.seg = None
        self.history: Optional[History] = None
        self.tool = "crosshair"
        self.brush_mode = "normal"
        self.brush_radius = DEFAULT_BRUSH_RADIUS
        self.threshold_band: Optional[Tuple[float, float]] = None
        self.morph_3d = True
        # Safety-first default for QC: painting must not silently relabel a
        # neighbouring object. Experts can disable this for reassignment work.
        self.protect_existing = True
        self.island_min = 20
        self.background_runner = None
        self._rec: Optional[StrokeRecorder] = None
        self._last_vh: Optional[Tuple[int, int]] = None
        self._paint_val: int = 0
        self._lasso_plane = None
        self._lasso_vertices = []
        ortho.set_controller(self)

    # -- context ---------------------------------------------------------
    def set_context(self, image, seg, history: History) -> None:
        self.image = image
        self.seg = seg
        self.history = history
        self.threshold_band = image.default_window if image is not None else None

    def set_tool(self, name: str) -> None:
        if self.tool == "lasso" and name != "lasso":
            self.cancel_lasso()
        self.tool = name
        self.ortho.set_brush_visible(name in PAINT_TOOLS)
        self.ortho.set_brush_radius(self.brush_radius)
        self.toolChanged.emit(name)

    def lasso_start(self, plane, v: int, h: int) -> None:
        if self.seg is None or self.history is None:
            return
        self._lasso_plane = plane
        self._lasso_vertices = [(int(v), int(h))]
        self.ortho.set_lasso_preview(plane, self._lasso_vertices)

    def lasso_move(self, plane, v: int, h: int) -> None:
        if self._lasso_plane is not plane:
            return
        point = (int(v), int(h))
        if point != self._lasso_vertices[-1]:
            self._lasso_vertices.append(point)
            self.ortho.set_lasso_preview(plane, self._lasso_vertices)

    def lasso_end(self, plane, v: int, h: int, right: bool = False) -> None:
        """Commit the freehand contour immediately as one undoable edit."""
        self.lasso_move(plane, v, h)
        if len(self._lasso_vertices) < 3:
            self.cancel_lasso()
            return
        self.apply_lasso("remove" if right else "add")

    def cancel_lasso(self) -> None:
        self._lasso_plane = None
        self._lasso_vertices = []
        self.ortho.clear_lasso_preview()

    def apply_lasso(self, mode: str) -> None:
        plane, vertices = self._lasso_plane, self._lasso_vertices
        if plane is None or len(vertices) < 3:
            return
        value = 0 if mode == "remove" else int(self.seg.active_id)
        cmd = segops.apply_lasso_plane(
            self.seg, plane, self.ortho.cursor, vertices, value,
            protect_existing=self.protect_existing,
            remove_label=int(self.seg.active_id) if mode == "remove" else None,
        )
        self.cancel_lasso()
        if cmd is not None:
            if self.tool in CLICK_TOOLS:
                self.history.push(cmd)
            else:
                self.history.record_applied(cmd)
            self.ortho.redraw_overlay()
            self.ortho.flash_lasso(plane, vertices)
            self.ortho.notify_edit()
            self.edited.emit()

    def set_brush_mode(self, mode: str) -> None:
        if mode in BRUSH_MODES:
            self.brush_mode = mode

    def set_protect_existing(self, enabled: bool) -> None:
        self.protect_existing = bool(enabled)

    def set_brush_radius(self, r: int) -> None:
        self.brush_radius = int(np.clip(r, MIN_BRUSH_RADIUS, MAX_BRUSH_RADIUS))
        self.ortho.set_brush_radius(self.brush_radius)
        self.brushRadiusChanged.emit(self.brush_radius)

    def wheel_brush(self, steps: int) -> None:
        self.set_brush_radius(self.brush_radius + steps)

    # -- stamping --------------------------------------------------------
    def _value_for(self, right: bool) -> int:
        """Left button draws the active object, right button erases."""
        return 0 if right else int(self.seg.active_id)

    def _plane_stamp(self, plane, v: int, h: int, value: int) -> None:
        self._plane_stamp_centers(plane, np.asarray([v]), np.asarray([h]), value)

    def _plane_stamp_centers(self, plane, vs: np.ndarray, hs: np.ndarray, value: int) -> None:
        """Stamp a batch of brush centres in one vectorised recorder update."""
        if self._rec is None:
            return
        dv, dh = disk_offsets(self.brush_radius)
        # Expanding all dabs at once replaces hundreds of repeated coordinate
        # transforms, unique() calls, and Python-dict passes for a fast drag.
        vv = (np.asarray(vs, dtype=np.intp).ravel()[:, None] + dv[None, :]).ravel()
        hh = (np.asarray(hs, dtype=np.intp).ravel()[:, None] + dh[None, :]).ravel()
        shape = self.seg.data.shape
        ii, jj, kk = plane.disp_to_vox_arrays(vv, hh, self.ortho.cursor, shape)
        R, C, S = shape
        inside = (ii >= 0) & (ii < R) & (jj >= 0) & (jj < C) & (kk >= 0) & (kk < S)
        ii, jj, kk = ii[inside], jj[inside], kk[inside]
        if ii.size == 0:
            return
        if self.brush_mode == "threshold" and value != 0 and self.threshold_band is not None and self.image is not None:
            lo, hi = self.threshold_band
            vals = self.image.data[ii, jj, kk]
            keep = (vals >= lo) & (vals <= hi)
            ii, jj, kk = ii[keep], jj[keep], kk[keep]
        if ii.size:
            keep = policy_for(self.seg, protect_existing=self.protect_existing).writable(
                self.seg.data[ii, jj, kk], value)
            ii, jj, kk = ii[keep], jj[keep], kk[keep]
        self._rec.stamp_voxels(ii, jj, kk, value)

    def _plane_stamp_line(self, plane, v0, h0, v1, h1, value) -> None:
        distance = float(np.hypot(v1 - v0, h1 - h0))
        # A disk covers the gap when adjacent centres are at most one radius
        # apart.  This preserves continuous strokes but avoids a dab per pixel
        # for large brushes and rapid mouse moves.
        steps = max(1, int(np.ceil(distance / max(1, self.brush_radius))))
        vs = np.rint(np.linspace(v0, v1, steps + 1)).astype(np.intp)
        hs = np.rint(np.linspace(h0, h1, steps + 1)).astype(np.intp)
        self._plane_stamp_centers(plane, vs, hs, value)

    # -- paint interaction (from OrthoView) ------------------------------
    def plane_paint_start(self, plane, v, h, right=False) -> None:
        if self.seg is None:
            return
        self._paint_val = self._value_for(right)
        self._rec = StrokeRecorder(self.seg, self.tool)
        self._last_vh = (v, h)
        try:
            self._plane_stamp(plane, v, h, self._paint_val)
        except BaseException:
            self._abort_stroke()
            raise
        self.ortho.redraw_overlay(plane)

    def plane_paint_move(self, plane, v, h, right=False) -> None:
        if self._rec is None:
            return
        v0, h0 = self._last_vh
        try:
            self._plane_stamp_line(plane, v0, h0, v, h, self._paint_val)
        except BaseException:
            self._abort_stroke()
            raise
        self._last_vh = (v, h)
        self.ortho.redraw_overlay(plane)

    def plane_paint_end(self) -> None:
        if self._rec is None:
            return
        recorder = self._rec
        cmd = recorder.commit()
        self._rec = None
        self._last_vh = None
        if cmd is not None and self.history is not None:
            try:
                self.history.record_applied(cmd)
            except BaseException:
                recorder.rollback()
                raise
            self.ortho.redraw_overlay()
            self.ortho.notify_edit()
            self.edited.emit()

    def plane_paint_click(self, plane, v, h, right=False) -> None:
        if self.seg is None or self.history is None:
            return
        if self.tool in CLICK_TOOLS:
            value = 0 if right else int(self.seg.active_id)
            cmd = segops.flood_fill_plane(self.seg, plane, self.ortho.cursor, v, h, value,
                                             policy=policy_for(self.seg, protect_existing=self.protect_existing))
        else:
            self._rec = StrokeRecorder(self.seg, self.tool)
            try:
                self._plane_stamp(plane, v, h, self._value_for(right))
                cmd = self._rec.commit()
            except BaseException:
                self._abort_stroke()
                raise
            self._rec = None
        if cmd is not None:
            if self.tool in CLICK_TOOLS:
                self.history.push(cmd)
            else:
                self.history.record_applied(cmd)
            self.ortho.redraw_overlay()
            self.ortho.notify_edit()
            self.edited.emit()

    def _abort_stroke(self) -> None:
        if self._rec is not None:
            self._rec.rollback()
        self._rec = None
        self._last_vh = None

    # -- region actions (toolbar) ---------------------------------------
    def _run(self, cmd) -> None:
        if cmd is not None and self.history is not None:
            self.history.push(cmd)
            self.ortho.redraw_overlay()
            self.ortho.notify_edit()
            self.edited.emit()

    def _background_or_run(self, op_name, sync_compute):
        if self.background_runner is not None and self.seg is not None:
            self.background_runner(op_name, int(self.seg.active_id), self.morph_3d, self.ortho.z, self.island_min)
        else:
            self._run(sync_compute())

    def apply_grow(self) -> None:
        self._background_or_run("grow", lambda: segops.grow(self.seg, int(self.seg.active_id), 1, self.morph_3d, self.ortho.z))

    def apply_shrink(self) -> None:
        self._background_or_run("shrink", lambda: segops.shrink(self.seg, int(self.seg.active_id), 1, self.morph_3d, self.ortho.z))

    def apply_remove_islands(self) -> None:
        self._background_or_run("remove islands", lambda: segops.remove_islands(self.seg, int(self.seg.active_id),
                                        self.island_min, self.morph_3d, self.ortho.z))

    def apply_fill_holes(self) -> None:
        self._background_or_run("fill holes", lambda: segops.fill_holes(self.seg, int(self.seg.active_id), self.morph_3d, self.ortho.z))

    def apply_interpolate(self) -> None:
        if self.seg is None:
            return
        lid = int(self.seg.active_id)
        S = self.seg.data.shape[2]
        annotated = [z for z in range(S) if (self.seg.data[:, :, z] == lid).any()]
        commands = [
            segops.interpolate_between(self.seg, lid, a, b)
            for a, b in zip(annotated, annotated[1:]) if b - a > 1
        ]
        self._run(combine_commands(commands, "interpolate slices"))
