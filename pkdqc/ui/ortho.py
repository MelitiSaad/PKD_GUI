"""Multi-planar reconstruction viewer (ITK-SNAP-style).

A 2x2 grid — axial, coronal, sagittal, 3D — over a single volume sharing one
crosshair cursor, plus a single-pane mode (double-click a pane, or use the
layout buttons) so you can focus on one orientation.

Mouse model:
  * Crosshair: left-drag moves the crosshair through the volume (all panes
               follow); a click also selects the object under the cursor.
  * Pan:       left-drag pans.
  * Brush:     left paints the active object, right erases.
  * Fill:      left fills the region with the active object, right clears it.
Right-drag always zooms about a fixed anchor, and middle-drag always pans, no
matter which tool is active. Wheel scrolls that pane's slices; Ctrl+wheel zooms;
Alt+wheel resizes the brush.

Contrast/window-level is no longer on the right mouse button — it lives in the
Contrast editor (Tools menu / toolbar).
"""
from __future__ import annotations

from typing import Dict

import numpy as np
import pyqtgraph as pg
from pyqtgraph import functions as fn
from PySide6.QtCore import QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem, QGraphicsPathItem, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from .. import theme
from ..core.planes import ORDER, PLANES, display_aspect
from . import volume_view

pg.setConfigOptions(imageAxisOrder="row-major", antialias=False)


class _PlaneViewBox(pg.ViewBox):
    def __init__(self, widget: "PlaneWidget"):
        super().__init__()
        self.w = widget
        self.setMenuEnabled(False)
        self.setMouseMode(pg.ViewBox.PanMode)
        self._zoom_anchor = None

    def _vh(self, scene_pos):
        p = self.mapSceneToView(scene_pos)
        return int(np.floor(p.y())), int(np.floor(p.x()))

    def _zoom_drag(self, ev):
        """Zoom about a FIXED anchor captured when the drag started.

        Anchoring to the live mouse position makes the image slide around while
        you zoom; capturing it once keeps the point under the cursor put.
        """
        if ev.isStart() or self._zoom_anchor is None:
            tr = fn.invertQTransform(self.childGroup.transform())
            self._zoom_anchor = pg.Point(tr.map(ev.buttonDownPos(Qt.MouseButton.RightButton)))
        d = ev.pos() - ev.lastPos()
        s = float(np.clip(1.0 - d.y() * 0.006, 0.25, 4.0))
        self._resetTarget()
        self.scaleBy((s, s), self._zoom_anchor)
        if ev.isFinish():
            self._zoom_anchor = None

    def mouseDragEvent(self, ev, axis=None):
        o = self.w.owner
        btn = ev.button()
        tool = o.tool_name()

        # Middle-drag always pans. Right-drag zooms except when the active editing
        # tool uses it as its scoped erase gesture (Brush or Lasso).
        if btn == Qt.MouseButton.MiddleButton:
            super().mouseDragEvent(ev, axis)
            return

        if o.tool_is_lasso() and btn in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            ev.accept()
            v, h = self._vh(ev.scenePos())
            right = btn == Qt.MouseButton.RightButton
            if ev.isStart():
                o.lasso_start(self.w.plane, v, h)
            elif ev.isFinish():
                o.lasso_end(self.w.plane, v, h, right)
            else:
                o.lasso_move(self.w.plane, v, h)
            return

        if o.tool_is_paint() and btn in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            ev.accept()
            v, h = self._vh(ev.scenePos())
            right = btn == Qt.MouseButton.RightButton
            if ev.isStart():
                o.paint_start(self.w.plane, v, h, right)
            elif ev.isFinish():
                o.paint_end()
            else:
                o.paint_move(self.w.plane, v, h, right)
            return

        if btn == Qt.MouseButton.RightButton:
            ev.accept()
            self._zoom_drag(ev)
            return

        if btn == Qt.MouseButton.LeftButton:
            if tool == "crosshair":
                ev.accept()
                v, h = self._vh(ev.scenePos())
                o.set_cursor_from_plane(self.w.plane, v, h)
                return
            if tool == "pan":
                super().mouseDragEvent(ev, axis)
                return
            ev.accept()   # fill: nothing to drag
            return
        super().mouseDragEvent(ev, axis)

    def mouseClickEvent(self, ev):
        o = self.w.owner
        right = ev.button() == Qt.MouseButton.RightButton
        if ev.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            ev.accept()
            v, h = self._vh(ev.scenePos())
            if o.tool_is_paint() or o.tool_is_click():
                o.paint_click(self.w.plane, v, h, right)
            elif not right:
                o.navigate_click(self.w.plane, v, h)
            return
        super().mouseClickEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.w.owner.toggle_maximize(self.w.plane.name)
        ev.accept()

    def wheelEvent(self, ev, axis=None):
        o = self.w.owner
        mods = ev.modifiers()
        delta = ev.delta() if hasattr(ev, "delta") else ev.angleDelta().y()
        steps = 1 if delta > 0 else -1
        if mods & Qt.KeyboardModifier.ControlModifier:
            super().wheelEvent(ev, axis)
            return
        if mods & Qt.KeyboardModifier.AltModifier and o.controller is not None:
            o.controller.wheel_brush(steps)
            ev.accept()
            return
        o.scroll_plane(self.w.plane, steps)
        ev.accept()


