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

from .geometry import ImageGeometry


@dataclass
class ImageVolume:
    data: np.ndarray                     # 3D, shape (R, C, S)
    spacing: Tuple[float, float, float]  # mm per (row, col, slice)
    affine: np.ndarray                   # 4x4, for saving derived volumes
    path: str = ""
    geometry: ImageGeometry | None = None

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
        if self.geometry is None:
            aff = np.asarray(self.affine, dtype=float)
            if np.allclose(aff, np.eye(4)) and tuple(float(v) for v in self.spacing) != (1.0, 1.0, 1.0):
                aff = np.diag([float(self.spacing[0]), float(self.spacing[1]), float(self.spacing[2]), 1.0])
                self.affine = aff
            self.geometry = ImageGeometry.from_affine(self.data.shape, self.affine, spacing=self.spacing)
        if not self.geometry.validation.ok:
            raise ValueError("; ".join(self.geometry.validation.errors))
        self.spacing = self.geometry.spacing
        self.affine = self.geometry.affine

    @property
    def shape(self) -> Tuple[int, int, int]:
        return self.data.shape  # type: ignore[return-value]

    @property
    def n_slices(self) -> int:
        return self.data.shape[2]

    @property
    def voxel_volume_mm3(self) -> float:
        return float(self.geometry.voxel_volume_mm3 if self.geometry is not None else abs(np.linalg.det(self.affine[:3, :3])))

    def slice(self, z: int) -> np.ndarray:
        return self.data[:, :, int(z)]
