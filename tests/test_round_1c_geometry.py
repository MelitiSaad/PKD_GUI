import numpy as np
import pytest

from pkdqc.core.geometry import ImageGeometry, markers_for_plane
from pkdqc.core.planes import PLANES
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume
from pkdqc.core.volumetry import compute_volumes
from pkdqc.core import io, session


def geom(shape=(5, 6, 7), affine=None, spacing=None):
    if affine is None:
        affine = np.diag([2.0, 3.0, 4.0, 1.0])
    return ImageGeometry.from_affine(shape, affine, spacing=spacing)


def test_axis_aligned_ras_geometry_contract():
    g = geom()
    assert g.validation.ok
    assert g.orientation == "RAS"
    assert g.handedness == "right"
    assert g.voxel_volume_mm3 == pytest.approx(24.0)
    assert np.allclose(g.voxel_to_world((1, 2, 3)), (2, 6, 12))
    assert np.allclose(g.world_to_voxel((2, 6, 12)), (1, 2, 3))


def test_flipped_negative_determinant_markers():
    aff = np.diag([-1.5, 2.0, 2.5, 1.0])
    g = geom(affine=aff)
    assert g.validation.ok
    assert g.orientation == "LAS"
    assert g.handedness == "left"
    assert g.voxel_volume_mm3 == pytest.approx(7.5)
    axial = markers_for_plane(g, PLANES["axial"])
    assert axial == {"top": "A", "bottom": "P", "left": "L", "right": "R"}


def test_oblique_rotation_allowed_but_shear_rejected():
    theta = np.deg2rad(30)
    rot = np.array([[np.cos(theta), -np.sin(theta), 0], [np.sin(theta), np.cos(theta), 0], [0, 0, 1]])
    aff = np.eye(4); aff[:3, :3] = rot @ np.diag([1.0, 2.0, 3.0])
    g = geom(affine=aff)
    assert g.validation.ok
    shear = aff.copy(); shear[0, 1] += 0.4
    bad = geom(affine=shear)
    assert not bad.validation.ok
    assert "shear" in "; ".join(bad.validation.errors)


@pytest.mark.parametrize("affine", [np.eye(4) * np.nan, np.diag([1, 0, 1, 1]), np.diag([1, 1, 1e-12, 1])])
def test_invalid_affines_rejected(affine):
    g = ImageGeometry.from_affine((3, 3, 3), affine, spacing=(1, 1, 1))
    assert not g.validation.ok


def test_spacing_units_and_header_policy(tmp_path):
    nib = pytest.importorskip("nibabel")
    path = tmp_path / "bad_units.nii.gz"
    img = nib.Nifti1Image(np.zeros((3, 3, 3), np.float32), np.eye(4))
    img.header.set_xyzt_units("meter")
    nib.save(img, str(path))
    with pytest.raises(io.LoadError, match="unsupported spatial units"):
        io.load_image(str(path))


def test_qform_sform_conflict_rejected(tmp_path):
    nib = pytest.importorskip("nibabel")
    path = tmp_path / "conflict.nii.gz"
    img = nib.Nifti1Image(np.zeros((4, 4, 4), np.float32), np.eye(4))
    img.set_qform(np.eye(4), code=1)
    img.set_sform(np.diag([2, 2, 2, 1]), code=1)
    nib.save(img, str(path))
    with pytest.raises(io.LoadError, match="conflicting qform and sform"):
        io.load_image(str(path))


def test_segmentation_shape_and_affine_mismatch(tmp_path):
    nib = pytest.importorskip("nibabel")
    imgp = tmp_path / "img.nii.gz"; segp = tmp_path / "seg.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((4, 5, 6), np.float32), np.eye(4)), str(imgp))
    nib.save(nib.Nifti1Image(np.zeros((4, 5, 6), np.uint16), np.diag([2, 1, 1, 1])), str(segp))
    image = io.load_image(str(imgp))
    with pytest.raises(io.LoadError, match="affine"):
        io.load_segmentation(str(segp), image.shape, image.affine)


