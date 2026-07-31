"""One reusable draw-over policy for every voxel-modifying tool."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class DrawOver(str, Enum):
    BACKGROUND_ONLY = "background_only"
    SELECTED_LABEL = "selected_label"
    ALL_PERMITTED = "all_permitted"


@dataclass(frozen=True)
class LabelProtectionPolicy:
    """Describe which current labels may be replaced by a requested value.

    Hidden labels receive exactly the same protection as visible labels. Locking
    is label metadata, not a rendering property, and always takes precedence.
    """
    mode: DrawOver = DrawOver.BACKGROUND_ONLY
    selected_label: int | None = None
    locked_labels: frozenset[int] = frozenset()
    erase_selected_only: bool = True

    def writable(self, current, target: int) -> np.ndarray:
        values = np.asarray(current)
        locked = np.isin(values, tuple(self.locked_labels)) if self.locked_labels else np.zeros(values.shape, bool)
        if target == 0:
            allowed = values != 0
            if self.erase_selected_only:
                allowed &= values == self.selected_label
        elif self.mode is DrawOver.BACKGROUND_ONLY:
            allowed = (values == 0) | (values == target)
        elif self.mode is DrawOver.SELECTED_LABEL:
            allowed = (values == 0) | (values == target) | (values == self.selected_label)
        else:
            allowed = np.ones(values.shape, dtype=bool)
        return allowed & ~locked


def policy_for(seg, *, protect_existing: bool = True, selected_label: int | None = None) -> LabelProtectionPolicy:
    locked = frozenset(l.id for l in seg.labels if l.locked)
    return LabelProtectionPolicy(
        DrawOver.BACKGROUND_ONLY if protect_existing else DrawOver.ALL_PERMITTED,
        selected_label=int(seg.active_id if selected_label is None else selected_label), locked_labels=locked,
    )
