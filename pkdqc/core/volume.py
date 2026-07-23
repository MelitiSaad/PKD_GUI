"""The grayscale image volume being reviewed.

Orientation is canonicalised at load time (see ``io.py``) so the rest of the app
can treat the array with a fixed convention:

    data[row, col, slice]   # axial slice == data[:, :, z]

Spacing is stored per axis in millimetres, taken from the image header.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class ImageVolume:
    data: np.ndarray                     # 3D, shape (R, C, S)
    spacing: Tuple[float, float, float]  # mm per (row, col, slice)
    affine: np.ndarray                   # 4x4, for saving derived volumes
    path: str = ""

    def __post_init__(self):
        if self.data.ndim != 3:
            raise ValueError(f"Image must be 3D, got shape {self.data.shape}")
        # Precompute robust default window (2nd..98th percentile) once.
        finite = self.data[np.isfinite(self.data)]
        if finite.size:
            lo, hi = np.percentile(finite, (2.0, 98.0))
            if hi <= lo:
                lo, hi = float(finite.min()), float(finite.max() or 1.0)
        else:
            lo, hi = 0.0, 1.0
        self.default_window: Tuple[float, float] = (float(lo), float(hi))

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self.data.shape  # type: ignore[return-value]

    @property
    def n_slices(self) -> int:
        return self.data.shape[2]

    @property
    def voxel_volume_mm3(self) -> float:
        sr, sc, ss = self.spacing
        return float(sr * sc * ss)

    def slice(self, z: int) -> np.ndarray:
        return self.data[:, :, int(z)]
