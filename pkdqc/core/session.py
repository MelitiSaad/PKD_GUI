"""Recovery v2: versioned, verified, transactional emergency checkpoints.

Each session contains immutable generation directories.  A generation is written
under ``.tmp-*`` and renamed to its final unique name only after both labels and
manifest have been flushed.  The rename is the commit point; no directory is
replaced, which is safe on Windows and leaves older generations untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from .. import config
from ..config import sessions_dir
from .labels import LabelTable
from .segmentation import Segmentation
from .volume import ImageVolume

SCHEMA_VERSION = 2
MAX_GENERATIONS = 2
MANIFEST = "manifest.json"
LABELS = "labels.npy"
FaultHook = Callable[[str], None]


class RecoveryError(Exception):
    """A checkpoint is invalid or cannot safely be recovered."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_identity(image_or_path, shape=None, affine=None, spacing=None) -> dict:
    """Calculate a stable source identity once when a case/session is created."""
    if isinstance(image_or_path, ImageVolume):
        if getattr(image_or_path, "source_identity", None):
            return dict(image_or_path.source_identity)
        path = image_or_path.path
        shape, affine, spacing = image_or_path.shape, image_or_path.affine, image_or_path.spacing
    else:
        path = str(image_or_path)
    normalized = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    stat = os.stat(path)
    identity = {
        "type": "nifti-file" if path.lower().endswith((".nii", ".nii.gz")) else "file",
        "locator": normalized,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256_file(Path(path)),
        "shape": list(shape) if shape is not None else None,
        "affine": np.asarray(affine if affine is not None else np.eye(4), dtype=float).tolist(),
        "spacing": list(spacing if spacing is not None else (1.0, 1.0, 1.0)),
    }
    identity["identity_sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return identity


def _identity_digest(identity: dict) -> str:
    content = {key: value for key, value in identity.items() if key != "identity_sha256"}
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_labels(path: Path, data: np.ndarray, hook: FaultHook) -> None:
    hook("before_data_write")
    with path.open("wb") as stream:
        np.save(stream, data, allow_pickle=False)
        hook("during_data_write")
        stream.flush(); os.fsync(stream.fileno())


def _write_manifest(path: Path, manifest: dict, hook: FaultHook) -> None:
    hook("before_manifest_write")
    payload = json.dumps(manifest, indent=2, sort_keys=True)
    with path.open("w", encoding="utf-8") as stream:
        stream.write(payload)
        hook("during_manifest_write")
        stream.flush(); os.fsync(stream.fileno())


def _generation_revision(path: Path) -> int:
    try:
        return int(json.loads((path / MANIFEST).read_text(encoding="utf-8")).get("revision", -1))
    except Exception:
        return -1

def _noop(_phase: str) -> None:
    pass


class Session:
    def __init__(self, image_or_path, seg_path: Optional[str] = None,
                 fault_hook: Optional[FaultHook] = None):
        self.image = image_or_path if isinstance(image_or_path, ImageVolume) else None
        self.image_path = self.image.path if self.image is not None else str(image_or_path)
        self.seg_path = seg_path
        # Random IDs prevent unrelated launches with the same paths sharing state.
        self.id = uuid.uuid4().hex
        self.dir = sessions_dir() / self.id
        self.generations = self.dir / "generations"
        self.created = time.time()
        self._last_revision = -1
        self._fault = fault_hook or _noop
        self._source_identity = source_identity(self.image or self.image_path)

    def begin(self) -> None:
        self.generations.mkdir(parents=True, exist_ok=True)
        _fsync_dir(self.dir)

    def save(self, seg: Segmentation, force: bool = False, *, saved_revision=None,
             dirty: Optional[bool] = None) -> bool:
        if not force and seg.revision == self._last_revision:
            return False
        self.begin()
        generation = uuid.uuid4().hex
        temp = self.generations / f".tmp-{generation}"
        committed = self.generations / generation
        temp.mkdir()
        try:
            labels = temp / LABELS
            _write_labels(labels, seg.data, self._fault)
            self._fault("after_data_write")
            checksum = _sha256_file(labels)
            identity = dict(self._source_identity)
            if identity["shape"] is None:
                identity["shape"] = list(seg.data.shape)
                identity["identity_sha256"] = _identity_digest(identity)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "session_id": self.id,
                "generation_id": generation,
                "created_at": self.created,
                "updated_at": time.time(),
                "segmentation": {"file": LABELS, "shape": list(seg.data.shape),
                                 "dtype": str(seg.data.dtype), "sha256": checksum},
                "source_image": identity,
                "source_shape": identity["shape"],
                "source_affine": identity["affine"],
                "voxel_spacing": identity["spacing"],
                "segmentation_path": self.seg_path,
                "revision": seg.revision,
                "saved_revision": saved_revision,
                "dirty": bool(seg.dirty if dirty is None else dirty),
                "application_version": getattr(config, "VERSION", None),
            }
            _write_manifest(temp / MANIFEST, manifest, self._fault)
            self._fault("before_commit")
            os.replace(temp, committed)  # unique destination: atomic visibility/commit
            _fsync_dir(self.generations)
            self._fault("during_commit")
            self._last_revision = seg.revision
            self._fault("after_commit")
            self._cleanup()
            return True
        except BaseException:
            # Incomplete temporary state is never discoverable as a generation.
            shutil.rmtree(temp, ignore_errors=True)
            raise

    def _cleanup(self) -> None:
        self._fault("during_cleanup")
        valid = sorted((p for p in self.generations.iterdir()
                        if p.is_dir() and not p.name.startswith(".")),
                       key=lambda p: (_generation_revision(p), p.stat().st_mtime_ns), reverse=True)
        for old in valid[MAX_GENERATIONS:]:
            shutil.rmtree(old, ignore_errors=True)

    def mark_clean(self, remove: bool = True) -> None:
        if remove:
            shutil.rmtree(self.dir, ignore_errors=True)


