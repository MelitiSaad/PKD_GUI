import json
import os
from pathlib import Path

import numpy as np
import pytest

from pkdqc.core.document import Disposition, SegmentationDocument
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    from pkdqc.core import session
    source = tmp_path / "source.nii.gz"
    source.write_bytes(b"deidentified-source-content")
    image = ImageVolume(np.zeros((3, 4, 2), np.float32), (1.1, 1.2, 2.5),
                        np.diag([1.1, 1.2, 2.5, 1.0]), str(source))
    return session, image


def dirty_seg(shape, value=1, revision=1):
    seg = Segmentation(np.zeros(shape, np.uint16))
    seg.data[0, 0, 0] = value
    seg.revision = revision
    seg.dirty = True
    return seg


def generation_dirs(s):
    return sorted((p for p in s.generations.iterdir()
                   if p.is_dir() and not p.name.startswith(".")),
                  key=lambda p: p.stat().st_mtime_ns)


def test_v2_round_trip_restores_document_state(recovery):
    session, image = recovery
    seg = dirty_seg(image.shape, 7, 4)
    s = session.Session(image, "/safe/output_QC.nii.gz")
    assert s.save(seg, saved_revision=2, dirty=True)
    rec = session.find_recoverable()[0]
    assert rec.seg_path == "/safe/output_QC.nii.gz"
    assert (rec.revision, rec.saved_revision, rec.dirty) == (4, 2, True)
    restored = session.load_recovered_segmentation(rec)
    session.validate_recovery_image(rec, image)
    np.testing.assert_array_equal(restored.data, seg.data)
    assert restored.revision == 4 and restored.dirty
    manifest = json.loads(Path(rec.manifest_path).read_text())
    assert manifest["schema_version"] == 2
    assert manifest["segmentation"]["dtype"] == "uint16"
    assert manifest["source_shape"] == list(image.shape)
    assert np.allclose(manifest["source_affine"], image.affine)
    assert np.allclose(manifest["voxel_spacing"], image.spacing)


def test_reopened_image_geometry_must_match(recovery):
    session, image = recovery
    s = session.Session(image); s.save(dirty_seg(image.shape), saved_revision=0, dirty=True)
    rec = session.find_recoverable()[0]
    wrong_affine = ImageVolume(image.data, image.spacing, image.affine.copy(), image.path)
    wrong_affine.affine[0, 3] = 5
    with pytest.raises(session.RecoveryError, match="affine"):
        session.validate_recovery_image(rec, wrong_affine)
    wrong_spacing = ImageVolume(image.data, (9, 9, 9), image.affine, image.path)
    with pytest.raises(session.RecoveryError, match="spacing"):
        session.validate_recovery_image(rec, wrong_spacing)


@pytest.mark.parametrize("phase,new_committed", [
    ("before_data_write", False), ("during_data_write", False),
    ("after_data_write", False), ("before_manifest_write", False),
    ("during_manifest_write", False), ("before_commit", False),
    ("during_commit", True), ("after_commit", True), ("during_cleanup", True),
])
def test_fault_at_every_phase_leaves_a_coherent_generation(recovery, phase, new_committed):
    session, image = recovery
    base = session.Session(image)
    base.save(dirty_seg(image.shape, 1, 1), saved_revision=0, dirty=True)

    def fail(visited):
        if visited == phase:
            raise RuntimeError(f"simulated termination at {phase}")
    base._fault = fail
    with pytest.raises(RuntimeError, match="simulated termination"):
        base.save(dirty_seg(image.shape, 2, 2), saved_revision=0, dirty=True)

    recs = session.find_recoverable()
    assert len(recs) == 1
    restored = session.load_recovered_segmentation(recs[0])
    assert restored.data[0, 0, 0] == (2 if new_committed else 1)
    # Temporary/incomplete directories are never offered.
    assert all(not p.name.startswith(".tmp-") or p not in
               [Path(r.manifest_path).parent for r in recs]
               for p in base.generations.iterdir())


def test_corrupt_newest_falls_back_and_marks_invalid(recovery):
    session, image = recovery
    s = session.Session(image)
    s.save(dirty_seg(image.shape, 3, 1), saved_revision=0, dirty=True)
    s.save(dirty_seg(image.shape, 4, 2), saved_revision=0, dirty=True)
    newest = generation_dirs(s)[-1]
    (newest / session.LABELS).write_bytes(b"truncated")
    rec = session.find_recoverable()[0]
    assert rec.warning and rec.generation_id != newest.name
    assert session.load_recovered_segmentation(rec).data[0, 0, 0] == 3
    assert (newest / "INVALID.txt").exists()