class PlaneWidget(QWidget):
    def __init__(self, plane, owner: "OrthoView"):
        super().__init__()
        self.plane = plane
        self.owner = owner
        self.setObjectName("Panel")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        header = QWidget(); header.setObjectName("PaneHeader")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(10, 5, 10, 5)
        self.title = QLabel(plane.name.capitalize())
        self.title.setProperty("role", "subtitle")
        self.markers = QLabel(""); self.markers.setProperty("role", "muted")
        self.info = QLabel(""); self.info.setProperty("role", "muted")
        hb.addWidget(self.title); hb.addWidget(self.markers); hb.addStretch(1); hb.addWidget(self.info)
        v.addWidget(header)

        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground(theme.BASE)
        self.vb = _PlaneViewBox(self)
        self.vb.setAspectLocked(True)
        self.vb.invertY(True)
        self.glw.addItem(self.vb)
        v.addWidget(self.glw, 1)

        self.img_item = pg.ImageItem()
        self.seg_item = pg.ImageItem(); self.seg_item.setZValue(10)
        self.selected_item = pg.ImageItem(); self.selected_item.setZValue(11)
        self.vb.addItem(self.img_item)
        self.vb.addItem(self.seg_item)
        self.vb.addItem(self.selected_item)

        pen = QPen(QColor(theme.ACCENT)); pen.setCosmetic(True); pen.setWidthF(0.8)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.cx = pg.InfiniteLine(angle=90, pen=pen); self.cx.setZValue(15)
        self.cy = pg.InfiniteLine(angle=0, pen=pen); self.cy.setZValue(15)
        self.vb.addItem(self.cx); self.vb.addItem(self.cy)

        bpen = QPen(QColor(theme.ACCENT)); bpen.setCosmetic(True); bpen.setWidthF(1.6)
        self.brush = QGraphicsEllipseItem(); self.brush.setPen(bpen)
        self.brush.setBrush(Qt.BrushStyle.NoBrush); self.brush.setZValue(20)
        self.brush.setVisible(False)
        self.vb.addItem(self.brush)
        self.lasso = QGraphicsPathItem(); self.lasso.setZValue(21)
        ppen = QPen(QColor(theme.ACCENT)); ppen.setCosmetic(True); ppen.setWidthF(1.8)
        self.lasso.setPen(ppen); self.lasso.setVisible(False)
        self.vb.addItem(self.lasso)
        self._brush_r = 4
        self._overlay_timer = QTimer(self); self._overlay_timer.setSingleShot(True)
        self._overlay_timer.timeout.connect(self._flush_overlay)
        self._overlay_dirty = None
        self._lasso_flash_timer = QTimer(self); self._lasso_flash_timer.setSingleShot(True)
        self._lasso_flash_timer.timeout.connect(lambda: self.set_lasso((), None, False))
        self.glw.scene().sigMouseMoved.connect(self._hover)

    def refresh(self):
        img = self.owner.image
        if img is None:
            return
        self.img_item.setImage(self.plane.slice2d(img.data, self.owner.cursor),
                               autoLevels=False, levels=self.owner.window)
        self._refresh_overlay()
        v, h = self.plane.vox_to_disp(self.owner.cursor, img.shape)
        self.cx.setPos(h + 0.5); self.cy.setPos(v + 0.5)
        if getattr(img, "geometry", None) is not None:
            m = self.plane.edge_markers(img.geometry)
            self.markers.setText(f"  {m['left']}↔{m['right']}  {m['top']}↕{m['bottom']}")
        di = self.owner.cursor[self.plane.depth_axis]
        self.info.setText(f"{di + 1} / {self.plane.depth_len(img.shape)}")

    def _refresh_overlay(self):
        seg = self.owner.seg
        if seg is None:
            self.seg_item.clear(); self.selected_item.clear(); return
        lut = seg.labels.lut()
        max_id = max(1, lut.shape[0] - 1)
        current = self.plane.slice2d(seg.data, self.owner.cursor)
        self.seg_item.setImage(current, autoLevels=False, levels=(0, max_id), lut=lut)
        selected = self.owner.selected_label_id
        if selected is None:
            self.selected_item.clear()
            return
        lab = seg.labels.labels.get(selected)
        if lab is None or not lab.visible:
            self.selected_item.clear()
            return
        # A lightweight alpha mask makes the selected object obvious without
        # altering the label overlay or adding work to live brush strokes.
        mask = current == np.uint16(selected)
        if not mask.any():
            self.selected_item.clear()
            return
        color = np.array([[0, 0, 0, 0], [*lab.color, 76]], dtype=np.uint8)
        self.selected_item.setImage(mask.astype(np.uint8), autoLevels=False,
                                    levels=(0, 1), lut=color)

    def redraw_overlay(self):
        """Coalesce pointer-rate overlay uploads into one event-loop frame.

        A live brush can emit many stamps before Qt paints.  Keeping only one
        queued upload avoids repeatedly converting/uploading the same slice,
        while the mutable segmentation array remains the source of truth.
        """
        if not self._overlay_timer.isActive():
            self._overlay_timer.start(0)

    def _flush_overlay(self):
        self._refresh_overlay()

    def set_lasso(self, vertices, hover=None, visible=False):
        path = QPainterPath()
        if vertices:
            v, h = vertices[0]; path.moveTo(h + .5, v + .5)
            for v, h in vertices[1:]: path.lineTo(h + .5, v + .5)
            if hover is not None:
                v, h = hover; path.lineTo(h + .5, v + .5)
            else:
                path.closeSubpath()
        self.lasso.setPath(path)
        self.lasso.setVisible(bool(visible and vertices))

    def stop_lasso_flash(self):
        self._lasso_flash_timer.stop()

    def flash_lasso(self, vertices):
        """Leave the closed contour visible briefly after its edit is committed."""
        self.set_lasso(vertices, visible=True)
        self._lasso_flash_timer.start(160)

    def set_levels(self, win):
        self.img_item.setLevels(win)

    def fit(self):
        img = self.owner.image
        if img is None:
            return
        W = self.plane.horizontal_len(img.shape)
        V = self.plane.vertical_len(img.shape)
        vspac, hspac = self.plane.spacing_vh(img.spacing)
        ratio = display_aspect(vspac, hspac)
        self.vb.setAspectLocked(True, ratio=ratio)
        self.vb.setRange(QRectF(0, 0, W, V), padding=0.03)

    def set_brush_radius(self, r):
        self._brush_r = int(r)

    def set_brush_visible(self, visible):
        self.brush.setVisible(visible)

    def _hover(self, scene_pos):
        img = self.owner.image
        if img is None:
            return
        p = self.vb.mapSceneToView(scene_pos)
        v, h = int(np.floor(p.y())), int(np.floor(p.x()))
        V = self.plane.vertical_len(img.shape); H = self.plane.horizontal_len(img.shape)
        if 0 <= v < V and 0 <= h < H:
            # Keep the cursor circular on anisotropic CT planes.  Stamping
            # remains voxel-based; this is a physical-space preview only.
            vsp, hsp = self.plane.spacing_vh(img.spacing)
            rv = self._brush_r
            rh = rv * vsp / hsp if hsp > 0 else rv
            self.brush.setRect(h - rh, v - rv, 2 * rh + 1, 2 * rv + 1)
            self.owner.on_hover(self.plane, v, h)


