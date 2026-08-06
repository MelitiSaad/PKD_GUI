"""Conservative seed-based intensity-connected fill.

Preview calculation is pure: neither the image nor segmentation snapshot is
mutated.  Numeric labels remain local to the source segmentation layer.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .commands import EditCommand
from .background import CancelledTask
from .label_policy import LabelProtectionPolicy
from .planes import PLANES


@dataclass(frozen=True)
class IntelligentFillRequest:
    image: np.ndarray
    segmentation: np.ndarray
    seed: tuple[int, int, int]
    target_label: int
    lower: float
    upper: float
    scope: str = "axial"
    connectivity: int = 4
    policy: LabelProtectionPolicy = LabelProtectionPolicy()
    case_id: str = ""
    layer_id: str = ""
    source_revision: int = 0


@dataclass(frozen=True)
class IntelligentFillResult:
    status: str
    flat_indices: np.ndarray
    changed_voxels: int
    already_active_voxels: int
    protected_voxels: int
    bounding_box: Optional[tuple[tuple[int, int, int], tuple[int, int, int]]]
    seed_intensity: float
    bounds: tuple[float, float]
    scope: str
    connectivity: int
    case_id: str
    layer_id: str
    source_revision: int
    target_label: int
    message: str = ""

    @property
    def applicable(self) -> bool:
        return self.status == "success" and self.changed_voxels > 0


def _empty(req, status: str, seed_intensity=np.nan, message="") -> IntelligentFillResult:
    return IntelligentFillResult(status, np.empty(0, np.int64), 0, 0, 0, None,
        float(seed_intensity), (float(req.lower), float(req.upper)), req.scope,
        int(req.connectivity), req.case_id, req.layer_id, int(req.source_revision),
        int(req.target_label), message)


def _offsets(scope: str, connectivity: int):
    if scope == "3d":
        if connectivity not in (6, 18, 26):
            raise ValueError("3D connectivity must be 6, 18, or 26")
        offsets = []
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for dk in (-1, 0, 1):
                    distance = abs(di) + abs(dj) + abs(dk)
                    if distance and distance <= {6: 1, 18: 2, 26: 3}[connectivity]:
                        offsets.append((di, dj, dk))
        return offsets, None
    if scope not in PLANES:
        raise ValueError("Scope must be axial, coronal, sagittal, or 3d")
    if connectivity not in (4, 8):
        raise ValueError("2D connectivity must be 4 or 8")
    depth = PLANES[scope].depth_axis
    axes = [axis for axis in range(3) if axis != depth]
    offsets = []
    for da in (-1, 0, 1):
        for db in (-1, 0, 1):
            if not (da or db) or (connectivity == 4 and abs(da) + abs(db) != 1):
                continue
            offset = [0, 0, 0]; offset[axes[0]] = da; offset[axes[1]] = db
            offsets.append(tuple(offset))
    return offsets, depth


def compute_preview(req: IntelligentFillRequest, cancellation_token=None) -> IntelligentFillResult:
    image = np.asarray(req.image)
    segmentation = np.asarray(req.segmentation)
    if image.ndim != 3 or segmentation.ndim != 3 or image.shape != segmentation.shape:
        raise ValueError("Image and segmentation must be matching 3D arrays")
    if not isinstance(req.target_label, (int, np.integer)) or not 0 < int(req.target_label) <= 65535:
        raise ValueError("Target label must be an integer from 1 through 65535")
    if not np.isfinite(req.lower) or not np.isfinite(req.upper) or req.lower > req.upper:
        raise ValueError("Intensity bounds must be finite and lower must not exceed upper")
    offsets, depth_axis = _offsets(req.scope, int(req.connectivity))
    if len(req.seed) != 3 or any(not isinstance(v, (int, np.integer)) for v in req.seed):
        raise ValueError("Seed must contain three integer voxel coordinates")
    seed = tuple(int(v) for v in req.seed)
    if any(v < 0 or v >= image.shape[axis] for axis, v in enumerate(seed)):
        raise ValueError("Seed lies outside the image")
    intensity = float(image[seed])
    if not np.isfinite(intensity):
        return _empty(req, "rejected", intensity, "Seed intensity is not finite")
    if intensity < req.lower or intensity > req.upper:
        return _empty(req, "rejected", intensity, "Seed is outside the intensity range")

    writable_seed = bool(req.policy.writable(np.asarray([segmentation[seed]]), int(req.target_label))[0])
    if not writable_seed:
        return _empty(req, "rejected", intensity, "Seed label is protected")

    visited = np.zeros(image.shape, dtype=bool)
    queued = deque([seed]); visited[seed] = True
    region = []; conflicts = 0; processed = 0
    shape = image.shape
    while queued:
        if cancellation_token is not None and processed % 256 == 0:
            if getattr(cancellation_token, "cancelled", False):
                return _empty(req, "cancelled", intensity, "Preview cancelled")
            raiser = getattr(cancellation_token, "raise_if_cancelled", None)
            if raiser is not None:
                try: raiser()
                except CancelledTask: return _empty(req, "cancelled", intensity, "Preview cancelled")
        point = queued.popleft(); processed += 1; region.append(point)
        for offset in offsets:
            nxt = tuple(point[a] + offset[a] for a in range(3))
            if any(nxt[a] < 0 or nxt[a] >= shape[a] for a in range(3)) or visited[nxt]:
                continue
            visited[nxt] = True
            value = image[nxt]
            if not np.isfinite(value) or value < req.lower or value > req.upper:
                continue
            if depth_axis is not None and nxt[depth_axis] != seed[depth_axis]:
                continue
            writable = bool(req.policy.writable(np.asarray([segmentation[nxt]]), int(req.target_label))[0])
            if not writable:
                conflicts += 1
                continue
            queued.append(nxt)

    coords = np.asarray(region, dtype=np.intp)
    values = segmentation[tuple(coords.T)]
    already = int(np.count_nonzero(values == np.uint16(req.target_label)))
    changed_coords = coords[values != np.uint16(req.target_label)]
    if not changed_coords.size:
        result = _empty(req, "empty", intensity, "Connected region already has the active label")
        return IntelligentFillResult(**{**result.__dict__, "already_active_voxels": already,
                                       "protected_voxels": conflicts})
    flat = np.ravel_multi_index(tuple(changed_coords.T), shape).astype(np.int64)
    lo = tuple(int(v) for v in coords.min(axis=0)); hi = tuple(int(v) for v in coords.max(axis=0))
    return IntelligentFillResult("success", flat, int(flat.size), already, conflicts,
        (lo, hi), intensity, (float(req.lower), float(req.upper)), req.scope,
        int(req.connectivity), req.case_id, req.layer_id, int(req.source_revision),
        int(req.target_label))


def command_for_preview(segmentation, result: IntelligentFillResult,
                        *, case_id: str, layer_id: str) -> Optional[EditCommand]:
    """Build one exact diff, rejecting stale or foreign preview results."""
    if result.status != "success" or not result.flat_indices.size:
        return None
    if result.case_id != case_id or result.layer_id != layer_id:
        raise ValueError("Intelligent Fill preview belongs to another case or layer")
    if segmentation.revision != result.source_revision:
        raise ValueError("Intelligent Fill preview is stale")
    flat = np.asarray(result.flat_indices, dtype=np.int64)
    old = segmentation.data.reshape(-1)[flat].copy()
    new = np.full(flat.shape, np.uint16(result.target_label), dtype=np.uint16)
    changed = old != new
    if not changed.any():
        return None
    slices = np.unique(flat[changed] % segmentation.data.shape[2]).tolist()
    return EditCommand(flat[changed], old[changed], new[changed], slices, "Intelligent Fill")