@dataclass
class Recoverable:
    session_id: str
    generation_id: str
    image_path: str
    seg_path: Optional[str]
    labels_path: str
    manifest_path: str
    updated: float
    revision: int
    saved_revision: Optional[int]
    dirty: bool
    warning: Optional[str] = None

    @property
    def age_str(self) -> str:
        secs = max(0, time.time() - self.updated)
        if secs < 90: return f"{int(secs)}s ago"
        if secs < 5400: return f"{int(secs / 60)} min ago"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.updated))


def _validate_generation(path: Path, expected_session: str) -> tuple[dict, np.ndarray]:
    try:
        manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
    except Exception as exc:
        raise RecoveryError("manifest is missing or malformed") from exc
    required = {"schema_version", "session_id", "generation_id", "created_at", "updated_at",
                "segmentation", "source_image", "source_shape", "source_affine",
                "voxel_spacing", "revision", "saved_revision", "dirty"}
    if not required.issubset(manifest):
        raise RecoveryError("manifest is missing required fields")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise RecoveryError("unsupported recovery schema version")
    if manifest["session_id"] != expected_session or manifest["generation_id"] != path.name:
        raise RecoveryError("session or generation identifier mismatch")
    info = manifest["segmentation"]
    if not {"file", "shape", "dtype", "sha256"}.issubset(info):
        raise RecoveryError("segmentation metadata is incomplete")
    labels_path = path / info["file"]
    if not labels_path.is_file():
        raise RecoveryError("segmentation data is missing")
    if _sha256_file(labels_path) != info["sha256"]:
        raise RecoveryError("segmentation checksum mismatch")
    try:
        data = np.load(labels_path, allow_pickle=False)
    except Exception as exc:
        raise RecoveryError("segmentation data is unreadable") from exc
    if list(data.shape) != info["shape"] or str(data.dtype) != info["dtype"]:
        raise RecoveryError("segmentation shape or dtype mismatch")
    if data.dtype != np.uint16:
        raise RecoveryError("unsupported segmentation dtype")
    if not isinstance(manifest["revision"], int) or manifest["revision"] < 0:
        raise RecoveryError("invalid document revision")
    saved = manifest["saved_revision"]
    if saved is not None and (not isinstance(saved, int) or saved < 0):
        raise RecoveryError("invalid saved revision")
    if bool(manifest["dirty"]) != (manifest["revision"] != saved):
        raise RecoveryError("dirty and revision state are inconsistent")
    source = manifest["source_image"]
    if source.get("identity_sha256") != _identity_digest(source):
        raise RecoveryError("source image identity record is corrupt")
    if source.get("shape") != manifest["source_shape"]:
        raise RecoveryError("source shape is inconsistent")
    if info["shape"] != manifest["source_shape"]:
        raise RecoveryError("segmentation and source shape mismatch")
    if not np.allclose(source.get("affine"), manifest["source_affine"]):
        raise RecoveryError("source affine is inconsistent")
    if not np.allclose(source.get("spacing"), manifest["voxel_spacing"]):
        raise RecoveryError("source spacing is inconsistent")
    if source.get("type") == "dicom-series":
        from . import dicom
        try:
            img = dicom.load_series(source["locator"], source_identity=source)
        except Exception as exc:
            raise RecoveryError("DICOM source identity mismatch") from exc
        if list(img.shape) != source.get("shape"):
            raise RecoveryError("source image identity mismatch")
    else:
        current = source_identity(source["locator"], source["shape"], source["affine"], source["spacing"])
        for key in ("size", "mtime_ns", "sha256", "shape"):
            if current[key] != source.get(key):
                raise RecoveryError("source image identity mismatch")
    return manifest, data


