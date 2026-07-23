"""Undo/redo over :class:`EditCommand`s.

Commands are pushed already-applied. The stack is bounded by total byte size
(``MAX_UNDO_BYTES``) so a long QC session can't grow memory without limit; the
oldest commands are dropped first. ``on_change`` is an optional callback the UI
uses to refresh enabled/disabled state of the undo/redo actions.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from ..config import MAX_UNDO_BYTES
from .commands import EditCommand
from .segmentation import Segmentation


class History:
    def __init__(self, seg: Segmentation, max_bytes: int = MAX_UNDO_BYTES):
        self.seg = seg
        self.max_bytes = max_bytes
        self._undo: List[EditCommand] = []
        self._redo: List[EditCommand] = []
        self._bytes = 0
        self.on_change: Optional[Callable[[], None]] = None

    def set_segmentation(self, seg: Segmentation) -> None:
        self.seg = seg
        self.clear()

    def push(self, cmd: Optional[EditCommand]) -> None:
        """Record an already-applied command and clear the redo stack."""
        if cmd is None or cmd.is_empty():
            return
        self._undo.append(cmd)
        self._bytes += cmd.nbytes
        self._redo.clear()
        self._enforce_cap()
        self._changed()

    def undo(self) -> Optional[EditCommand]:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        self._bytes -= cmd.nbytes
        cmd.undo(self.seg)
        self._redo.append(cmd)
        self._changed()
        return cmd

    def redo(self) -> Optional[EditCommand]:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cmd.redo(self.seg)
        self._undo.append(cmd)
        self._bytes += cmd.nbytes
        self._enforce_cap()
        self._changed()
        return cmd

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._bytes = 0
        self._changed()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def last_description(self) -> str:
        return self._undo[-1].description if self._undo else ""

    def _enforce_cap(self) -> None:
        while self._bytes > self.max_bytes and len(self._undo) > 1:
            dropped = self._undo.pop(0)
            self._bytes -= dropped.nbytes

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()
