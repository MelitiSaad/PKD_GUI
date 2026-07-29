"""Right-hand panel: labels + volumetry.

Top: the object/label list (colour, visibility, active selection, add/remove).
Middle: overlay opacity.
Bottom: the volume table in voxels / mm³ / mL with a one-click copy formatted for
the reviewer's spreadsheet (which is in mL).
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QColorDialog, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import theme
from ..core.volumetry import LabelVolume, compute_volumes, total_volume


def _swatch(color, size: int = 14) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setBrush(QColor(*color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 0, size, size, 4, 4)
    p.end()
    return QIcon(pm)


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("role", "subtitle")
    return lbl


class LabelPanel(QWidget):
    activeLabelChanged = Signal(int)
    overlayChanged = Signal()
    deleteLabelRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.seg = None
        self.image = None
        self._suppress = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        root.addWidget(_title("OBJECTS"))
        self.active_summary = QLabel("No active object")
        self.active_summary.setProperty("role", "activeObject")
        self.active_summary.setWordWrap(True)
        root.addWidget(self.active_summary)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setMaximumHeight(190)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.itemDoubleClicked.connect(self._rename)
        root.addWidget(self.list)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add")
        self.btn_color = QPushButton("Colour")
        self.btn_del = QPushButton("Remove")
        self.btn_del.setProperty("danger", "true")
        for b in (self.btn_add, self.btn_color, self.btn_del):
            btn_row.addWidget(b)
        self.btn_add.clicked.connect(self._add_label)
        self.btn_color.clicked.connect(self._pick_color)
        self.btn_del.clicked.connect(self._delete_label)
        root.addLayout(btn_row)

        div = QFrame(); div.setProperty("role", "divider"); root.addWidget(div)

        op_row = QHBoxLayout()
        op_row.addWidget(_title("OVERLAY"))
        op_row.addStretch(1)
        self.op_value = QLabel("50%")
        self.op_value.setProperty("role", "muted")
        op_row.addWidget(self.op_value)
        root.addLayout(op_row)
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(50)
        self.opacity.valueChanged.connect(self._on_opacity)
        root.addWidget(self.opacity)

        div2 = QFrame(); div2.setProperty("role", "divider"); root.addWidget(div2)

        vol_head = QHBoxLayout()
        vol_head.addWidget(_title("VOLUMES"))
        vol_head.addStretch(1)
        self.btn_copy = QPushButton("Copy mL")
        self.btn_copy.clicked.connect(self._copy_volumes)
        vol_head.addWidget(self.btn_copy)
        root.addLayout(vol_head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Object", "Voxels", "mm³", "mL"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self.table, 1)

        self.btn_compute = QPushButton("Compute volumes")
        self.btn_compute.setProperty("accent", "true")
        self.btn_compute.clicked.connect(self.recompute)
        root.addWidget(self.btn_compute)

        self._volumes: List[LabelVolume] = []

    # -- context ---------------------------------------------------------
    def set_context(self, image, seg) -> None:
        self.image = image
        self.seg = seg
        self.rebuild()
        self.opacity.setValue(int(round(seg.labels.alpha / 255 * 100)) if seg else 50)

    def rebuild(self) -> None:
        self._suppress = True
        self.list.clear()
        if self.seg is not None:
            for lab in self.seg.labels:
                item = QListWidgetItem(_swatch(lab.color), lab.name)
                item.setData(Qt.ItemDataRole.UserRole, lab.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if lab.visible else Qt.CheckState.Unchecked)
                self.list.addItem(item)
                if lab.id == self.seg.active_id:
                    self.list.setCurrentItem(item)
        self._suppress = False
        self._update_active_summary()

    def _update_active_summary(self) -> None:
        if self.seg is None:
            self.active_summary.setText("Open an image to begin.")
            return
        lab = self.seg.labels.labels.get(self.seg.active_id)
        if lab is None:
            self.active_summary.setText("No active object")
            return
        state = "visible" if lab.visible else "hidden"
        self.active_summary.setText(f"Active object  ·  {lab.name}  (#{lab.id}, {state})")

    def select_label(self, lid: int) -> None:
        """Make ``lid`` the active object (e.g. after clicking a cyst)."""
        for i in range(self.list.count()):
            it = self.list.item(i)
            if int(it.data(Qt.ItemDataRole.UserRole)) == lid:
                self.list.setCurrentItem(it)
                break

    def label_name(self, lid: int) -> str:
        lab = self.seg.labels.labels.get(lid) if self.seg else None
        return lab.name if lab else f"label {lid}"

    def selection_summary(self, lid: int) -> str:
        """Concise transient details for a label selected in a slice viewer."""
        if self.seg is None:
            return "No segmentation loaded"
        volume = next((v for v in self._volumes if v.id == lid), None)
        if volume is None:
            volume = next((v for v in compute_volumes(self.seg, self.image) if v.id == lid), None)
        if volume is None:
            return self.label_name(lid)
        lines = [self.label_name(lid), f"Label ID: {lid}",
                 f"Volume: {volume.ml:,.2f} mL", f"Voxels: {volume.voxels:,}"]
        if volume.mean_intensity is not None:
            lines.append(f"Mean intensity: {volume.mean_intensity:,.1f}")
        return "\n".join(lines)

    def remove_unused_labels(self) -> int:
        """Drop object definitions that don't appear anywhere in the volume."""
        if self.seg is None:
            return 0
        import numpy as np
        present = {int(x) for x in np.unique(self.seg.data)}
        removable = [lab.id for lab in list(self.seg.labels) if lab.id not in present]
        removed = 0
        for lid in removable:
            if len(self.seg.labels) <= 1:
                break
            self.seg.labels.remove(lid)
            removed += 1
        if self.seg.active_id not in self.seg.labels.labels:
            self.seg.active_id = next(iter(self.seg.labels)).id
        self.rebuild()
        self.recompute()
        self.overlayChanged.emit()
        return removed

    # -- label list handlers --------------------------------------------
    def _current_id(self) -> Optional[int]:
        item = self.list.currentItem()
        return None if item is None else int(item.data(Qt.ItemDataRole.UserRole))

    def _on_current_changed(self, cur, _prev) -> None:
        if self._suppress or cur is None or self.seg is None:
            return
        lid = int(cur.data(Qt.ItemDataRole.UserRole))
        self.seg.active_id = lid
        self._update_active_summary()
        self.activeLabelChanged.emit(lid)

    def _on_item_changed(self, item) -> None:
        if self._suppress or self.seg is None:
            return
        lid = int(item.data(Qt.ItemDataRole.UserRole))
        lab = self.seg.labels.labels.get(lid)
        if lab is None:
            return
        lab.visible = item.checkState() == Qt.CheckState.Checked
        if item.text() != lab.name:
            lab.name = item.text()
        self.overlayChanged.emit()

    def _rename(self, item) -> None:
        if self.seg is None:
            return
        lid = int(item.data(Qt.ItemDataRole.UserRole))
        lab = self.seg.labels.labels.get(lid)
        name, ok = QInputDialog.getText(self, "Rename object", "Name:", text=lab.name)
        if ok and name.strip():
            lab.name = name.strip()
            self.rebuild()
            self.recompute()

    def _add_label(self) -> None:
        if self.seg is None:
            return
        lab = self.seg.labels.add()
        self.seg.active_id = lab.id
        self.rebuild()
        self.overlayChanged.emit()

    def _pick_color(self) -> None:
        lid = self._current_id()
        if lid is None or self.seg is None:
            return
        lab = self.seg.labels.labels[lid]
        col = QColorDialog.getColor(QColor(*lab.color), self, "Object colour")
        if col.isValid():
            lab.color = (col.red(), col.green(), col.blue())
            self.rebuild()
            self.overlayChanged.emit()

    def _delete_label(self) -> None:
        lid = self._current_id()
        if lid is not None:
            self.deleteLabelRequested.emit(lid)

    def _on_opacity(self, val: int) -> None:
        self.op_value.setText(f"{val}%")
        if self.seg is not None:
            self.seg.labels.alpha = int(round(val / 100 * 255))
            self.overlayChanged.emit()

    # -- volumes ---------------------------------------------------------
    def recompute(self) -> None:
        if self.seg is None:
            return
        self._volumes = compute_volumes(self.seg, self.image)
        self._fill_table()

    def _fill_table(self) -> None:
        rows = self._volumes + [total_volume(self._volumes)] if self._volumes else []
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            is_total = v.id == -1
            name = QTableWidgetItem(v.name)
            if not is_total and self.seg is not None and v.id in self.seg.labels.labels:
                name.setIcon(_swatch(self.seg.labels.labels[v.id].color))
            vox = QTableWidgetItem(f"{v.voxels:,}")
            mm3 = QTableWidgetItem(f"{v.mm3:,.1f}")
            ml = QTableWidgetItem(f"{v.ml:,.2f}")
            for it in (vox, mm3, ml):
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if is_total:
                for it in (name, vox, mm3, ml):
                    f = it.font(); f.setBold(True); it.setFont(f)
            self.table.setItem(r, 0, name)
            self.table.setItem(r, 1, vox)
            self.table.setItem(r, 2, mm3)
            self.table.setItem(r, 3, ml)

    def _copy_volumes(self) -> None:
        if not self._volumes:
            self.recompute()
        lines = ["Object\tVoxels\tmm3\tmL"]
        for v in self._volumes + [total_volume(self._volumes)]:
            lines.append(f"{v.name}\t{v.voxels}\t{v.mm3:.1f}\t{v.ml:.3f}")
        QGuiApplication.clipboard().setText("\n".join(lines))
