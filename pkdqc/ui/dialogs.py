"""Modal dialogs: crash recovery, keyboard-shortcut editor, about."""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QKeySequenceEdit, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .. import config


class RecoveryDialog(QDialog):
    """Offered at startup when unsaved sessions from a previous crash are found."""

    def __init__(self, recs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recover unsaved work")
        self.setMinimumWidth(460)
        self.chosen = None            # -> a Recoverable or None
        self.action = "skip"          # 'recover' | 'discard' | 'skip'

        lay = QVBoxLayout(self)
        head = QLabel("It looks like the app closed unexpectedly. "
                      "These segmentations have unsaved changes:")
        head.setWordWrap(True)
        lay.addWidget(head)

        self.list = QListWidget()
        for r in recs:
            name = os.path.basename(r.image_path)
            fallback = "   ·   using an older verified checkpoint" if r.warning else ""
            item = QListWidgetItem(f"{name}   ·   last checkpoint {r.age_str}{fallback}")
            item.setData(Qt.ItemDataRole.UserRole, r)
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        lay.addWidget(self.list)

        row = QHBoxLayout()
        btn_recover = QPushButton("Recover")
        btn_recover.setProperty("accent", "true")
        btn_discard = QPushButton("Discard")
        btn_discard.setProperty("danger", "true")
        btn_skip = QPushButton("Not now")
        row.addWidget(btn_recover)
        row.addWidget(btn_discard)
        row.addStretch(1)
        row.addWidget(btn_skip)
        lay.addLayout(row)

        btn_recover.clicked.connect(lambda: self._choose("recover"))
        btn_discard.clicked.connect(lambda: self._choose("discard"))
        btn_skip.clicked.connect(lambda: self._choose("skip"))

    def _choose(self, action: str) -> None:
        self.action = action
        item = self.list.currentItem()
        self.chosen = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.accept()


class ShortcutsDialog(QDialog):
    def __init__(self, registry, actions: Dict[str, QAction], settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumWidth(640)
        self._registry = registry
        self._actions = actions
        self._settings = settings
        self._editors: Dict[str, QKeySequenceEdit] = {}
        self._rows: Dict[str, QWidget] = {}

        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText("Search commands")
        self.category = QComboBox(); self.category.addItem("All categories")
        for cat in sorted({spec.category for spec in registry.values()}):
            self.category.addItem(cat)
        top.addWidget(self.search, 1); top.addWidget(self.category)
        lay.addLayout(top)
        for action_id, spec in sorted(registry.items(), key=lambda kv: (kv[1].category, kv[1].label)):
            roww = QWidget(); row = QHBoxLayout(roww); row.setContentsMargins(0, 0, 0, 0)
            name = QLabel(f"{spec.label}\n{spec.category}"); name.setMinimumWidth(240)
            edit = QKeySequenceEdit(actions[action_id].shortcut())
            clear = QPushButton("Clear"); clear.clicked.connect(lambda _=False, e=edit: e.clear())
            self._editors[action_id] = edit; self._rows[action_id] = roww
            row.addWidget(name); row.addWidget(edit, 1); row.addWidget(clear)
            lay.addWidget(roww)
        reset = QPushButton("Reset recommended defaults")
        reset.clicked.connect(self._reset_defaults)
        lay.addWidget(reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save); buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        self.search.textChanged.connect(self._filter); self.category.currentTextChanged.connect(self._filter)

    def _filter(self):
        text = self.search.text().strip().lower(); cat = self.category.currentText()
        for aid, spec in self._registry.items():
            visible = (cat == "All categories" or spec.category == cat) and (not text or text in spec.label.lower() or text in aid.lower())
            self._rows[aid].setVisible(visible)

    def _reset_defaults(self) -> None:
        for aid, spec in self._registry.items():
            self._editors[aid].setKeySequence(QKeySequence(spec.default))

    def _save(self) -> None:
        stored = {aid: self._editors[aid].keySequence().toString() for aid in self._registry}
        from ..core.shortcuts import shortcut_conflicts
        conflicts = shortcut_conflicts(stored, self._registry)
        if conflicts:
            detail = "\n".join(f"{key}: " + ", ".join(self._registry[a].label for a in aids) for key, aids in conflicts.items())
            QMessageBox.warning(self, "Shortcut conflict", "Resolve duplicate shortcuts before saving.\n" + detail)
            return
        self._settings.setValue(config.SK_SHORTCUTS, stored)
        for action_id, key in stored.items():
            self._actions[action_id].setShortcut(QKeySequence(key))
        self.accept()


def about_html() -> str:
    return (
        f"<h3>{config.APP_NAME}</h3>"
        f"<p>Version {config.VERSION}</p>"
        "<p>Quality-control and volume measurement for kidney segmentations.</p>"
        "<p style='color:#98A2B3'>Load an image, overlay a segmentation, correct it "
        "slice by slice, and export volumes in mm³ and mL.</p>"
    )

class DicomSeriesDialog(QDialog):
    """Minimal PHI-safe chooser for valid DICOM image series."""
    def __init__(self, candidates, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select DICOM series")
        self.chosen = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Multiple valid DICOM image series were found. Select one to load."))
        self.list = QListWidget()
        self._candidates = list(candidates)
        for candidate in self._candidates:
            self.list.addItem(candidate.display_description)
        self.list.setCurrentRow(0)
        layout.addWidget(self.list)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self):
        row = self.list.currentRow()
        if 0 <= row < len(self._candidates):
            self.chosen = self._candidates[row]
        super().accept()