def test_determinant_volume_mm3_and_ml_for_rotated_and_flipped():
    aff = np.diag([-2.0, 3.0, 4.0, 1.0])
    image = ImageVolume(np.ones((4, 4, 4), np.float32), (2, 3, 4), aff)
    seg = Segmentation(np.zeros(image.shape, np.uint16))
    seg.data[:2, :2, :2] = 1
    vols = compute_volumes(seg, image)
    v = next(x for x in vols if x.id == 1)
    assert v.voxels == 8
    assert v.mm3 == pytest.approx(8 * abs(np.linalg.det(aff[:3, :3])))
    assert v.ml == pytest.approx(v.mm3 / 1000.0)


def test_all_three_plane_display_mappings_and_markers():
    g = geom(shape=(3, 4, 5), affine=np.diag([1, 2, 3, 1]))
    expected = {
        "axial": {"top": "A", "bottom": "P", "left": "R", "right": "L"},
        "coronal": {"top": "S", "bottom": "I", "left": "R", "right": "L"},
        "sagittal": {"top": "S", "bottom": "I", "left": "A", "right": "P"},
    }
    for name, plane in PLANES.items():
        assert markers_for_plane(g, plane) == expected[name]
        cursor = [1, 2, 3]
        assert plane.disp_to_vox(*plane.vox_to_disp(cursor, g.shape), cursor, g.shape) == tuple(cursor)


def test_asymmetric_phantom_edit_and_save_reload_geometry(tmp_path):
    nib = pytest.importorskip("nibabel")
    shape = (7, 8, 9)
    aff = np.diag([1.2, 2.0, 3.0, 1.0])
    data = np.zeros(shape, np.float32)
    # Distinguishable patient-space features: R=max x, A=max y, S=max z.
    data[6, 1, 1] = 10; data[1, 7, 1] = 20; data[1, 1, 8] = 30
    imgp = tmp_path / "phantom.nii.gz"
    nib.save(nib.Nifti1Image(data, aff), str(imgp))
    image = io.load_image(str(imgp))
    assert image.data[6, 1, 1] == 10
    assert image.geometry.voxel_to_world((6, 1, 1))[0] > image.geometry.voxel_to_world((1, 1, 1))[0]
    seg = Segmentation.empty_like(image.shape)
    cursor = [3, 4, 5]
    for plane in PLANES.values():
        v, h = plane.vox_to_disp(cursor, image.shape)
        vox = plane.disp_to_vox(v, h, cursor, image.shape)
        seg.data[vox] = 9
    assert seg.data[tuple(cursor)] == 9
    out = tmp_path / "seg_QC.nii.gz"
    io.save_segmentation(seg, image, str(out))
    reloaded = io.load_segmentation(str(out), image.shape, image.affine)
    assert np.array_equal(reloaded.data, seg.data)
    saved = nib.load(str(out))
    assert np.allclose(saved.affine, image.affine)
    assert abs(np.linalg.det(saved.affine[:3, :3])) == pytest.approx(image.voxel_volume_mm3)


def test_recovery_v2_geometry_compatibility_and_failure_preserves_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import importlib
    import pkdqc.config as cfg
    import pkdqc.core.session as sess
    importlib.reload(cfg); importlib.reload(sess)
    path = tmp_path / "source.nii"; path.write_bytes(b"source")
    image = ImageVolume(np.zeros((3, 3, 3), np.float32), (1, 1, 1), np.eye(4), str(path))
    seg = Segmentation.empty_like(image.shape); seg.data[1, 1, 1] = 2
    s = sess.Session(image); s.begin(); assert s.save(seg, dirty=True)
    rec = sess.find_recoverable()[0]
    wrong = ImageVolume(np.zeros((3, 3, 3), np.float32), (1, 1, 1), np.diag([2, 1, 1, 1]), str(path))
    with pytest.raises(sess.RecoveryError):
        sess.validate_recovery_image(rec, wrong)
    assert sess.find_recoverable()
