"""Orthogonal plane geometry for multi-planar reconstruction.

One volume is viewed through three orthogonal planes (axial / coronal / sagittal),
ITK-SNAP style. This module is the single source of truth for how a plane maps to
and from voxel indices, so both display and painting stay consistent.

Volume axes follow the canonicalised RAS+ convention used on load:
    axis 0 = X (left–right), axis 1 = Y (post–ant), axis 2 = Z (inf–sup)

For every plane the on-screen image is arranged (vertical, horizontal) with the
larger-numbered spatial axis vertical, and flipped so the anatomical "max"
(anterior / superior / one side) sits at top-left. Every transform has an exact
inverse (verified by round-trip tests) so a brush dab on any plane writes the
right voxels.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

AXIAL = "axial"
CORONAL = "coronal"
SAGITTAL = "sagittal"


@dataclass(frozen=True)
class Plane:
    name: str
    depth_axis: int  # the volume axis you scroll through

    @property
    def _others(self):
        return tuple(a for a in (0, 1, 2) if a != self.depth_axis)

    @property
    def lo(self) -> int:  # horizontal axis (lower-numbered in-plane axis)
        return self._others[0]

    @property
    def hi(self) -> int:  # vertical axis (higher-numbered in-plane axis)
        return self._others[1]

    def depth_len(self, shape) -> int:
        return int(shape[self.depth_axis])

    def vertical_len(self, shape) -> int:
        return int(shape[self.hi])

    def horizontal_len(self, shape) -> int:
        return int(shape[self.lo])

    def spacing_vh(self, spacing) -> Tuple[float, float]:
        return float(spacing[self.hi]), float(spacing[self.lo])

    def depth_spacing(self, spacing) -> float:
        return float(spacing[self.depth_axis])

    # -- extraction ------------------------------------------------------
    def slice2d(self, data: np.ndarray, cursor) -> np.ndarray:
        """Return the 2D display array (V, H) for this plane at the cursor depth."""
        di = int(np.clip(cursor[self.depth_axis], 0, data.shape[self.depth_axis] - 1))
        sl = np.take(data, di, axis=self.depth_axis)   # (lo_len, hi_len)
        arr = sl.T                                       # (hi_len, lo_len) = (V, H)
        arr = arr[::-1, ::-1]                            # max of each axis to top / left
        return np.ascontiguousarray(arr)

    # -- mapping ---------------------------------------------------------
    def disp_to_vox(self, v: int, h: int, cursor, shape) -> Tuple[int, int, int]:
        hi_len, lo_len = shape[self.hi], shape[self.lo]
        vox = [0, 0, 0]
        vox[self.hi] = hi_len - 1 - int(v)
        vox[self.lo] = lo_len - 1 - int(h)
        vox[self.depth_axis] = int(np.clip(cursor[self.depth_axis], 0, shape[self.depth_axis] - 1))
        return tuple(vox)  # type: ignore[return-value]

    def disp_to_vox_arrays(self, vv: np.ndarray, hh: np.ndarray, cursor, shape):
        hi_len, lo_len = shape[self.hi], shape[self.lo]
        out = [None, None, None]
        out[self.hi] = (hi_len - 1 - vv.astype(np.intp))
        out[self.lo] = (lo_len - 1 - hh.astype(np.intp))
        di = int(np.clip(cursor[self.depth_axis], 0, shape[self.depth_axis] - 1))
        out[self.depth_axis] = np.full(vv.shape, di, dtype=np.intp)
        return out[0], out[1], out[2]

    def vox_to_disp(self, cursor, shape) -> Tuple[int, int]:
        hi_len, lo_len = shape[self.hi], shape[self.lo]
        v = hi_len - 1 - int(cursor[self.hi])
        h = lo_len - 1 - int(cursor[self.lo])
        return v, h


PLANES = {
    AXIAL: Plane(AXIAL, 2),
    CORONAL: Plane(CORONAL, 1),
    SAGITTAL: Plane(SAGITTAL, 0),
}

ORDER = (AXIAL, CORONAL, SAGITTAL)


def display_aspect(vspac: float, hspac: float) -> float:
    """Aspect ratio for a viewer pane, in pyqtgraph's convention.

    pyqtgraph defines the locked aspect as (screen px per x unit) / (screen px
    per y unit). To draw square millimetres we need

        px_per_y / px_per_x == vspac / hspac      ->      aspect = hspac / vspac

    Getting this the wrong way round silently collapses an anisotropic pane into
    a thin line (a 24-slice 12 mm scan rendered 549x7 instead of 549x395), so it
    is pinned by a regression test.
    """
    try:
        v = float(vspac); h = float(hspac)
    except (TypeError, ValueError):
        return 1.0
    if not (np.isfinite(v) and np.isfinite(h)) or v <= 0 or h <= 0:
        return 1.0
    return float(np.clip(h / v, 0.005, 200.0))
