"""Live 3D view of the corrected segmentation.

Renders a marching-cubes surface per visible label (coloured to match the
overlay) using PyVista/VTK, embedded in Qt. Picking a point jumps the 2D viewer
to the corresponding slice. If VTK can't initialise (headless box, no GPU), the
whole dock degrades to an informative placeholder — the app never hard-depends
on 3D.
"""
from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import theme

log = logging.getLogger(__name__)

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
    _IMPORT_OK = True
except Exception as exc:  # pragma: no cover - environment dependent
    log.info("3D unavailable: %s", exc)
    _IMPORT_OK = False


def available() -> bool:
    return _IMPORT_OK


class Volume3DView(QWidget):
    sliceClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.image = None
        self.seg = None
        self.plotter = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        if not _IMPORT_OK:
            msg = QLabel("3D view unavailable\n(VTK could not start on this system)")
            msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setProperty("role", "muted")
            lay.addWidget(msg)
            return

        try:
            self.plotter = QtInteractor(self)
            self.plotter.set_background(theme.BASE)
            lay.addWidget(self.plotter.interactor)
            self.plotter.enable_point_picking(
                callback=self._on_pick, show_message=False, show_point=False, left_clicking=False
            )
            self._axes_on = True
            try:
                self.plotter.add_axes()   # corner XYZ orientation reference
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover
            log.warning("3D init failed: %s", exc)
            self.plotter = None
            lay.addWidget(QLabel("3D view could not be initialised."))

    # -- api -------------------------------------------------------------
    def set_context(self, image, seg) -> None:
        self.image = image
        self.seg = seg

    def refresh(self, max_voxels: int = 6_000_000) -> None:
        if self.plotter is None or self.seg is None:
            return
        try:
            self.plotter.clear()
            data = self.seg.data
            stride = 1
            while data[::stride, ::stride, ::stride].size > max_voxels:
                stride += 1
            spacing = tuple(s * stride for s in self.image.spacing) if self.image else (1, 1, 1)
            any_mesh = False
            for lab in self.seg.labels:
                if not lab.visible:
                    continue
                mask = (data[::stride, ::stride, ::stride] == np.uint16(lab.id)).astype(np.float32)
                if mask.max() < 0.5:
                    continue
                grid = pv.wrap(mask)
                grid.spacing = spacing
                try:
                    surf = grid.contour([0.5])
                except Exception:
                    continue
                if surf.n_points == 0:
                    continue
                surf = surf.smooth(n_iter=20, relaxation_factor=0.1)
                self.plotter.add_mesh(
                    surf, color=np.array(lab.color) / 255.0, opacity=1.0,
                    smooth_shading=True, specular=0.3, name=f"label_{lab.id}",
                )
                any_mesh = True
            if any_mesh:
                self.plotter.reset_camera()
            if getattr(self, "_axes_on", True):
                try:
                    self.plotter.add_axes()
                except Exception:
                    pass
            self.plotter.render()
        except Exception as exc:  # pragma: no cover
            log.warning("3D refresh failed: %s", exc)

    def set_axes_visible(self, on: bool) -> None:
        self._axes_on = bool(on)
        if self.plotter is None:
            return
        try:
            if on:
                self.plotter.add_axes()
            else:
                self.plotter.hide_axes()
            self.plotter.render()
        except Exception:  # pragma: no cover
            pass

    def _on_pick(self, point, *args):  # pragma: no cover - interactive
        if point is None or self.image is None:
            return
        sz = self.image.spacing[2] or 1.0
        z = int(round(point[2] / sz))
        z = int(np.clip(z, 0, self.image.n_slices - 1))
        self.sliceClicked.emit(z)
