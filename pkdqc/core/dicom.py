"""Trustworthy DICOM image-series discovery and loading.

The implementation follows the DICOM image-plane model: Image Orientation
Patient provides row and column direction cosines, Image Position Patient gives
the first voxel position in the patient LPS coordinate system, and Pixel Spacing
provides row/column spacing.  Volumes are converted to the application's RAS+
geometry contract before display/editing.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .geometry import ImageGeometry, ORTHO_TOL
from .volume import ImageVolume

LPS_TO_RAS = np.diag([-1.0, -1.0, 1.0, 1.0])
SUPPORTED_MODALITIES = {"CT", "MR", "PT", "NM"}
SEGMENTATION_SOP = "1.2.840.10008.5.1.4.1.1.66.4"
LOCALIZER_TERMS = ("localizer", "scout", "survey")
ENHANCED_SOPS = {
    "1.2.840.10008.5.1.4.1.1.2.1",   # Enhanced CT Image Storage
    "1.2.840.10008.5.1.4.1.1.4.1",   # Enhanced MR Image Storage
}


class DicomError(Exception):
    """A DICOM input cannot be represented as one safe scalar 3D volume."""


@dataclass(frozen=True)
class DicomSeriesCandidate:
    key: str
    study_uid: str
    series_uid: str
    frame_of_reference_uid: str
    sop_class_uid: str
    modality: str
    series_number: str
    series_description: str
    instances_or_frames: int
    rows: int
    columns: int
    pixel_spacing: tuple[float, float] | None
    orientation_summary: str
    kind: str
    files: tuple[str, ...]
    validation_errors: tuple[str, ...] = ()
    validation_warnings: tuple[str, ...] = ()
    is_localizer: bool = False
    is_unsupported: bool = False

    @property
    def valid(self) -> bool:
        return not self.validation_errors and not self.is_localizer and not self.is_unsupported

    @property
    def display_description(self) -> str:
        spacing = "?" if self.pixel_spacing is None else "×".join(f"{v:g}" for v in self.pixel_spacing)
        status = "valid" if self.valid else "; ".join(self.validation_errors or ("unsupported",))
        return (f"Series {self.series_number or '?'} · {self.modality or '?'} · "
                f"{self.instances_or_frames} frames · {self.rows}×{self.columns} · "
                f"spacing {spacing} · {self.orientation_summary} · {status}")


def scan_root(path: str) -> Path:
    p = Path(path)
    return p if p.is_dir() else p.parent


def _dicom_files(path: str) -> list[Path]:
    root = scan_root(path)
    if not root.exists():
        raise DicomError("DICOM selection does not exist")
    if root.is_file():
        return [root]
    return [p for p in root.iterdir() if p.is_file()]


def _read_header(path: Path):
    import pydicom
    from pydicom.errors import InvalidDicomError
    try:
        return pydicom.dcmread(str(path), stop_before_pixels=True, force=False)
    except InvalidDicomError:
        return None
    except Exception:
        return None


def discover_series(path: str) -> list[DicomSeriesCandidate]:
    groups: dict[tuple[str, str, str, str, str], list[tuple[Path, object]]] = {}
    for f in _dicom_files(path):
        ds = _read_header(f)
        if ds is None or not hasattr(ds, "SOPClassUID"):
            continue
        study = str(getattr(ds, "StudyInstanceUID", ""))
        series = str(getattr(ds, "SeriesInstanceUID", ""))
        frame = str(getattr(ds, "FrameOfReferenceUID", ""))
        sop = str(getattr(ds, "SOPClassUID", ""))
        modality = str(getattr(ds, "Modality", ""))
        groups.setdefault((study, series, frame, sop, modality), []).append((f, ds))
    out = [_candidate_from_group(key, items) for key, items in groups.items()]
    out.sort(key=lambda c: (c.study_uid, c.series_number, c.series_uid, c.key))
    return out


def _candidate_from_group(key, items) -> DicomSeriesCandidate:
    study, series, frame, sop, modality = key
    first = items[0][1]
    errors: list[str] = []
    warnings: list[str] = []
    desc = _safe_text(getattr(first, "SeriesDescription", ""))
    localizer = _is_localizer(first, desc)
    unsupported = modality not in SUPPORTED_MODALITIES or str(sop) == SEGMENTATION_SOP
    rows = int(getattr(first, "Rows", 0) or 0); cols = int(getattr(first, "Columns", 0) or 0)
    enhanced = str(sop) in ENHANCED_SOPS
    spacing = None if enhanced else _pixel_spacing(first, errors)
    orientation = _orientation(first, errors, allow_missing=enhanced)
    frames = int(getattr(first, "NumberOfFrames", 1) or 1) if str(sop) in ENHANCED_SOPS else len(items)
    if str(sop) == SEGMENTATION_SOP:
        errors.append("DICOM SEG is not currently supported")
    if unsupported and str(sop) != SEGMENTATION_SOP:
        errors.append("unsupported DICOM object for scalar image loading")
    if localizer:
        warnings.append("localizer/scout series is not auto-selected")
    if rows <= 0 or cols <= 0:
        errors.append("missing matrix size")
    if frames < 2:
        errors.append("series is not a 3D volume")
    orient_summary = "?" if orientation is None else _orientation_summary(orientation)
    file_names = tuple(str(p) for p, _ in sorted(items, key=lambda item: str(item[0])))
    digest = hashlib.sha256(json.dumps([study, series, frame, sop, file_names], sort_keys=True).encode()).hexdigest()[:16]
    return DicomSeriesCandidate(digest, study, series, frame, sop, modality,
                                _safe_text(getattr(first, "SeriesNumber", "")), desc,
                                frames, rows, cols, spacing, orient_summary,
                                "enhanced" if enhanced else "classic",
                                file_names, tuple(errors), tuple(warnings), localizer, unsupported)


def _safe_text(value) -> str:
    text = str(value or "")
    return " ".join(text.split())[:80]


def _is_localizer(ds, desc: str) -> bool:
    image_type = " ".join(str(v).lower() for v in getattr(ds, "ImageType", []) or [])
    text = f"{desc} {image_type}".lower()
    return any(term in text for term in LOCALIZER_TERMS)


def _pixel_spacing(ds, errors: list[str]) -> tuple[float, float] | None:
    ps = getattr(ds, "PixelSpacing", None)
    try:
        out = (float(ps[0]), float(ps[1]))
        if out[0] <= 0 or out[1] <= 0:
            raise ValueError
        return out
    except Exception:
        errors.append("missing or invalid PixelSpacing")
        return None


def _orientation(ds, errors: list[str], *, allow_missing=False) -> tuple[np.ndarray, np.ndarray] | None:
    iop = getattr(ds, "ImageOrientationPatient", None)
    try:
        row = np.asarray([float(v) for v in iop[:3]], dtype=float)
        col = np.asarray([float(v) for v in iop[3:]], dtype=float)
        _validate_dirs(row, col)
        return row, col
    except Exception:
        if not allow_missing:
            errors.append("missing or invalid ImageOrientationPatient")
        return None


def _validate_dirs(row: np.ndarray, col: np.ndarray) -> None:
    if row.shape != (3,) or col.shape != (3,) or not np.all(np.isfinite(row)) or not np.all(np.isfinite(col)):
        raise DicomError("invalid direction cosines")
    if not np.isclose(np.linalg.norm(row), 1.0, atol=1e-4) or not np.isclose(np.linalg.norm(col), 1.0, atol=1e-4):
        raise DicomError("direction cosines are not unit length")
    if abs(float(np.dot(row, col))) > ORTHO_TOL:
        raise DicomError("unsupported gantry tilt/shear or non-orthogonal row/column directions")


def _orientation_summary(orientation: tuple[np.ndarray, np.ndarray]) -> str:
    row, col = orientation
    return f"row {_lps_code(row)} col {_lps_code(col)}"


def _lps_code(vec: np.ndarray) -> str:
    labels_pos = ("L", "P", "S"); labels_neg = ("R", "A", "I")
    idx = int(np.argmax(np.abs(vec)))
    return labels_pos[idx] if vec[idx] >= 0 else labels_neg[idx]


def choose_candidate(candidates: list[DicomSeriesCandidate], selector: Optional[Callable[[list[DicomSeriesCandidate]], Optional[DicomSeriesCandidate]]] = None) -> DicomSeriesCandidate:
    valid = [c for c in candidates if c.valid]
    if not valid:
        problems = sorted({e for c in candidates for e in c.validation_errors})
        raise DicomError("No valid DICOM image series found" + (": " + "; ".join(problems) if problems else ""))
    if len(valid) == 1:
        return valid[0]
    if selector is None:
        raise DicomError("Multiple valid DICOM series were found; select one series to load")
    selected = selector(valid)
    if selected is None:
        raise DicomError("DICOM series selection was cancelled")
    if selected.key not in {c.key for c in valid}:
        raise DicomError("Selected DICOM series is not valid")
    return selected


def load_series(path: str, *, selector: Optional[Callable[[list[DicomSeriesCandidate]], Optional[DicomSeriesCandidate]]] = None,
                series_uid: str | None = None, source_identity: dict | None = None) -> ImageVolume:
    candidates = discover_series(path)
    if series_uid is not None:
        matches = [c for c in candidates if c.series_uid == series_uid]
        if len(matches) != 1 or not matches[0].valid:
            raise DicomError("Requested DICOM series is missing or invalid")
        candidate = matches[0]
    elif source_identity is not None and source_identity.get("type") == "dicom-series":
        expected = source_identity.get("series_uid")
        matches = [c for c in candidates if c.series_uid == expected and c.study_uid == source_identity.get("study_uid")]
        if len(matches) != 1 or not matches[0].valid:
            raise DicomError("Recovery DICOM series is missing or ambiguous")
        candidate = matches[0]
    else:
        candidate = choose_candidate(candidates, selector)
    image = _load_enhanced(candidate) if candidate.kind == "enhanced" else _load_classic(candidate)
    identity = series_identity(candidate, image)
    if source_identity is not None and source_identity.get("identity_sha256") != identity.get("identity_sha256"):
        raise DicomError("DICOM source identity mismatch")
    image.source_identity = identity
    return image


def _read_full(path: str):
    import pydicom
    try:
        return pydicom.dcmread(path, force=False)
    except Exception as exc:
        raise DicomError("DICOM pixel data could not be read; a pixel decoder may be missing") from exc


def _load_classic(candidate: DicomSeriesCandidate) -> ImageVolume:
    datasets = [_read_full(f) for f in candidate.files]
    errors: list[str] = []
    rows = int(datasets[0].Rows); cols = int(datasets[0].Columns)
    spacing = _pixel_spacing(datasets[0], errors)
    orient = _orientation(datasets[0], errors)
    if spacing is None or orient is None:
        raise DicomError("; ".join(errors))
    row_dir, col_dir = orient
    normal = np.cross(row_dir, col_dir)
    positions = []
    arrays = []
    temporal = set()
    for ds in datasets:
        if int(ds.Rows) != rows or int(ds.Columns) != cols:
            raise DicomError("inconsistent matrix size in DICOM series")
        if str(getattr(ds, "FrameOfReferenceUID", "")) != candidate.frame_of_reference_uid:
            raise DicomError("inconsistent frame of reference in DICOM series")
        sp = _pixel_spacing(ds, [])
        if sp != spacing:
            raise DicomError("inconsistent PixelSpacing in DICOM series")
        o = _orientation(ds, [])
        if o is None or not np.allclose(o[0], row_dir, atol=1e-4) or not np.allclose(o[1], col_dir, atol=1e-4):
            raise DicomError("inconsistent ImageOrientationPatient in DICOM series")
        ipp = _position(ds)
        positions.append(float(np.dot(ipp, normal)))
        temporal.add(str(getattr(ds, "TemporalPositionIdentifier", "")))
        arrays.append(_scaled_pixels(ds))
    if len([x for x in temporal if x]) > 1:
        raise DicomError("mixed temporal positions are not supported")
    order = np.argsort(positions)
    sorted_pos = np.asarray(positions, dtype=float)[order]
    diffs = np.diff(sorted_pos)
    if np.any(np.isclose(diffs, 0.0, atol=1e-4)):
        raise DicomError("duplicate DICOM slice positions")
    if len(diffs) == 0:
        raise DicomError("series is not a 3D volume")
    dz = float(np.median(np.abs(diffs)))
    if not np.allclose(np.abs(diffs), dz, rtol=1e-3, atol=1e-3):
        raise DicomError("irregular or missing DICOM slice spacing")
    if len(diffs) >= 2 and np.max(np.abs(np.abs(diffs) - dz)) > max(1e-3, 0.25 * dz):
        raise DicomError("missing DICOM slice or spacing gap")
    volume = np.stack([arrays[i] for i in order], axis=-1)
    ipp0 = _position(datasets[int(order[0])])
    step_sign = 1.0 if diffs[0] > 0 else -1.0
    affine_lps = np.eye(4)
    affine_lps[:3, 0] = col_dir * spacing[0]   # row index advances down image rows
    affine_lps[:3, 1] = row_dir * spacing[1]   # column index advances across image columns
    affine_lps[:3, 2] = normal * dz * step_sign
    affine_lps[:3, 3] = ipp0
    return _canonical_image(volume, affine_lps, scan_root(candidate.files[0]), candidate)


def _position(ds) -> np.ndarray:
    ipp = getattr(ds, "ImagePositionPatient", None)
    try:
        out = np.asarray([float(v) for v in ipp], dtype=float)
        if out.shape != (3,) or not np.all(np.isfinite(out)):
            raise ValueError
        return out
    except Exception as exc:
        raise DicomError("missing or invalid ImagePositionPatient") from exc


def _scaled_pixels(ds) -> np.ndarray:
    photo = str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2"))
    samples = int(getattr(ds, "SamplesPerPixel", 1) or 1)
    if samples != 1 or not photo.startswith("MONOCHROME"):
        raise DicomError("unsupported color or vector DICOM pixel data")
    try:
        arr = ds.pixel_array.astype(np.float32)
    except Exception as exc:
        raise DicomError("DICOM pixel data could not be decoded; install an appropriate decoder") from exc
    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    return arr * slope + intercept


def _load_enhanced(candidate: DicomSeriesCandidate) -> ImageVolume:
    ds = _read_full(candidate.files[0])
    if int(getattr(ds, "SamplesPerPixel", 1) or 1) != 1:
        raise DicomError("unsupported enhanced multiframe pixel layout")
    shared = getattr(ds, "SharedFunctionalGroupsSequence", [])
    per = getattr(ds, "PerFrameFunctionalGroupsSequence", [])
    if not per:
        raise DicomError("enhanced multiframe is missing per-frame functional groups")
    n = int(getattr(ds, "NumberOfFrames", len(per)) or len(per))
    if len(per) != n:
        raise DicomError("unsupported multiframe dimensions")
    spacing = _fg_pixel_spacing(shared[0] if shared else None, per[0])
    row_dir, col_dir = _fg_orientation(shared[0] if shared else None, per[0])
    normal = np.cross(row_dir, col_dir)
    positions = np.asarray([float(np.dot(_fg_position(frame), normal)) for frame in per])
    diffs = np.diff(np.sort(positions))
    if len(diffs) == 0 or np.any(np.isclose(diffs, 0, atol=1e-4)):
        raise DicomError("duplicate or insufficient enhanced frame positions")
    dz = float(np.median(np.abs(diffs)))
    if not np.allclose(np.abs(diffs), dz, rtol=1e-3, atol=1e-3):
        raise DicomError("unsupported multiframe dimensions or irregular spacing")
    arr = _scaled_pixels(ds)
    if arr.ndim != 3 or arr.shape[0] != n:
        raise DicomError("unsupported enhanced multiframe pixel layout")
    order = np.argsort(positions)
    volume = np.transpose(arr[order, :, :], (1, 2, 0))
    ipp0 = _fg_position(per[int(order[0])])
    affine_lps = np.eye(4)
    affine_lps[:3, 0] = col_dir * spacing[0]
    affine_lps[:3, 1] = row_dir * spacing[1]
    affine_lps[:3, 2] = normal * dz
    affine_lps[:3, 3] = ipp0
    return _canonical_image(volume, affine_lps, scan_root(candidate.files[0]), candidate)


def _fg_item(item, name):
    if item is not None and hasattr(item, name):
        seq = getattr(item, name)
        if seq:
            return seq[0]
    return None


def _fg_pixel_spacing(shared, frame):
    obj = _fg_item(frame, "PixelMeasuresSequence") or _fg_item(shared, "PixelMeasuresSequence")
    if obj is None:
        raise DicomError("enhanced multiframe is missing Pixel Measures")
    ps = [float(v) for v in obj.PixelSpacing]
    if ps[0] <= 0 or ps[1] <= 0:
        raise DicomError("invalid enhanced PixelSpacing")
    return ps[0], ps[1]


def _fg_orientation(shared, frame):
    obj = _fg_item(frame, "PlaneOrientationSequence") or _fg_item(shared, "PlaneOrientationSequence")
    if obj is None:
        raise DicomError("enhanced multiframe is missing Plane Orientation")
    row = np.asarray([float(v) for v in obj.ImageOrientationPatient[:3]])
    col = np.asarray([float(v) for v in obj.ImageOrientationPatient[3:]])
    _validate_dirs(row, col)
    return row, col


def _fg_position(frame):
    obj = _fg_item(frame, "PlanePositionSequence")
    if obj is None:
        raise DicomError("enhanced multiframe is missing Plane Position")
    return np.asarray([float(v) for v in obj.ImagePositionPatient], dtype=float)


def _canonical_image(volume: np.ndarray, affine_lps: np.ndarray, root: Path, candidate: DicomSeriesCandidate) -> ImageVolume:
    import nibabel as nib
    affine_ras = LPS_TO_RAS @ affine_lps
    nii = nib.Nifti1Image(np.ascontiguousarray(volume.astype(np.float32)), affine_ras)
    canonical = nib.as_closest_canonical(nii)
    data = np.ascontiguousarray(np.asanyarray(canonical.dataobj).astype(np.float32))
    spacing = tuple(float(np.linalg.norm(canonical.affine[:3, i])) for i in range(3))
    geometry = ImageGeometry.from_affine(data.shape, canonical.affine, spacing=spacing)
    if not geometry.validation.ok:
        raise DicomError("; ".join(geometry.validation.errors))
    return ImageVolume(data, geometry.spacing, geometry.affine, str(root), geometry=geometry)


def series_identity(candidate: DicomSeriesCandidate, image: ImageVolume) -> dict:
    files = []
    for name in candidate.files:
        p = Path(name)
        st = p.stat()
        files.append({
            "name_sha256": hashlib.sha256(p.name.encode("utf-8")).hexdigest(),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": _hash_file(p),
        })
    identity = {
        "type": "dicom-series",
        "locator": os.path.normcase(os.path.realpath(os.path.abspath(str(scan_root(candidate.files[0]))))),
        "study_uid": candidate.study_uid,
        "series_uid": candidate.series_uid,
        "frame_of_reference_uid": candidate.frame_of_reference_uid,
        "sop_class_uid": candidate.sop_class_uid,
        "modality": candidate.modality,
        "kind": candidate.kind,
        "files": files,
        "shape": list(image.shape),
        "affine": np.asarray(image.affine, dtype=float).tolist(),
        "spacing": list(image.spacing),
    }
    identity["identity_sha256"] = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return identity


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