class OrthoView(QWidget):
    cursorChanged = Signal(int, int, int)
    windowChanged = Signal(float, float)
    hovered = Signal(int, int, int)
    labelPicked = Signal(int)
    layoutChanged = Signal(str)

    def __init__(self, enable_3d: bool = True, parent=None):
        super().__init__(parent)
        self.image = None
        self.seg = None
        self.cursor = [0, 0, 0]
        self.window = (0.0, 1.0)
        self.controller = None
        self.selected_label_id = None
        self.continuous_3d = False
        self._layout_mode = "grid"
        self._enable_3d = enable_3d and volume_view.available()

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(2)
        self.empty_hint = QLabel("Open an image to begin\n\nLoad a CT or MRI volume, then review or add a segmentation.")
        self.empty_hint.setObjectName("EmptyState")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)

        self.planes: Dict[str, PlaneWidget] = {name: PlaneWidget(PLANES[name], self) for name in ORDER}

        if self._enable_3d:
            self.view3d = volume_view.Volume3DView()
            self.view3d.sliceClicked.connect(self._on_3d_slice)
            self._corner = self.view3d
        else:
            self.view3d = None
            ph = QLabel("3D view unavailable\n(needs a GPU / OpenGL)")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setProperty("role", "muted"); ph.setObjectName("Panel")
            self._corner = ph

        self._cells = {ORDER[0]: self.planes[ORDER[0]], ORDER[1]: self.planes[ORDER[1]],
                       ORDER[2]: self.planes[ORDER[2]], "3d": self._corner}
        self._relayout()

    # -- layout ----------------------------------------------------------
    def _relayout(self):
        for w in (*self._cells.values(), self.empty_hint):
            self.grid.removeWidget(w); w.hide()
        if self.image is None:
            self.grid.addWidget(self.empty_hint, 0, 0, 2, 2)
            self.empty_hint.show()
        elif self._layout_mode == "grid":
            self.grid.addWidget(self._cells[ORDER[0]], 0, 0)
            self.grid.addWidget(self._cells[ORDER[1]], 0, 1)
            self.grid.addWidget(self._cells[ORDER[2]], 1, 0)
            self.grid.addWidget(self._cells["3d"], 1, 1)
            for w in self._cells.values():
                w.show()
        else:
            self.grid.addWidget(self._cells[self._layout_mode], 0, 0)
            self._cells[self._layout_mode].show()
        QTimer.singleShot(0, self.fit_all)
        self.layoutChanged.emit(self._layout_mode)

    def set_layout(self, mode: str):
        if mode not in ("grid", ORDER[0], ORDER[1], ORDER[2], "3d"):
            return
        self._layout_mode = mode
        self._relayout()

    @property
    def layout_mode(self):
        return self._layout_mode

    def toggle_maximize(self, plane_name: str):
        self.set_layout("grid" if self._layout_mode == plane_name else plane_name)

    # -- setup -----------------------------------------------------------
    def set_controller(self, controller):
        self.controller = controller

    def set_data(self, image, seg):
        self.image = image
        self.seg = seg
        self.selected_label_id = int(seg.active_id) if seg is not None else None
        self._relayout()
        self.window = image.default_window if image is not None else (0.0, 1.0)
        self.cursor = [s // 2 for s in image.shape] if image is not None else [0, 0, 0]
        for p in self.planes.values():
            p.refresh()
        QTimer.singleShot(0, self.fit_all)
        if self.view3d is not None:
            self.view3d.set_context(image, seg)
        self.windowChanged.emit(*self.window)
        self.cursorChanged.emit(*self.cursor)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.fit_all()

    def fit_all(self):
        for name, w in self._cells.items():
            if name != "3d" and (self._layout_mode in ("grid", name)):
                w.fit()

    def refresh_all(self):
        for p in self.planes.values():
            p.refresh()

    def set_selected_label(self, lid: int | None):
        self.selected_label_id = None if lid is None else int(lid)
        self.redraw_overlay()

    def redraw_overlay(self, plane=None):
        """Refresh a segmentation overlay.

        During a live stroke only the pane receiving pointer events needs a
        frame.  Cross-plane overlays are synchronized at stroke completion;
        rebuilding all three full slice images for every mouse event was the
        primary source of visible brush stutter.
        """
        if plane is None:
            for p in self.planes.values():
                p.redraw_overlay()
        else:
            self.planes[plane.name].redraw_overlay()

    def set_lasso_preview(self, plane, vertices, hover=None):
        for name, widget in self.planes.items():
            widget.stop_lasso_flash()
            widget.set_lasso(vertices if name == plane.name else (), hover if name == plane.name else None,
                             name == plane.name)

    def clear_lasso_preview(self):
        for widget in self.planes.values():
            widget.stop_lasso_flash()
            widget.set_lasso((), None, False)

    def flash_lasso(self, plane, vertices):
        self.planes[plane.name].flash_lasso(vertices)

    # -- cursor / navigation --------------------------------------------
    def set_cursor(self, i, j, k):
        if self.image is None:
            return
        R, C, S = self.image.shape
        self.cursor = [int(np.clip(i, 0, R - 1)), int(np.clip(j, 0, C - 1)), int(np.clip(k, 0, S - 1))]
        self.refresh_all()
        self.cursorChanged.emit(*self.cursor)

    def set_cursor_from_plane(self, plane, v, h):
        self.set_cursor(*plane.disp_to_vox(v, h, self.cursor, self.image.shape))

    def navigate_click(self, plane, v, h):
        vox = plane.disp_to_vox(v, h, self.cursor, self.image.shape)
        self.set_cursor(*vox)
        if self.seg is not None:
            lid = int(self.seg.data[vox])
            if lid > 0:
                self.labelPicked.emit(lid)

    def scroll_plane(self, plane, steps):
        c = list(self.cursor); c[plane.depth_axis] += steps; self.set_cursor(*c)

    def set_axial_slice(self, z):
        c = list(self.cursor); c[2] = int(z); self.set_cursor(*c)

    def _on_3d_slice(self, z):
        self.set_axial_slice(z)

    @property
    def z(self):
        return self.cursor[2]

    # -- window / level --------------------------------------------------
    def set_window(self, lo, hi):
        if hi <= lo:
            hi = lo + 1e-3
        self.window = (float(lo), float(hi))
        for p in self.planes.values():
            p.set_levels(self.window)
        self.windowChanged.emit(*self.window)

    def intensity_sample(self, max_n: int = 200_000):
        """A flat sample of image intensities for the contrast histogram."""
        if self.image is None:
            return np.zeros(0, dtype=np.float32)
        d = self.image.data.reshape(-1)
        if d.size > max_n:
            idx = np.linspace(0, d.size - 1, max_n).astype(np.intp)
            d = d[idx]
        return d[np.isfinite(d)]

    # -- brush -----------------------------------------------------------
    def set_brush_radius(self, r):
        for p in self.planes.values():
            p.set_brush_radius(r)

    def set_brush_visible(self, visible):
        for p in self.planes.values():
            p.set_brush_visible(visible)

    # -- tool queries / paint delegation --------------------------------
    def tool_name(self):
        return self.controller.tool if self.controller is not None else "crosshair"

    def tool_is_paint(self):
        return self.controller is not None and self.controller.tool == "brush"

    def tool_is_lasso(self):
        return self.controller is not None and self.controller.tool == "lasso"

    def tool_is_click(self):
        return self.controller is not None and self.controller.tool == "fill"

    def paint_start(self, plane, v, h, right):
        if self.controller:
            self.controller.plane_paint_start(plane, v, h, right)

    def paint_move(self, plane, v, h, right):
        if self.controller:
            self.controller.plane_paint_move(plane, v, h, right)

    def paint_end(self):
        if self.controller:
            self.controller.plane_paint_end()

    def paint_click(self, plane, v, h, right):
        if self.controller:
            self.controller.plane_paint_click(plane, v, h, right)

    def lasso_start(self, plane, v, h):
        if self.controller:
            self.controller.lasso_start(plane, v, h)

    def lasso_move(self, plane, v, h):
        if self.controller:
            self.controller.lasso_move(plane, v, h)

    def lasso_end(self, plane, v, h, right=False):
        if self.controller:
            self.controller.lasso_end(plane, v, h, right)

    def on_hover(self, plane, v, h):
        self.hovered.emit(*plane.disp_to_vox(v, h, self.cursor, self.image.shape))

    # -- 3D --------------------------------------------------------------
    def refresh_3d(self):
        if self.view3d is not None:
            self.view3d.refresh()

    def set_3d_axes_visible(self, on: bool):
        if self.view3d is not None:
            self.view3d.set_axes_visible(on)

    def notify_edit(self):
        """Called after an edit; only rebuild 3D if the user opted into continuous mode."""
        if self.continuous_3d and self.view3d is not None:
            self.view3d.refresh()
