"""Label metadata and the colour lookup table used by the overlay renderer.

A ``Label`` is one segmentation object (e.g. "Left kidney"). The ``LabelTable``
owns the ordered set of labels and produces the ``(N, 4)`` uint8 RGBA lookup
table that the 2D viewer and 3D view map integer label ids through. Label id 0
is reserved for background and is always fully transparent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import numpy as np

# A pleasant, high-contrast categorical palette (kidney-friendly warm/cool mix).
_PALETTE: List[Tuple[int, int, int]] = [
    (239, 83, 80),    # red
    (66, 165, 245),   # blue
    (102, 187, 106),  # green
    (255, 167, 38),   # orange
    (171, 71, 188),   # purple
    (38, 198, 218),   # cyan
    (255, 238, 88),   # yellow
    (236, 64, 122),   # pink
    (141, 110, 99),   # brown
    (120, 144, 156),  # blue-grey
    (156, 204, 101),  # lime
    (255, 112, 67),   # deep orange
]


@dataclass
class Label:
    id: int
    name: str
    color: Tuple[int, int, int]
    visible: bool = True


@dataclass
class LabelTable:
    """Ordered labels keyed by integer id (>= 1). Background (0) is implicit."""

    labels: Dict[int, Label] = field(default_factory=dict)
    alpha: int = 128  # overlay opacity 0-255

    # -- construction ----------------------------------------------------
    @classmethod
    def from_ids(cls, ids, names: Dict[int, str] | None = None) -> "LabelTable":
        names = names or {}
        table = cls()
        for i, lid in enumerate(sorted(int(x) for x in ids if int(x) != 0)):
            color = _PALETTE[i % len(_PALETTE)]
            table.labels[lid] = Label(lid, names.get(lid, f"Object {lid}"), color)
        if not table.labels:  # ensure at least one editable label exists
            table.labels[1] = Label(1, "Object 1", _PALETTE[0])
        return table

    # -- mutation --------------------------------------------------------
    def next_free_id(self) -> int:
        i = 1
        while i in self.labels:
            i += 1
        return i

    def add(self, name: str | None = None) -> Label:
        lid = self.next_free_id()
        color = _PALETTE[(lid - 1) % len(_PALETTE)]
        lab = Label(lid, name or f"Object {lid}", color)
        self.labels[lid] = lab
        return lab

    def remove(self, lid: int) -> None:
        self.labels.pop(lid, None)

    # -- lookup table ----------------------------------------------------
    @property
    def max_id(self) -> int:
        return max(self.labels) if self.labels else 1

    def lut(self) -> np.ndarray:
        """Return an ``(max_id+1, 4)`` uint8 RGBA table; row *i* == colour of id *i*."""
        n = self.max_id + 1
        lut = np.zeros((n, 4), dtype=np.uint8)
        for lid, lab in self.labels.items():
            if not lab.visible:
                continue
            lut[lid, 0:3] = lab.color
            lut[lid, 3] = self.alpha
        return lut

    def __iter__(self):
        return iter(sorted(self.labels.values(), key=lambda l: l.id))

    def __len__(self):
        return len(self.labels)
