"""Modal dialogs: crash recovery, keyboard-shortcut editor, about."""
from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QKeySequenceEdit, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
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
            item = QListWidgetItem(f"{name}   ·   last autosaved {r.age_str}")
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
    def __init__(self, actions: List[Tuple[str, str, QAction]], settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumWidth(420)
        self._actions = actions
        self._settings = settings
        self._editors: Dict[str, QKeySequenceEdit] = {}

        lay = QVBoxLayout(self)
        for action_id, label, action in actions:
            row = QHBoxLayout()
            name = QLabel(label)
            name.setMinimumWidth(180)
            edit = QKeySequenceEdit(action.shortcut())
            self._editors[action_id] = edit
            row.addWidget(name)
            row.addWidget(edit, 1)
            lay.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self) -> None:
        stored = {}
        for action_id, _label, action in self._actions:
            seq = self._editors[action_id].keySequence()
            action.setShortcut(seq)
            stored[action_id] = seq.toString()
        self._settings.setValue(config.SK_SHORTCUTS, stored)
        self.accept()


def about_html() -> str:
    return (
        f"<h3>{config.APP_NAME}</h3>"
        f"<p>Version {config.VERSION}</p>"
        "<p>Quality-control and volume measurement for kidney segmentations.</p>"
        "<p style='color:#98A2B3'>Load an image, overlay a segmentation, correct it "
        "slice by slice, and export volumes in mm³ and mL.</p>"
    )
