"""Edit commands.

Every edit in the app — no matter which tool produced it — is represented as a
single :class:`EditCommand`: a set of flat voxel indices with their *old* and
*new* label values. This gives:

* instant, uniform undo/redo (restore old / restore new),
* a compact on-disk journal for crash recovery (§ session.py),
* trivial testability (tools are pure functions that emit commands).

Commands are constructed and validated before mutation. History executes a
command and records it as one rollback-capable logical transaction.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

import numpy as np

from .segmentation import Segmentation


class EditCommand:
    """A validated voxel diff. ``undo`` restores old, ``redo`` applies new."""

    __slots__ = ("flat_idx", "old_vals", "new_vals", "_slices", "description")

    def __init__(self, flat_idx, old_vals, new_vals, slices, description="edit"):
        from .validation import validated_labels
        raw_idx = np.asarray(flat_idx)
        if raw_idx.ndim != 1 or raw_idx.dtype.kind not in "iu" or (raw_idx < 0).any():
            raise ValueError("Edit voxel indices must be a one-dimensional non-negative integer array")
        self.flat_idx = np.ascontiguousarray(raw_idx, dtype=np.int64)
        self.old_vals = validated_labels(np.asarray(old_vals).reshape(-1, 1, 1)).reshape(-1)
        self.new_vals = validated_labels(np.asarray(new_vals).reshape(-1, 1, 1)).reshape(-1)
        self._slices = tuple(sorted({int(s) for s in slices}))
        self.description = description

    def redo(self, seg: Segmentation) -> None:
        seg.data.reshape(-1)[self.flat_idx] = self.new_vals
        seg.mark_edited(self._slices)

    def undo(self, seg: Segmentation) -> None:
        seg.data.reshape(-1)[self.flat_idx] = self.old_vals
        seg.mark_edited(self._slices)

    @property
    def slices(self):
        return self._slices

    @property
    def nbytes(self) -> int:
        return int(self.flat_idx.nbytes + self.old_vals.nbytes + self.new_vals.nbytes)

    def is_empty(self) -> bool:
        return self.flat_idx.size == 0

    def validate_for(self, seg: Segmentation) -> None:
        if not (self.flat_idx.size == self.old_vals.size == self.new_vals.size):
            raise ValueError("Edit command arrays have inconsistent lengths")
        if self.flat_idx.size and (self.flat_idx.min() < 0 or self.flat_idx.max() >= seg.data.size):
            raise IndexError("Edit command contains an out-of-range voxel index")


class StrokeRecorder:
    """Accumulates a freehand brush/eraser stroke into one undoable command.

    Dabs are applied live to ``seg.data``; the *original* value of each voxel is
    remembered on first touch so the whole stroke collapses to a single command
    on :meth:`commit`.
    """

    def __init__(self, seg: Segmentation, description: str = "paint"):
        self.seg = seg
        self.description = description
        self._orig: Dict[int, int] = {}
        self._slices: set[int] = set()

    def stamp(self, z: int, rows: np.ndarray, cols: np.ndarray, value: int) -> bool:
        """Axial convenience: rows->axis0, cols->axis1, at depth z (axis2)."""
        rows = np.asarray(rows).ravel()
        cols = np.asarray(cols).ravel()
        zc = np.full(rows.shape, int(z), dtype=np.intp)
        return self.stamp_voxels(rows, cols, zc, value)

    def stamp_voxels(self, ii: np.ndarray, jj: np.ndarray, kk: np.ndarray, value: int) -> bool:
        """Apply a dab at explicit voxel coordinates (any plane maps to this)."""
        data = self.seg.data
        R, C, S = data.shape
        ii = np.asarray(ii).ravel()
        jj = np.asarray(jj).ravel()
        kk = np.asarray(kk).ravel()
        m = (ii >= 0) & (ii < R) & (jj >= 0) & (jj < C) & (kk >= 0) & (kk < S)
        ii, jj, kk = ii[m], jj[m], kk[m]
        if ii.size == 0:
            return False
        flat = np.unique(np.ravel_multi_index(
            (ii.astype(np.intp), jj.astype(np.intp), kk.astype(np.intp)), (R, C, S)))
        flatv = data.reshape(-1)
        # A dab that already has the requested value is a no-op.  Filtering it
        # before recording avoids retaining large, redundant diffs while a
        # stroke overlaps its previous dabs.
        flat = flat[flatv[flat] != np.uint16(value)]
        if flat.size == 0:
            return False
        unseen = [int(f) for f in flat if int(f) not in self._orig]
        if unseen:
            unseen_arr = np.asarray(unseen, dtype=np.int64)
            for f, ov in zip(unseen, flatv[unseen_arr]):
                self._orig[f] = int(ov)
        flatv[flat] = np.uint16(value)
        self._slices.update(int(z) for z in np.unique(kk).tolist())  # axial slices touched
        return True

    def commit(self) -> Optional[EditCommand]:
        if not self._orig:
            return None
        flat = np.fromiter(self._orig.keys(), dtype=np.int64, count=len(self._orig))
        old = np.fromiter(self._orig.values(), dtype=np.uint16, count=len(self._orig))
        new = self.seg.data.reshape(-1)[flat].copy()
        changed = old != new
        if not changed.any():
            return None
        return EditCommand(flat[changed], old[changed], new[changed], self._slices, self.description)

    def rollback(self) -> None:
        """Restore every voxel touched by this live stroke exactly."""
        if self._orig:
            flat = np.fromiter(self._orig, dtype=np.int64, count=len(self._orig))
            old = np.fromiter(self._orig.values(), dtype=np.uint16, count=len(self._orig))
            self.seg.data.reshape(-1)[flat] = old


def combine_commands(commands: Iterable[EditCommand], description: str) -> Optional[EditCommand]:
    """Combine disjoint calculated edits into one atomic history transaction."""
    items = [cmd for cmd in commands if cmd is not None and not cmd.is_empty()]
    if not items:
        return None
    flat = np.concatenate([cmd.flat_idx for cmd in items])
    if np.unique(flat).size != flat.size:
        raise ValueError("Compound edit contains overlapping voxel changes")
    return EditCommand(
        flat,
        np.concatenate([cmd.old_vals for cmd in items]),
        np.concatenate([cmd.new_vals for cmd in items]),
        (s for cmd in items for s in cmd.slices),
        description,
    )


# --- builders for region edits (fill / morphology / interpolation / threshold) ---
def apply_slice(seg: Segmentation, z: int, new_slice: np.ndarray, description: str) -> Optional[EditCommand]:
    """Calculate a replacement-slice diff without mutating the segmentation."""
    z = int(z)
    R, C, _ = seg.data.shape
    old_slice = seg.data[:, :, z]
    from .validation import validated_labels
    if new_slice.ndim != 2:
        raise ValueError("Replacement slice must be 2D")
    # Validate through a temporary singleton volume without lossy conversion.
    new_slice = validated_labels(new_slice[:, :, None])[:, :, 0]
    changed = np.flatnonzero(old_slice.ravel() != new_slice.ravel())
    if changed.size == 0:
        return None
    # Convert 2D (row-major over (R,C)) indices to full 3D flat indices at slice z.
    rows, cols = np.divmod(changed, C)
    zc = np.full(rows.shape, z, dtype=np.intp)
    flat = np.ravel_multi_index((rows.astype(np.intp), cols.astype(np.intp), zc), (R, C, seg.data.shape[2]))
    old = old_slice.ravel()[changed].copy()
    new = new_slice.ravel()[changed].copy()
    return EditCommand(flat, old, new, [z], description)


def apply_volume(seg: Segmentation, new_volume: np.ndarray, description: str,
                 slices: Optional[Iterable[int]] = None) -> Optional[EditCommand]:
    """Calculate a replacement-volume diff without mutating the segmentation."""
    from .validation import validated_labels
    new_volume = validated_labels(new_volume)
    if new_volume.shape != seg.data.shape:
        raise ValueError("Replacement volume shape does not match segmentation")
    old_flat = seg.data.reshape(-1)
    new_flat = new_volume.reshape(-1)
    changed = np.flatnonzero(old_flat != new_flat)
    if changed.size == 0:
        return None
    old = old_flat[changed].copy()
    new = new_flat[changed].copy()
    if slices is None:
        S = seg.data.shape[2]
        slices = np.unique(changed % S).tolist()
    return EditCommand(changed.astype(np.int64), old, new, slices, description)


def apply_plane_slice(seg: Segmentation, plane, cursor, new_slice2d: np.ndarray,
                      description: str) -> Optional[EditCommand]:
    """Diff a replacement 2D slice on an arbitrary plane and apply it (any orientation)."""
    cur2d = plane.slice2d(seg.data, cursor)
    from .validation import validated_labels
    new_slice2d = validated_labels(np.asarray(new_slice2d)[:, :, None])[:, :, 0]
    diff = cur2d != new_slice2d
    if not diff.any():
        return None
    vv, hh = np.nonzero(diff)
    ii, jj, kk = plane.disp_to_vox_arrays(vv, hh, cursor, seg.data.shape)
    R, C, S = seg.data.shape
    flat = np.ravel_multi_index((ii, jj, kk), (R, C, S))
    flatv = seg.data.reshape(-1)
    old = flatv[flat].copy()
    new = new_slice2d[vv, hh].astype(np.uint16)
    slices = np.unique(kk).tolist()
    return EditCommand(flat.astype(np.int64), old, new, slices, description)
