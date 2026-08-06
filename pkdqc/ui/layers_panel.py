"""Compact controls for the independent segmentation-layer stack."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSlider, QVBoxLayout, QWidget)


class LayersPanel(QWidget):
    activeRequested = Signal(str)
    visibilityRequested = Signal(str, bool)
    opacityRequested = Signal(str, float)
    addExistingRequested = Signal()
    addBlankRequested = Signal()
    renameRequested = Signal(str)
    removeRequested = Signal(str)
    moveRequested = Signal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent); self._layers = None; self._syncing = False
        root = QVBoxLayout(self); root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(QLabel("SEGMENTATION LAYERS  ·  3D shows active only"))
        self.list = QListWidget(); self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.currentItemChanged.connect(self._selected); self.list.itemChanged.connect(self._changed)
        root.addWidget(self.list)
        row = QHBoxLayout(); self.add_existing = QPushButton("Add file"); self.add_blank = QPushButton("Add blank")
        self.rename = QPushButton("Rename"); self.remove = QPushButton("Remove")
        for w in (self.add_existing, self.add_blank, self.rename, self.remove): row.addWidget(w)
        root.addLayout(row)
        row2 = QHBoxLayout(); self.down = QPushButton("Down"); self.up = QPushButton("Up")
        row2.addWidget(self.down); row2.addWidget(self.up); row2.addWidget(QLabel("Opacity"))
        self.opacity = QSlider(Qt.Orientation.Horizontal); self.opacity.setRange(0, 100); row2.addWidget(self.opacity)
        root.addLayout(row2)
        self.add_existing.clicked.connect(self.addExistingRequested); self.add_blank.clicked.connect(self.addBlankRequested)
        self.rename.clicked.connect(lambda: self._emit_id(self.renameRequested))
        self.remove.clicked.connect(lambda: self._emit_id(self.removeRequested))
        self.up.clicked.connect(lambda: self._move(+1)); self.down.clicked.connect(lambda: self._move(-1))
        self.opacity.valueChanged.connect(self._opacity)

    def set_layers(self, layers):
        self._layers = layers; self.refresh()

    def refresh(self):
        self._syncing = True; self.list.clear()
        if self._layers is not None:
            for layer in self._layers:
                text = ("✎ " if layer.layer_id == self._layers.active_layer_id else "") + layer.name + (" *" if layer.dirty else "")
                item = QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole, layer.layer_id)
                item.setToolTip(layer.path or "Not yet saved."); item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked)
                self.list.addItem(item)
                if layer.layer_id == self._layers.active_layer_id: self.list.setCurrentItem(item)
        active = self._layers.active if self._layers is not None else None
        self.opacity.setEnabled(active is not None); self.opacity.setValue(round(active.opacity * 100) if active else 50)
        enabled = active is not None
        for b in (self.rename, self.remove, self.up, self.down): b.setEnabled(enabled)
        self._syncing = False

    def _id(self):
        item = self.list.currentItem(); return item.data(Qt.ItemDataRole.UserRole) if item else None
    def _emit_id(self, signal):
        layer_id = self._id()
        if layer_id: signal.emit(layer_id)
    def _selected(self, item, _old):
        if not self._syncing and item: self.activeRequested.emit(item.data(Qt.ItemDataRole.UserRole))
    def _changed(self, item):
        if not self._syncing: self.visibilityRequested.emit(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)
    def _opacity(self, value):
        layer_id = self._id()
        if not self._syncing and layer_id: self.opacityRequested.emit(layer_id, value / 100.0)
    def _move(self, delta):
        layer_id = self._id()
        if layer_id: self.moveRequested.emit(layer_id, delta)
