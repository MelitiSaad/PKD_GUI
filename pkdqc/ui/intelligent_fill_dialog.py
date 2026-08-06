"""Compact, modeless controls for Intelligent Fill preview and commit."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout)


class IntelligentFillDialog(QDialog):
    parametersChanged = Signal()
    applyRequested = Signal()
    cancelRequested = Signal()

    def __init__(self, lower, upper, parent=None):
        super().__init__(parent); self.setWindowTitle("Intelligent Fill"); self.setModal(False)
        root = QVBoxLayout(self)
        self.help = QLabel("Click a seed voxel in an image plane. Preview does not modify the segmentation.")
        self.help.setWordWrap(True); root.addWidget(self.help)
        form = QFormLayout(); self.seed = QLabel("—"); self.intensity = QLabel("—")
        self.lower = QDoubleSpinBox(); self.upper = QDoubleSpinBox()
        for spin, value in ((self.lower, lower), (self.upper, upper)):
            spin.setRange(-1e12, 1e12); spin.setDecimals(4); spin.setValue(float(value))
        self.scope = QComboBox(); self.scope.addItem("Current 2D plane", "2d"); self.scope.addItem("Full 3D (advanced)", "3d")
        self.connectivity = QComboBox(); self.connectivity.addItems(["4", "8"])
        self.changed = QLabel("0"); self.protected = QLabel("0")
        for label, widget in (("Seed", self.seed), ("Seed intensity", self.intensity),
                              ("Lower intensity", self.lower), ("Upper intensity", self.upper),
                              ("Scope", self.scope), ("Connectivity", self.connectivity),
                              ("Proposed changes", self.changed), ("Protected/conflicting", self.protected)):
            form.addRow(label, widget)
        root.addLayout(form)
        row = QHBoxLayout(); self.cancel = QPushButton("Cancel"); self.apply = QPushButton("Apply")
        self.apply.setEnabled(False); row.addStretch(1); row.addWidget(self.cancel); row.addWidget(self.apply); root.addLayout(row)
        self.lower.valueChanged.connect(self.parametersChanged); self.upper.valueChanged.connect(self.parametersChanged)
        self.scope.currentIndexChanged.connect(self._scope_changed); self.connectivity.currentIndexChanged.connect(self.parametersChanged)
        self.apply.clicked.connect(self.applyRequested); self.cancel.clicked.connect(self.cancelRequested)

    def _scope_changed(self):
        current = self.connectivity.currentText()
        self.connectivity.clear(); self.connectivity.addItems(["6", "18", "26"] if self.scope.currentData() == "3d" else ["4", "8"])
        if current in [self.connectivity.itemText(i) for i in range(self.connectivity.count())]: self.connectivity.setCurrentText(current)
        self.parametersChanged.emit()

    def set_seed(self, seed, intensity):
        self.seed.setText(str(tuple(seed))); self.intensity.setText(f"{float(intensity):.6g}")

    def set_result(self, result):
        self.changed.setText(f"{result.changed_voxels:,}"); self.protected.setText(f"{result.protected_voxels:,}")
        self.apply.setEnabled(result.applicable)
        self.help.setText(result.message or "Preview ready. Adjust parameters or Apply as one undoable edit.")

    def reject(self):
        self.cancelRequested.emit()
