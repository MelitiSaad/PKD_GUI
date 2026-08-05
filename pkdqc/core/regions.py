"""Qt-independent Region Review indexing and state.

Region Review is layered over ordinary integer label maps.  It never renumbers
or recolors labels: connected components are transient review items computed
inside each numeric label for the current document revision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

from .. import config
from .commands import EditCommand
from .geometry import ImageGeometry
from .labels import LabelTable
from .segmentation import Segmentation

DEFAULT_CONNECTIVITY = 26
SMALL_VOLUME_MM3 = 10.0
REVIEW_SCHEMA_VERSION = 1
OVERLAP_THRESHOLD = 0.85


class GroupingMode(str, Enum):
    CONNECTED = "connected"
    LABELS = "labels"
    LABELS_WITH_COMPONENTS = "labels_components"


class ReviewStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    CHANGED = "changed"


class SortMode(str, Enum):
    LARGEST = "largest_volume"
    SMALLEST = "smallest_volume"
    SUPERIOR_TO_INFERIOR = "superior_to_inferior"
    LEFT_TO_RIGHT = "left_to_right"
    FLAGGED_FIRST = "flagged_first"
    UNREVIEWED_FIRST = "unreviewed_first"
    NUMERIC_LABEL = "numeric_label"
    LABEL_NAME = "label_name"


class FilterMode(str, Enum):
    ALL = "all"
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"
    CHANGED = "changed"
    FLAGGED = "flagged"
    SELECTED_LABELS = "selected_labels"


@dataclass(frozen=True)
class RegionFingerprint:
    label_id: int
    bbox: Tuple[Tuple[int, int, int], Tuple[int, int, int]]
    centroid_q: Tuple[int, int, int]
    voxel_count: int
    voxel_checksum: str

    def key(self) -> str:
        return f"{self.label_id}:{self.bbox}:{self.centroid_q}:{self.voxel_count}:{self.voxel_checksum}"


@dataclass(frozen=True)
class RegionRecord:
    transient_id: int
    component_id: int
    label_id: int
    label_name: str
    color: Tuple[int, int, int]
    voxel_count: int
    volume_mm3: float
    volume_ml: float
    bbox: Tuple[Tuple[int, int, int], Tuple[int, int, int]]
    world_bbox: Tuple[Tuple[float, float, float], Tuple[float, float, float]]
    centroid_voxel: Tuple[float, float, float]
    centroid_world: Tuple[float, float, float]
    representative_voxel: Tuple[int, int, int]
    slice_range: Tuple[int, int]
    largest_axial_slice: int
    largest_axial_area: int
    touches_boundary: bool
    one_slice: bool
    review_state: str
    flags: Tuple[str, ...]
    fingerprint: RegionFingerprint
    flat_indices: np.ndarray = field(repr=False, compare=False)


@dataclass(frozen=True)
class LabelRegionSummary:
    label_id: int
    label_name: str
    color: Tuple[int, int, int]
    voxel_count: int
    volume_mm3: float
    volume_ml: float
    component_count: int
    bbox: Tuple[Tuple[int, int, int], Tuple[int, int, int]]
    included: bool
    reviewed_count: int = 0
    unreviewed_count: int = 0
    changed_count: int = 0


@dataclass(frozen=True)
class RegionIndex:
    document_id: str
    revision: int
    connectivity: int
    shape: Tuple[int, int, int]
    voxel_volume_mm3: float
    records: Tuple[RegionRecord, ...]
    labels: Mapping[int, LabelRegionSummary]
    included_labels: frozenset[int]

    @property
    def total_voxel_count(self) -> int:
        return int(sum(s.voxel_count for lid, s in self.labels.items() if lid in self.included_labels))

    @property
    def total_volume_mm3(self) -> float:
        return float(sum(s.volume_mm3 for lid, s in self.labels.items() if lid in self.included_labels))

    @property
    def total_volume_ml(self) -> float:
        return self.total_volume_mm3 / config.MM3_PER_ML

    def items(self, mode: GroupingMode | str = GroupingMode.CONNECTED) -> Tuple[object, ...]:
        mode = GroupingMode(mode)
        if mode == GroupingMode.CONNECTED:
            return tuple(r for r in self.records if r.label_id in self.included_labels)
        if mode == GroupingMode.LABELS:
            return tuple(self.labels[lid] for lid in sorted(self.included_labels) if lid in self.labels)
        out: list[object] = []
        for lid in sorted(self.included_labels):
            if lid in self.labels:
                out.append(self.labels[lid])
                out.extend(r for r in self.records if r.label_id == lid)
        return tuple(out)

    def sorted_records(self, sort: SortMode | str = SortMode.LARGEST) -> Tuple[RegionRecord, ...]:
        records = [r for r in self.records if r.label_id in self.included_labels]
        sort = SortMode(sort)
        if sort == SortMode.LARGEST:
            key = lambda r: (-r.volume_mm3, r.label_id, r.transient_id)
        elif sort == SortMode.SMALLEST:
            key = lambda r: (r.volume_mm3, r.label_id, r.transient_id)
        elif sort == SortMode.SUPERIOR_TO_INFERIOR:
            key = lambda r: (-r.centroid_world[2], r.label_id, r.transient_id)
        elif sort == SortMode.LEFT_TO_RIGHT:
            key = lambda r: (r.centroid_world[0], r.label_id, r.transient_id)
        elif sort == SortMode.FLAGGED_FIRST:
            key = lambda r: (not bool(r.flags), -r.volume_mm3, r.label_id)
        elif sort == SortMode.UNREVIEWED_FIRST:
            key = lambda r: (r.review_state == ReviewStatus.REVIEWED, r.label_id, r.transient_id)
        elif sort == SortMode.NUMERIC_LABEL:
            key = lambda r: (r.label_id, r.transient_id)
        else:
            key = lambda r: (r.label_name.lower(), r.label_id, r.transient_id)
        return tuple(sorted(records, key=key))

    def filtered_records(self, filter_mode: FilterMode | str, selected_labels: Optional[Iterable[int]] = None) -> Tuple[RegionRecord, ...]:
        mode = FilterMode(filter_mode)
        records = [r for r in self.records if r.label_id in self.included_labels]
        if mode == FilterMode.UNREVIEWED:
            records = [r for r in records if r.review_state == ReviewStatus.UNREVIEWED]
        elif mode == FilterMode.REVIEWED:
            records = [r for r in records if r.review_state == ReviewStatus.REVIEWED]
        elif mode == FilterMode.CHANGED:
            records = [r for r in records if r.review_state == ReviewStatus.CHANGED]
        elif mode == FilterMode.FLAGGED:
            records = [r for r in records if r.flags]
        elif mode == FilterMode.SELECTED_LABELS:
            selected = {int(v) for v in (selected_labels or ())}
            records = [r for r in records if r.label_id in selected]
        return tuple(records)


@dataclass
class RegionReviewState:
    grouping_mode: str = GroupingMode.CONNECTED.value
    connectivity: int = DEFAULT_CONNECTIVITY
    included_labels: set[int] = field(default_factory=set)
    sort_mode: str = SortMode.LARGEST.value
    filter_mode: str = FilterMode.ALL.value
    current_position: int = 0
    review_by_fingerprint: Dict[str, str] = field(default_factory=dict)
    isolated_fingerprint: Optional[str] = None
    stale: bool = False

    def queue(self, index: RegionIndex) -> Tuple[RegionRecord, ...]:
        return index.sorted_records(self.sort_mode)

    def current(self, index: RegionIndex) -> Optional[RegionRecord]:
        q = self.queue(index)
        if not q:
            return None
        self.current_position = max(0, min(self.current_position, len(q) - 1))
        return q[self.current_position]

    def next(self, index: RegionIndex) -> Optional[RegionRecord]:
        q = self.queue(index)
        if q:
            self.current_position = min(len(q) - 1, self.current_position + 1)
        return self.current(index)

    def previous(self, index: RegionIndex) -> Optional[RegionRecord]:
        if self.queue(index):
            self.current_position = max(0, self.current_position - 1)
        return self.current(index)

    def mark_reviewed_and_advance(self, index: RegionIndex) -> Optional[RegionRecord]:
        cur = self.current(index)
        if cur:
            self.review_by_fingerprint[cur.fingerprint.key()] = ReviewStatus.REVIEWED.value
            self.current_position += 1
        return self.current(index)

    def mark_unreviewed(self, index: RegionIndex) -> None:
        cur = self.current(index)
        if cur:
            self.review_by_fingerprint[cur.fingerprint.key()] = ReviewStatus.UNREVIEWED.value

    def toggle_isolation(self, index: RegionIndex) -> None:
        cur = self.current(index)
        key = cur.fingerprint.key() if cur else None
        self.isolated_fingerprint = None if self.isolated_fingerprint == key else key


def build_region_index(segmentation: np.ndarray, labels: LabelTable, geometry: ImageGeometry, *,
                       document_id: str = "", revision: int = 0, connectivity: int = DEFAULT_CONNECTIVITY,
                       included_labels: Optional[Iterable[int]] = None,
                       review_state: Optional[Mapping[str, str]] = None) -> RegionIndex:
    data = np.asarray(segmentation)
    if tuple(data.shape) != tuple(geometry.shape):
        raise ValueError("segmentation shape does not match image geometry")
    structure = _structure(connectivity)
    present = [int(v) for v in np.unique(data) if int(v) != 0]
    included = frozenset(int(v) for v in (included_labels if included_labels is not None else present))
    review_state = review_state or {}
    records: list[RegionRecord] = []
    summaries: dict[int, LabelRegionSummary] = {}
    transient = 1
    for lid in present:
        lab = labels.labels.get(lid)
        name = lab.name if lab else f"Object {lid}"
        color = tuple(lab.color) if lab else (255, 255, 255)
        mask = data == lid
        comp, ncomp = ndimage.label(mask, structure=structure)
        label_records = []
        for comp_id in range(1, int(ncomp) + 1):
            flat = np.flatnonzero(comp.ravel() == comp_id).astype(np.int64, copy=False)
            if flat.size == 0:
                continue
            record = _record_for_component(transient, comp_id, lid, name, color, flat.copy(), data.shape, geometry, review_state)
            record.flat_indices.setflags(write=False)
            records.append(record); label_records.append(record); transient += 1
        if label_records:
            mins = np.min([r.bbox[0] for r in label_records], axis=0).astype(int)
            maxs = np.max([r.bbox[1] for r in label_records], axis=0).astype(int)
            vox = int(sum(r.voxel_count for r in label_records))
            rev = sum(1 for r in label_records if r.review_state == ReviewStatus.REVIEWED)
            chg = sum(1 for r in label_records if r.review_state == ReviewStatus.CHANGED)
            summaries[lid] = LabelRegionSummary(
                lid, name, color, vox, vox * geometry.voxel_volume_mm3,
                vox * geometry.voxel_volume_mm3 / config.MM3_PER_ML, len(label_records),
                (tuple(mins.tolist()), tuple(maxs.tolist())), lid in included,
                reviewed_count=rev, changed_count=chg,
                unreviewed_count=len(label_records) - rev - chg,
            )
    return RegionIndex(str(document_id), int(revision), int(connectivity), tuple(data.shape),
                       float(geometry.voxel_volume_mm3), tuple(records), summaries, included)


def delete_region_checked(seg: Segmentation, index: RegionIndex, record: RegionRecord) -> EditCommand:
    if int(seg.revision) != int(index.revision):
        raise ValueError("Region index is stale; rebuild before deleting this component")
    flat = record.flat_indices
    data = seg.data.reshape(-1)
    current = data[flat]
    expected = np.full(flat.shape, record.label_id, dtype=data.dtype)
    if not np.array_equal(current, expected):
        raise ValueError("Region voxels changed; rebuild before deleting this component")
    return EditCommand(flat.copy(), current.copy(), np.zeros(flat.shape, dtype=data.dtype), _slices_for_flat(flat, seg.data.shape), "delete connected region")


def delete_label_checked(seg: Segmentation, label_id: int) -> EditCommand:
    flat = np.flatnonzero(seg.data.ravel() == int(label_id)).astype(np.int64)
    data = seg.data.reshape(-1)
    return EditCommand(flat, data[flat].copy(), np.zeros(flat.shape, dtype=data.dtype), _slices_for_flat(flat, seg.data.shape), "delete entire label")


def remap_review_state(old: RegionIndex, new: RegionIndex, state: Mapping[str, str], *, threshold: float = OVERLAP_THRESHOLD) -> Dict[str, str]:
    remapped: dict[str, str] = {}
    exact = {r.fingerprint.key(): r for r in new.records}
    for old_rec in old.records:
        old_key = old_rec.fingerprint.key()
        status = state.get(old_key)
        if not status:
            continue
        if old_key in exact:
            remapped[old_key] = status
            continue
        overlaps = []
        old_set = set(int(v) for v in old_rec.flat_indices.tolist())
        for new_rec in new.records:
            if new_rec.label_id != old_rec.label_id:
                continue
            nset = set(int(v) for v in new_rec.flat_indices.tolist())
            inter = len(old_set.intersection(nset))
            if inter:
                overlaps.append((inter / max(len(old_set), len(nset)), new_rec))
        good = [x for x in overlaps if x[0] >= threshold]
        if len(good) == 1:
            remapped[good[0][1].fingerprint.key()] = ReviewStatus.CHANGED.value
    return remapped


def save_review_progress(identity: Mapping[str, object], state: RegionReviewState, *, path: Optional[Path] = None) -> Path:
    ident = _identity_hash(identity)
    out = Path(path) if path else review_progress_dir() / f"{ident}.json"
    payload = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "identity_hash": ident,
        "grouping_mode": state.grouping_mode,
        "connectivity": state.connectivity,
        "included_labels": sorted(int(v) for v in state.included_labels),
        "sort_mode": state.sort_mode,
        "filter_mode": state.filter_mode,
        "current_position": state.current_position,
        "review_by_fingerprint": dict(state.review_by_fingerprint),
        "overlap_threshold": OVERLAP_THRESHOLD,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, sort_keys=True)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, out)
    return out


def load_review_progress(identity: Mapping[str, object], *, path: Optional[Path] = None) -> Optional[RegionReviewState]:
    ident = _identity_hash(identity)
    src = Path(path) if path else review_progress_dir() / f"{ident}.json"
    if not src.exists():
        return None
    payload = json.loads(src.read_text(encoding="utf-8"))
    if int(payload.get("schema_version", -1)) != REVIEW_SCHEMA_VERSION:
        raise ValueError("unsupported Region Review progress schema")
    if payload.get("identity_hash") != ident:
        raise ValueError("Region Review progress identity does not match this segmentation")
    return RegionReviewState(
        grouping_mode=payload.get("grouping_mode", GroupingMode.CONNECTED.value),
        connectivity=int(payload.get("connectivity", DEFAULT_CONNECTIVITY)),
        included_labels={int(v) for v in payload.get("included_labels", [])},
        sort_mode=payload.get("sort_mode", SortMode.LARGEST.value),
        filter_mode=payload.get("filter_mode", FilterMode.ALL.value),
        current_position=int(payload.get("current_position", 0)),
        review_by_fingerprint={str(k): str(v) for k, v in payload.get("review_by_fingerprint", {}).items()},
    )


def clear_review_progress(identity: Mapping[str, object]) -> None:
    path = review_progress_dir() / f"{_identity_hash(identity)}.json"
    if path.exists():
        path.unlink()


def review_progress_dir() -> Path:
    d = config.app_data_dir() / "region_review"
    d.mkdir(parents=True, exist_ok=True)
    return d


def progress_identity(*, segmentation_path: Optional[str], shape: Sequence[int], affine: np.ndarray, dtype: str, labels: Iterable[int]) -> dict:
    # PHI-safe: store technical hashes and numeric geometry only, not DICOM demographics or descriptive paths.
    path_hash = hashlib.sha256(str(segmentation_path or "unsaved").encode("utf-8", "surrogatepass")).hexdigest()
    return {
        "segmentation_path_hash": path_hash,
        "shape": [int(v) for v in shape],
        "affine_sha256": hashlib.sha256(np.asarray(affine, dtype=np.float64).tobytes()).hexdigest(),
        "dtype": str(dtype),
        "labels": [int(v) for v in sorted(labels)],
    }


def invalidate_after_edit(index: RegionIndex, changed_bbox=None) -> str:
    if changed_bbox is None:
        return "full rebuild required: edit bounds unavailable"
    return "full rebuild required: local split/merge correctness is not yet provable"


def _record_for_component(transient, comp_id, lid, name, color, flat, shape, geometry, review_state):
    coords = np.column_stack(np.unravel_index(flat, shape)).astype(np.int64)
    mins = coords.min(axis=0); maxs = coords.max(axis=0) + 1
    centroid = coords.mean(axis=0)
    world = geometry.voxel_to_world(centroid)
    corners = np.array(np.meshgrid(*[[mins[a], maxs[a] - 1] for a in range(3)], indexing="ij")).reshape(3, -1).T
    wcorners = np.array([geometry.voxel_to_world(c) for c in corners])
    zvals, zcounts = np.unique(coords[:, 2], return_counts=True)
    best_z = int(zvals[int(np.argmax(zcounts))])
    on_best = coords[coords[:, 2] == best_z]
    rep = on_best[np.argmin(np.linalg.norm(on_best[:, :2] - centroid[:2], axis=1))].astype(int)
    checksum = hashlib.sha256(flat.astype(np.int64, copy=False).tobytes()).hexdigest()
    fp = RegionFingerprint(int(lid), (tuple(mins.tolist()), tuple(maxs.tolist())), tuple(np.round(centroid * 1000).astype(int).tolist()), int(flat.size), checksum)
    flags = []
    volume = int(flat.size) * geometry.voxel_volume_mm3
    touches = bool(np.any(mins == 0) or np.any(maxs == np.asarray(shape)))
    one_slice = bool(maxs[2] - mins[2] == 1)
    if volume < SMALL_VOLUME_MM3:
        flags.append("small-volume")
    if one_slice:
        flags.append("one-slice")
    if touches:
        flags.append("touches-boundary")
    state = review_state.get(fp.key(), ReviewStatus.UNREVIEWED.value)
    if state == ReviewStatus.CHANGED.value and "changed-after-review" not in flags:
        flags.append("changed-after-review")
    return RegionRecord(
        int(transient), int(comp_id), int(lid), str(name), tuple(int(c) for c in color), int(flat.size),
        float(volume), float(volume / config.MM3_PER_ML), (tuple(mins.tolist()), tuple(maxs.tolist())),
        (tuple(wcorners.min(axis=0).tolist()), tuple(wcorners.max(axis=0).tolist())),
        tuple(float(v) for v in centroid.tolist()), tuple(float(v) for v in world.tolist()),
        tuple(int(v) for v in rep.tolist()), (int(mins[2]), int(maxs[2] - 1)), best_z, int(zcounts.max()),
        touches, one_slice, str(state), tuple(flags), fp, flat,
    )


def _structure(connectivity: int) -> np.ndarray:
    if connectivity not in (6, 18, 26):
        raise ValueError("connectivity must be 6, 18, or 26")
    s = np.zeros((3, 3, 3), dtype=bool)
    for i in range(3):
        for j in range(3):
            for k in range(3):
                d = abs(i - 1) + abs(j - 1) + abs(k - 1)
                if connectivity == 26 or d <= (1 if connectivity == 6 else 2):
                    s[i, j, k] = True
    return s


def _slices_for_flat(flat: np.ndarray, shape) -> Tuple[int, ...]:
    if flat.size == 0:
        return ()
    return tuple(int(v) for v in np.unique(np.unravel_index(flat, shape)[2]).tolist())


def _identity_hash(identity: Mapping[str, object]) -> str:
    safe = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(safe.encode("utf-8")).hexdigest()
