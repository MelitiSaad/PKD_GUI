"""The editable label volume overlaid on the image.

Holds the integer label array (same shape as the image), the :class:`LabelTable`,
the currently active label being painted, and a monotonically increasing
``revision`` counter plus an ``edited_slices`` set so the viewer, autosave, and
"jump to next edited slice" can all react to changes cheaply.
"""
from __future__ import annotations

from typing import Iterable, Set

import numpy as np

from .labels import LabelTable
from .validation import validated_labels


class Segmentation:
    def __init__(self, data: np.ndarray, labels: LabelTable | None = None):
        # Validate before conversion: labels must never be rounded or wrapped.
        self.data = validated_labels(data)
        ids = np.unique(self.data)
        self.labels = labels or LabelTable.from_ids(ids)
        self.active_id: int = next(iter(self.labels)).id if len(self.labels) else 1
        self.revision: int = 0
        self.dirty: bool = False
        self.edited_slices: Set[int] = set()

    # -- factory ---------------------------------------------------------
    @classmethod
    def empty_like(cls, shape) -> "Segmentation":
        return cls(np.zeros(shape, dtype=np.uint16))

    # -- access ----------------------------------------------------------
    def slice(self, z: int) -> np.ndarray:
        return self.data[:, :, int(z)]

    def max_id(self) -> int:
        return self.labels.max_id

    # -- change notification --------------------------------------------
    def mark_edited(self, slices: Iterable[int]) -> None:
        self.revision += 1
        self.dirty = True
        for z in slices:
            self.edited_slices.add(int(z))

    def clear_dirty(self) -> None:
        self.dirty = False
