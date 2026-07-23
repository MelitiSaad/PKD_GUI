"""Interactive contrast (window/level) editor.

A histogram of the image intensities with a draggable shaded region for the
display window, plus numeric min/max fields and Auto/Reset. Applies live to the
viewer, so it replaces the old right-drag-to-window-level behaviour with
something you can actually see and tune.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from .. import theme

_BG = getattr(theme, "PANEL", theme.BASE)


class ContrastDialog(QDialog):
    def __init__(self, ortho, parent=None):
        super().__init__(parent)
        self.ortho = ortho
        self._suppress = False
        self.setWindowTitle("Image contrast")
        self.resize(480, 340)

        lay = QVBoxLayout(self)
        info = QLabel("Drag the shaded band, or edit Min/Max. Changes apply live.")
        info.setProperty("role", "muted")
        lay.addWidget(info)

        self.plot = pg.PlotWidget()
        self.plot.setBackground(_BG)
        self.plot.getAxis("left").hide()
        self.plot.setMenuEnabled(False)
        self.plot.setMouseEnabled(x=True, y=False)
        lay.addWidget(self.plot, 1)

        data = ortho.intensity_sample()
        lo_data = float(data.min()) if data.size else 0.0
        hi_data = float(data.max()) if data.size else 1.0
        if hi_data <= lo_data:
            hi_data = lo_data + 1.0
        self._data_range = (lo_data, hi_data)
        if data.size:
            counts, edges = np.histogram(data, bins=160)
            centers = (edges[:-1] + edges[1:]) / 2.0
            self.plot.plot(centers, counts, fillLevel=0,
                           brush=(90, 120, 200, 120), pen=pg.mkPen(theme.ACCENT))

        lo, hi = ortho.window
        self.region = pg.LinearRegionItem(values=(lo, hi), brush=(120, 150, 220, 60))
        self.region.setBounds([lo_data, hi_data])
        self.plot.addItem(self.region)
        self.region.sigRegionChanged.connect(self._on_region)

        row = QHBoxLayout()
        row.addWidget(QLabel("Min"))
        self.sp_lo = QDoubleSpinBox(); self._cfg(self.sp_lo, lo)
        row.addWidget(self.sp_lo)
        row.addSpacing(8)
        row.addWidget(QLabel("Max"))
        self.sp_hi = QDoubleSpinBox(); self._cfg(self.sp_hi, hi)
        row.addWidget(self.sp_hi)
        row.addStretch(1)
        b_auto = QPushButton("Auto"); b_auto.clicked.connect(self._auto)
        b_reset = QPushButton("Full range"); b_reset.clicked.connect(self._reset)
        row.addWidget(b_auto); row.addWidget(b_reset)
        lay.addLayout(row)

        self.sp_lo.valueChanged.connect(self._on_spin)
        self.sp_hi.valueChanged.connect(self._on_spin)

    def _cfg(self, sp: QDoubleSpinBox, val: float):
        lo, hi = self._data_range
        span = max(hi - lo, 1.0)
        sp.setRange(lo - span, hi + span)
        sp.setDecimals(1)
        sp.setSingleStep(max(span / 200.0, 0.1))
        sp.setValue(val)

    def _on_region(self):
        if self._suppress:
            return
        lo, hi = self.region.getRegion()
        self._push(lo, hi, from_region=True)

    def _on_spin(self):
        if self._suppress:
            return
        lo, hi = self.sp_lo.value(), self.sp_hi.value()
        if hi <= lo:
            hi = lo + 1.0
        self._push(lo, hi, from_spin=True)

    def _auto(self):
        data = self.ortho.intensity_sample()
        if data.size:
            self._push(float(np.percentile(data, 2)), float(np.percentile(data, 98)),
                       full=True)

    def _reset(self):
        self._push(self._data_range[0], self._data_range[1], full=True)

    def _push(self, lo, hi, from_region=False, from_spin=False, full=False):
        self._suppress = True
        if not from_spin:
            self.sp_lo.setValue(lo); self.sp_hi.setValue(hi)
        if not from_region:
            self.region.setRegion((lo, hi))
        self._suppress = False
        self.ortho.set_window(lo, hi)
