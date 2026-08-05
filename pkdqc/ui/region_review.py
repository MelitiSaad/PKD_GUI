"""Compact Region Review panel.

The widget is intentionally thin: all indexing, measurements, persistence, and
safe deletion rules live in :mod:`pkdqc.core.regions` so they are testable
without Qt.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..core.regions import DEFAULT_CONNECTIVITY, GroupingMode, RegionIndex, RegionReviewState


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "subtitle")
    return label


class RegionReviewPanel(QWidget):
    toggled = Signal()
    rebuildRequested = Signal()
    nextRequested = Signal()
    previousRequested = Signal()
    reviewedRequested = Signal()
    unreviewedRequested = Signal()
    deleteRegionRequested = Signal()
    deleteLabelRequested = Signal()
    isolateRequested = Signal()
    clearProgressRequested = Signal()
    groupingChanged = Signal(str)
    connectivityChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")
        self.active = False
        self.index: RegionIndex | None = None
        self.state = RegionReviewState(connectivity=DEFAULT_CONNECTIVITY)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)
        root.addWidget(_title("REGION REVIEW"))
        self.status = QLabel("Not active")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.grouping = QComboBox()
        self.grouping.addItem("Connected regions", GroupingMode.CONNECTED.value)
        self.grouping.addItem("Labels/colors", GroupingMode.LABELS.value)
        self.grouping.addItem("Labels with connected regions", GroupingMode.LABELS_WITH_COMPONENTS.value)
        root.addWidget(QLabel("Group regions by")); root.addWidget(self.grouping)

        self.connectivity = QComboBox()
        for value in (6, 18, 26):
            self.connectivity.addItem(f"{value}-neighbour", value)
        self.connectivity.setCurrentIndex(2)
        root.addWidget(QLabel("Connectivity")); root.addWidget(self.connectivity)

        row = QHBoxLayout()
        self.btn_toggle = QPushButton("Enter")
        self.btn_rebuild = QPushButton("Rebuild")
        row.addWidget(self.btn_toggle); row.addWidget(self.btn_rebuild)
        root.addLayout(row)

        row2 = QHBoxLayout()
        self.btn_prev = QPushButton("Previous")
        self.btn_next = QPushButton("Next")
        row2.addWidget(self.btn_prev); row2.addWidget(self.btn_next)
        root.addLayout(row2)

        self.btn_reviewed = QPushButton("Reviewed + next")
        self.btn_unreviewed = QPushButton("Mark unreviewed")
        root.addWidget(self.btn_reviewed); root.addWidget(self.btn_unreviewed)

        div = QFrame(); div.setProperty("role", "divider"); root.addWidget(div)
        self.details = QLabel("Open a segmentation to review connected regions or labels.")
        self.details.setWordWrap(True)
        root.addWidget(self.details)

        self.btn_delete_region = QPushButton("Delete current connected region")
        self.btn_delete_region.setProperty("danger", "true")
        self.btn_delete_label = QPushButton("Delete entire label…")
        self.btn_delete_label.setProperty("danger", "true")
        self.btn_isolate = QPushButton("Isolate / show all")
        self.btn_clear = QPushButton("Clear progress")
        for b in (self.btn_delete_region, self.btn_delete_label, self.btn_isolate, self.btn_clear):
            root.addWidget(b)
        root.addStretch(1)

        self.btn_toggle.clicked.connect(self.toggled.emit)
        self.btn_rebuild.clicked.connect(self.rebuildRequested.emit)
        self.btn_next.clicked.connect(self.nextRequested.emit)
        self.btn_prev.clicked.connect(self.previousRequested.emit)
        self.btn_reviewed.clicked.connect(self.reviewedRequested.emit)
        self.btn_unreviewed.clicked.connect(self.unreviewedRequested.emit)
        self.btn_delete_region.clicked.connect(self.deleteRegionRequested.emit)
        self.btn_delete_label.clicked.connect(self.deleteLabelRequested.emit)
        self.btn_isolate.clicked.connect(self.isolateRequested.emit)
        self.btn_clear.clicked.connect(self.clearProgressRequested.emit)
        self.grouping.currentIndexChanged.connect(lambda _i: self.groupingChanged.emit(str(self.grouping.currentData())))
        self.connectivity.currentIndexChanged.connect(lambda _i: self.connectivityChanged.emit(int(self.connectivity.currentData())))
        self.set_available(False)

    def set_available(self, available: bool) -> None:
        for w in (self.btn_toggle, self.btn_rebuild, self.btn_next, self.btn_prev, self.btn_reviewed,
                  self.btn_unreviewed, self.btn_delete_region, self.btn_delete_label, self.btn_isolate,
                  self.btn_clear, self.grouping, self.connectivity):
            w.setEnabled(bool(available))

    def set_index(self, index: RegionIndex | None, state: RegionReviewState, *, indexing: bool = False, stale: bool = False) -> None:
        self.index = index
        self.state = state
        self.active = True if self.active else False
        if indexing:
            self.status.setText("Indexing regions…")
        elif index is None:
            self.status.setText("No region index")
        else:
            cur = state.current(index)
            total = len(state.queue(index))
            pos = 0 if cur is None else state.current_position + 1
            suffix = " · stale" if stale else ""
            self.status.setText(f"Region {pos} of {total} · revision {index.revision}{suffix}")
            self.details.setText(_details(index, state))
        self.btn_toggle.setText("Leave" if self.active else "Enter")


def _details(index: RegionIndex, state: RegionReviewState) -> str:
    cur = state.current(index)
    if cur is None:
        return f"Total included volume: {index.total_volume_mm3:,.1f} mm³ ({index.total_volume_ml:,.3f} mL)"
    label = index.labels[cur.label_id]
    flags = ", ".join(cur.flags) if cur.flags else "none"
    return (
        f"Label {cur.label_id} · {cur.label_name}\n"
        f"Component: {cur.voxel_count:,} voxels · {cur.volume_mm3:,.1f} mm³ · {cur.volume_ml:,.3f} mL\n"
        f"Label total: {label.voxel_count:,} voxels · {label.volume_mm3:,.1f} mm³ · {label.volume_ml:,.3f} mL\n"
        f"Included total: {index.total_volume_mm3:,.1f} mm³ · {index.total_volume_ml:,.3f} mL\n"
        f"State: {cur.review_state}; flags: {flags}"
    )
