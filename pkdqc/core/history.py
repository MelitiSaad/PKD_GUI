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
        self._undo_states: List[int] = []
        self._redo_states: List[int] = []
        self._next_state = seg.revision + 1
        self._base_state = seg.revision
        self.on_change: Optional[Callable[[], None]] = None

    def set_segmentation(self, seg: Segmentation) -> None:
        self.seg = seg
        self.clear()

    def push(self, cmd: Optional[EditCommand]) -> None:
        """Execute and record a command atomically."""
        if cmd is None or cmd.is_empty():
            return
        cmd.validate_for(self.seg)
        data_before = self.seg.data.copy()
        state = (list(self._undo), list(self._redo), self._bytes,
                 self.seg.revision, self.seg.dirty, set(self.seg.edited_slices),
                 list(self._undo_states), list(self._redo_states), self._next_state)
        try:
            cmd.redo(self.seg)
            self._undo.append(cmd)
            self.seg.revision = self._next_state; self._next_state += 1
            self._undo_states.append(self.seg.revision); self._redo_states.clear()
            self._bytes += cmd.nbytes
            self._redo.clear()
            self._enforce_cap()
            self._changed()
        except BaseException:
            self.seg.data[...] = data_before
            self._undo[:], self._redo[:], self._bytes = state[0], state[1], state[2]
            self.seg.revision, self.seg.dirty = state[3], state[4]
            self.seg.edited_slices = state[5]
            self._undo_states[:], self._redo_states[:], self._next_state = state[6:]
            raise

    def record_applied(self, cmd: Optional[EditCommand]) -> None:
        """Atomically record a live-applied stroke, rolling it back on failure."""
        if cmd is None or cmd.is_empty():
            return
        cmd.validate_for(self.seg)
        # The command's old values are a byte-exact rollback snapshot.
        state = (list(self._undo), list(self._redo), self._bytes,
                 self.seg.revision, self.seg.dirty, set(self.seg.edited_slices),
                 list(self._undo_states), list(self._redo_states), self._next_state)
        try:
            self._undo.append(cmd); self._bytes += cmd.nbytes; self._redo.clear()
            self.seg.mark_edited(cmd.slices)
            self.seg.revision = self._next_state; self._next_state += 1
            self._undo_states.append(self.seg.revision); self._redo_states.clear()
            self._enforce_cap(); self._changed()
        except BaseException:
            self.seg.data.reshape(-1)[cmd.flat_idx] = cmd.old_vals
            self._undo[:], self._redo[:], self._bytes = state[0], state[1], state[2]
            self.seg.revision, self.seg.dirty = state[3], state[4]
            self.seg.edited_slices = state[5]
            self._undo_states[:], self._redo_states[:], self._next_state = state[6:]
            raise

    def undo(self) -> Optional[EditCommand]:
        if not self._undo:
            return None
        before = self.seg.data.copy()
        state = (list(self._undo), list(self._redo), self._bytes,
                 self.seg.revision, self.seg.dirty, set(self.seg.edited_slices),
                 list(self._undo_states), list(self._redo_states), self._next_state)
        cmd = self._undo[-1]
        try:
            undone_state = self._undo_states.pop()
            cmd.undo(self.seg); self._undo.pop(); self._bytes -= cmd.nbytes
            self._redo.append(cmd); self._changed()
            self._redo_states.append(undone_state)
            self.seg.revision = self._undo_states[-1] if self._undo_states else self._base_state
        except BaseException:
            self.seg.data[...] = before
            self._undo[:], self._redo[:], self._bytes = state[:3]
            self.seg.revision, self.seg.dirty, self.seg.edited_slices = state[3], state[4], state[5]
            self._undo_states[:], self._redo_states[:], self._next_state = state[6:]
            raise
        return cmd

    def redo(self) -> Optional[EditCommand]:
        if not self._redo:
            return None
        before = self.seg.data.copy()
        state = (list(self._undo), list(self._redo), self._bytes,
                 self.seg.revision, self.seg.dirty, set(self.seg.edited_slices),
                 list(self._undo_states), list(self._redo_states), self._next_state)
        cmd = self._redo[-1]
        try:
            restored_state = self._redo_states.pop()
            cmd.redo(self.seg); self._redo.pop(); self._undo.append(cmd)
            self.seg.revision = restored_state; self._undo_states.append(restored_state)
            self._bytes += cmd.nbytes; self._enforce_cap(); self._changed()
        except BaseException:
            self.seg.data[...] = before
            self._undo[:], self._redo[:], self._bytes = state[:3]
            self.seg.revision, self.seg.dirty, self.seg.edited_slices = state[3], state[4], state[5]
            self._undo_states[:], self._redo_states[:], self._next_state = state[6:]
            raise
        return cmd

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._bytes = 0
        self._undo_states.clear(); self._redo_states.clear()
        self._base_state = self.seg.revision
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
            self._base_state = self._undo_states.pop(0)
            self._bytes -= dropped.nbytes

    def _changed(self) -> None:
        if self.on_change:
            self.on_change()