@pytest.mark.parametrize("damage,reason", [
    ("checksum", "checksum"), ("missing", "missing"), ("truncated", "checksum"),
    ("malformed", "malformed"), ("version", "unsupported"),
    ("dtype", "dtype"), ("affine", "affine"), ("spacing", "spacing"),
    ("revision", "revision"),
])
def test_invalid_checkpoint_is_not_offered_or_deleted(recovery, damage, reason):
    session, image = recovery
    s = session.Session(image); s.save(dirty_seg(image.shape), saved_revision=0, dirty=True)
    gen = generation_dirs(s)[0]; mp = gen / session.MANIFEST; lp = gen / session.LABELS
    manifest = json.loads(mp.read_text())
    if damage == "checksum": manifest["segmentation"]["sha256"] = "0" * 64
    elif damage == "missing": lp.unlink()
    elif damage == "truncated": lp.write_bytes(b"bad")
    elif damage == "malformed": mp.write_text("{")
    elif damage == "version": manifest["schema_version"] = 99
    elif damage == "dtype": manifest["segmentation"]["dtype"] = "uint8"
    elif damage == "affine": manifest["source_affine"][0][3] = 99
    elif damage == "spacing": manifest["voxel_spacing"][0] = 99
    elif damage == "revision": manifest["dirty"] = False
    if damage not in {"missing", "truncated", "malformed"}: mp.write_text(json.dumps(manifest))
    assert session.find_recoverable() == []
    assert gen.exists() and (gen / "INVALID.txt").exists()
    assert reason in (gen / "INVALID.txt").read_text().lower()


def test_same_shape_different_source_is_rejected(recovery):
    session, image = recovery
    s = session.Session(image); s.save(dirty_seg(image.shape), saved_revision=0, dirty=True)
    Path(image.path).write_bytes(b"different-image-with-the-same-array-shape")
    assert session.find_recoverable() == []
    assert "identity" in (generation_dirs(s)[0] / "INVALID.txt").read_text()


def test_discard_clean_close_cancel_and_no_sessions(recovery):
    session, image = recovery
    assert session.find_recoverable() == []
    s = session.Session(image); seg = dirty_seg(image.shape)
    s.save(seg, saved_revision=0, dirty=True)
    doc = SegmentationDocument(image, seg, None, 0, True)
    assert not doc.guard(lambda: Disposition.CANCEL, lambda: False, s.mark_clean)
    assert len(session.find_recoverable()) == 1  # cancel preserves recovery
    rec = session.find_recoverable()[0]; session.discard(rec)
    assert session.find_recoverable() == []
    s2 = session.Session(image); s2.save(seg, saved_revision=seg.revision, dirty=False)
    assert session.find_recoverable() == []  # clean checkpoints are never offered
    s2.mark_clean(); assert not s2.dir.exists()


def test_clean_newest_generation_suppresses_older_dirty_work(recovery):
    session, image = recovery
    s = session.Session(image)
    s.save(dirty_seg(image.shape, revision=1), saved_revision=0, dirty=True)
    clean = dirty_seg(image.shape, revision=2); clean.dirty = False
    s.save(clean, saved_revision=2, dirty=False)
    assert session.find_recoverable() == []


def test_multiple_sessions_and_retention_limit(recovery, tmp_path):
    session, image = recovery
    other_path = tmp_path / "other.nii"; other_path.write_bytes(b"other")
    other = ImageVolume(image.data.copy(), image.spacing, image.affine.copy(), str(other_path))
    sessions = [session.Session(image), session.Session(other)]
    for s in sessions:
        for revision in range(1, 5):
            s.save(dirty_seg(image.shape, revision, revision), saved_revision=0, dirty=True)
        assert len(generation_dirs(s)) == session.MAX_GENERATIONS
    assert len(session.find_recoverable()) == 2


def test_legacy_v1_is_retained_but_not_trusted(recovery):
    session, _image = recovery
    legacy = session.sessions_dir() / "legacy-session"
    legacy.mkdir(parents=True); (legacy / "meta.json").write_text('{"clean_exit": false}')
    (legacy / "labels.npy").write_bytes(b"unverified")
    assert session.find_recoverable() == []
    assert legacy.exists()
    assert "legacy" in (legacy / "INVALID.txt").read_text().lower()


def test_invalid_reason_is_phi_safe(recovery):
    session, image = recovery
    s = session.Session(image); s.save(dirty_seg(image.shape), saved_revision=0, dirty=True)
    gen = generation_dirs(s)[0]
    (gen / session.MANIFEST).write_text("not json")
    session.find_recoverable()
    reason = (gen / "INVALID.txt").read_text()
    assert image.path not in reason and Path(image.path).name not in reason
