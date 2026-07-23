"""Volume measurement.

Single-pass, vectorised replacement for the original per-object double loop
(which computed ``img[seg == i]`` twice for every label). Returns physical
volume in mm^3 and mL plus mean intensity per label.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from ..config import MM3_PER_ML
from .segmentation import Segmentation
from .volume import ImageVolume


@dataclass
class LabelVolume:
    id: int
    name: str
    voxels: int
    mm3: float
    ml: float
    mean_intensity: Optional[float]


def compute_volumes(seg: Segmentation, image: ImageVolume | None) -> List[LabelVolume]:
    flat = seg.data.ravel()
    max_id = int(flat.max()) if flat.size else 0
    counts = np.bincount(flat, minlength=max_id + 1)

    mean_by_id = None
    if image is not None:
        img_flat = image.data.ravel().astype(np.float64, copy=False)
        sums = np.bincount(flat, weights=img_flat, minlength=max_id + 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean_by_id = np.divide(
                sums, counts, out=np.full_like(sums, np.nan), where=counts > 0
            )

    vox_mm3 = image.voxel_volume_mm3 if image is not None else 1.0

    out: List[LabelVolume] = []
    for lab in seg.labels:
        n = int(counts[lab.id]) if lab.id < len(counts) else 0
        mm3 = n * vox_mm3
        mean = None
        if mean_by_id is not None and lab.id < len(mean_by_id):
            m = mean_by_id[lab.id]
            mean = None if np.isnan(m) else float(m)
        out.append(
            LabelVolume(
                id=lab.id,
                name=lab.name,
                voxels=n,
                mm3=float(mm3),
                ml=float(mm3 / MM3_PER_ML),
                mean_intensity=mean,
            )
        )
    return out


def total_volume(volumes: List[LabelVolume]) -> "LabelVolume":
    vox = sum(v.voxels for v in volumes)
    mm3 = sum(v.mm3 for v in volumes)
    return LabelVolume(-1, "Total", vox, mm3, mm3 / MM3_PER_ML, None)