def _mark_invalid(generation: Path, reason: str) -> None:
    # Reasons are deliberately categorical and contain no paths or patient metadata.
    try:
        (generation / "INVALID.txt").write_text(reason + "\n", encoding="utf-8")
    except OSError:
        pass


def find_recoverable() -> List[Recoverable]:
    out: List[Recoverable] = []
    base = sessions_dir()
    if not base.exists(): return out
    for directory in base.iterdir():
        if not directory.is_dir(): continue
        generations = directory / "generations"
        if not generations.is_dir():
            # Recovery v1 cannot be bound to a source fingerprint; retain and mark it.
            if (directory / "meta.json").exists():
                _mark_invalid(directory, "legacy Recovery v1 requires manual review")
            continue
        candidates = sorted((p for p in generations.iterdir()
                             if p.is_dir() and not p.name.startswith(".")),
                            key=lambda p: (_generation_revision(p), p.stat().st_mtime_ns), reverse=True)
        warning = None
        for generation in candidates:
            try:
                manifest, _ = _validate_generation(generation, directory.name)
            except Exception as exc:
                reason = str(exc) if isinstance(exc, RecoveryError) else "unexpected validation error"
                _mark_invalid(generation, reason)
                warning = "A newer checkpoint was invalid; an earlier valid checkpoint is available."
                continue
            if not manifest["dirty"]:
                # The newest valid generation is authoritative: an older dirty
                # generation must not be offered after a clean checkpoint.
                break
            source = manifest["source_image"]
            out.append(Recoverable(directory.name, generation.name, source["locator"],
                                   manifest.get("segmentation_path"), str(generation / LABELS),
                                   str(generation / MANIFEST), manifest["updated_at"],
                                   manifest["revision"], manifest["saved_revision"], True, warning))
            break
    out.sort(key=lambda item: item.updated, reverse=True)
    return out


def load_recovered_segmentation(rec: Recoverable) -> Segmentation:
    generation = Path(rec.manifest_path).parent
    manifest, data = _validate_generation(generation, rec.session_id)
    seg = Segmentation(data, LabelTable.from_ids(np.unique(data)))
    seg.revision = manifest["revision"]
    seg.dirty = manifest["dirty"]
    return seg


def validate_recovery_image(rec: Recoverable, image: ImageVolume) -> None:
    """Verify the reopened image still has the checkpoint's loaded geometry."""
    manifest = json.loads(Path(rec.manifest_path).read_text(encoding="utf-8"))
    source = manifest.get("source_image", {})
    if source.get("type") == "dicom-series":
        current = getattr(image, "source_identity", None)
        if current is None or current.get("identity_sha256") != source.get("identity_sha256"):
            raise RecoveryError("reopened DICOM source identity mismatch")
    if list(image.shape) != manifest["source_shape"]:
        raise RecoveryError("reopened source image shape mismatch")
    if not np.allclose(image.affine, manifest["source_affine"], rtol=1e-5, atol=1e-3):
        raise RecoveryError("reopened source image affine mismatch")
    if not np.allclose(image.spacing, manifest["voxel_spacing"], rtol=1e-6, atol=1e-6):
        raise RecoveryError("reopened source image spacing mismatch")


def recovery_source_identity(rec: Recoverable) -> dict:
    """Return PHI-safe source identity stored in a recovery manifest."""
    manifest = json.loads(Path(rec.manifest_path).read_text(encoding="utf-8"))
    return manifest.get("source_image", {})


def discard(rec: Recoverable) -> None:
    shutil.rmtree(sessions_dir() / rec.session_id, ignore_errors=True)
