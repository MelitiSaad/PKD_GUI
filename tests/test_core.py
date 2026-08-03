import os
import numpy as np
import pytest

from pkdqc.core.labels import LabelTable
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume
from pkdqc.core.volumetry import compute_volumes, total_volume
from pkdqc.core.commands import StrokeRecorder, apply_slice, apply_volume
from pkdqc.core.history import History
from pkdqc.core import segops


def make_seg(shape=(32, 32, 8)):
    data = np.zeros(shape, dtype=np.uint16)
    data[8:16, 8:16, 3] = 1          # a square blob of label 1 on slice 3
    return Segmentation(data)


def make_image(shape=(32, 32, 8), spacing=(1.5, 1.5, 3.0)):
    rng = np.random.default_rng(0)
    return ImageVolume(rng.random(shape).astype(np.float32) * 100, spacing, np.eye(4))


# ---------------------------------------------------------------- labels
def test_label_table_and_lut():
    t = LabelTable.from_ids([0, 1, 2, 5])
    assert set(t.labels) == {1, 2, 5}
    lut = t.lut()
    assert lut.shape == (6, 4)
    assert tuple(lut[0]) == (0, 0, 0, 0)          # background transparent
    assert lut[1, 3] == t.alpha                    # label alpha applied


# ---------------------------------------------------------------- volumetry
def test_volume_mm3_and_ml():
    seg = make_seg()
    img = make_image(spacing=(2.0, 2.0, 2.0))     # 8 mm^3 per voxel
    vols = compute_volumes(seg, img)
    v1 = next(v for v in vols if v.id == 1)
    assert v1.voxels == 64                          # 8x8 square
    assert v1.mm3 == pytest.approx(64 * 8.0)
    assert v1.ml == pytest.approx(64 * 8.0 / 1000.0)
    tot = total_volume(vols)
    assert tot.voxels == 64


# ---------------------------------------------------------------- commands/undo
def test_stroke_recorder_undo_redo():
    seg = make_seg()
    hist = History(seg)
    rec = StrokeRecorder(seg, "paint")
    dr, dc = segops.disk_offsets(2)
    rec.stamp(3, dr + 20, dc + 20, 2)               # paint label 2 near (20,20)
    cmd = rec.commit()
    hist.push(cmd)
    painted = int((seg.data == 2).sum())
    assert painted > 0
    hist.undo()
    assert int((seg.data == 2).sum()) == 0          # fully reverted
    hist.redo()
    assert int((seg.data == 2).sum()) == painted     # fully restored


def test_apply_slice_diff_and_undo():
    seg = make_seg()
    hist = History(seg)
    new_slice = seg.data[:, :, 3].copy()
    new_slice[0:4, 0:4] = 3
    cmd = apply_slice(seg, 3, new_slice, "edit")
    hist.push(cmd)
    assert int((seg.data[:, :, 3] == 3).sum()) == 16
    hist.undo()
    assert int((seg.data == 3).sum()) == 0


def test_history_byte_cap():
    seg = make_seg()
    hist = History(seg, max_bytes=1)                 # force immediate trimming
    for i in range(5):
        s = seg.data[:, :, 0].copy()
        s[i, i] = 1
        hist.push(apply_slice(seg, 0, s, "e"))
    assert len(hist._undo) == 1                       # capped to 1, never empties fully


# ---------------------------------------------------------------- segops
def test_flood_fill():
    seg = make_seg()
    from pkdqc.core.label_policy import LabelProtectionPolicy, DrawOver
    cmd = segops.flood_fill(seg, 3, 10, 10, 4,
                            policy=LabelProtectionPolicy(DrawOver.ALL_PERMITTED))
    assert cmd is not None
    History(seg).push(cmd)
    assert int((seg.data[:, :, 3] == 4).sum()) == 64  # whole square recolored


def test_safe_erase_mask_only_targets_active_label():
    values = np.array([0, 1, 2, 1], dtype=np.uint16)
    assert np.array_equal(segops.paintable_mask(values, 0, True, erase_label=1),
                          np.array([False, True, False, True]))


def test_segmentation_layers_keep_independent_editing_state():
    from pkdqc.core.layers import SegmentationLayers
    layers = SegmentationLayers()
    organs = layers.add("Organs", make_seg(), make_active=True)
    cysts = layers.add("Cysts", Segmentation(np.zeros((32, 32, 8), np.uint16)), locked=True)
    assert layers.active is organs
    assert layers.visible_layers() == (organs, cysts)
    with pytest.raises(ValueError):
        layers.set_active(1)
    assert organs.history is not cysts.history


def test_grow_and_shrink_3d():
    seg = make_seg()
    before = int((seg.data == 1).sum())
    History(seg).push(segops.grow(seg, 1, iterations=1, in_3d=True))
    assert int((seg.data == 1).sum()) > before
    grown = int((seg.data == 1).sum())
    History(seg).push(segops.shrink(seg, 1, iterations=1, in_3d=True))
    assert int((seg.data == 1).sum()) < grown


def test_remove_islands():
    seg = make_seg()
    seg.data[0, 0, 3] = 1                              # a 1-voxel island
    seg.data[30, 30, 3] = 1                            # another
    cmd = segops.remove_islands(seg, 1, min_size=10, in_3d=False, z=3)
    assert cmd is not None
    History(seg).push(cmd)
    assert seg.data[0, 0, 3] == 0 and seg.data[30, 30, 3] == 0
    assert int((seg.data[8:16, 8:16, 3] == 1).sum()) == 64  # big blob kept


def test_fill_holes():
    seg = Segmentation(np.zeros((32, 32, 4), dtype=np.uint16))
    seg.data[10:20, 10:20, 1] = 1
    seg.data[14:16, 14:16, 1] = 0                      # punch a hole
    cmd = segops.fill_holes(seg, 1, in_3d=False, z=1)
    assert cmd is not None
    History(seg).push(cmd)
    assert int((seg.data[14:16, 14:16, 1] == 1).sum()) == 4


def test_interpolate_between():
    seg = Segmentation(np.zeros((32, 32, 10), dtype=np.uint16))
    seg.data[10:22, 10:22, 2] = 1                      # blob on slice 2
    seg.data[10:22, 10:22, 7] = 1                      # same blob on slice 7
    assert int((seg.data[:, :, 4] == 1).sum()) == 0    # empty in between
    cmd = segops.interpolate_between(seg, 1, 2, 7)
    assert cmd is not None
    History(seg).push(cmd)
    assert int((seg.data[:, :, 4] == 1).sum()) > 0     # gap filled


# ---------------------------------------------------------------- session
def test_session_recovery(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import importlib
    from pkdqc import config as cfg
    importlib.reload(cfg)
    from pkdqc.core import session as sess
    importlib.reload(sess)

    img_file = tmp_path / "img.nii"
    img_file.write_bytes(b"stub")                      # only needs to exist
    seg = make_seg()

    s = sess.Session(str(img_file), None)
    s.begin()
    seg.data[0, 0, 0] = 7
    seg.mark_edited([0])
    assert s.save(seg) is True

    recs = sess.find_recoverable()
    assert len(recs) == 1
    recovered = sess.load_recovered_segmentation(recs[0])
    assert recovered.data[0, 0, 0] == 7

    s.mark_clean()
    assert sess.find_recoverable() == []               # gone after clean exit


# ---------------------------------------------------------------- io roundtrip
def test_nifti_roundtrip(tmp_path):
    nib = pytest.importorskip("nibabel")
    from pkdqc.core import io

    img_arr = (np.random.default_rng(1).random((24, 24, 6)) * 200).astype(np.float32)
    nib.save(nib.Nifti1Image(img_arr, np.diag([1.5, 1.5, 3.0, 1.0])), str(tmp_path / "img.nii.gz"))
    seg_arr = np.zeros((24, 24, 6), dtype=np.uint16)
    seg_arr[5:10, 5:10, 2] = 1
    nib.save(nib.Nifti1Image(seg_arr, np.diag([1.5, 1.5, 3.0, 1.0])), str(tmp_path / "seg.nii.gz"))

    image = io.load_image(str(tmp_path / "img.nii.gz"))
    assert image.shape == (24, 24, 6)
    assert image.voxel_volume_mm3 == pytest.approx(1.5 * 1.5 * 3.0)

    seg = io.load_segmentation(str(tmp_path / "seg.nii.gz"), image.shape)
    assert int((seg.data == 1).sum()) == 25

    out = tmp_path / "out.nii.gz"
    io.save_segmentation(seg, image, str(out))
    reloaded = io.load_segmentation(str(out), image.shape)
    assert np.array_equal(reloaded.data, seg.data)


def test_shape_mismatch_raises(tmp_path):
    nib = pytest.importorskip("nibabel")
    from pkdqc.core import io
    nib.save(nib.Nifti1Image(np.zeros((10, 10, 3), np.uint16), np.eye(4)), str(tmp_path / "s.nii.gz"))
    with pytest.raises(io.LoadError):
        io.load_segmentation(str(tmp_path / "s.nii.gz"), (12, 12, 3))


# ---------------------------------------------------------------- planes / MPR
def test_plane_roundtrip_all_orientations():
    from pkdqc.core.planes import PLANES
    shape = (12, 16, 20)
    data = np.arange(np.prod(shape), dtype=np.uint16).reshape(shape)
    rng = np.random.default_rng(0)
    for plane in PLANES.values():
        for _ in range(50):
            vox = (rng.integers(0, shape[0]), rng.integers(0, shape[1]), rng.integers(0, shape[2]))
            cursor = list(vox)
            v, h = plane.vox_to_disp(cursor, shape)
            back = plane.disp_to_vox(v, h, cursor, shape)
            assert back == tuple(int(x) for x in vox)
            # the displayed pixel equals the volume value at that voxel
            assert plane.slice2d(data, cursor)[v, h] == data[vox]


def test_plane_slice_dimensions():
    from pkdqc.core.planes import PLANES, AXIAL, CORONAL, SAGITTAL
    shape = (12, 16, 20)
    data = np.zeros(shape, dtype=np.uint16)
    cur = [6, 8, 10]
    assert PLANES[AXIAL].slice2d(data, cur).shape == (16, 12)     # (Y, X)
    assert PLANES[CORONAL].slice2d(data, cur).shape == (20, 12)   # (Z, X)
    assert PLANES[SAGITTAL].slice2d(data, cur).shape == (20, 16)  # (Z, Y)


def test_cross_plane_paint_writes_correct_voxels():
    from pkdqc.core.planes import PLANES, SAGITTAL
    from pkdqc.core.commands import StrokeRecorder
    seg = Segmentation(np.zeros((12, 16, 20), dtype=np.uint16))
    plane = PLANES[SAGITTAL]
    cursor = [5, 8, 10]
    # paint a single voxel via the sagittal plane at display (v,h) for a known voxel
    target_vox = (5, 8, 10)
    v, h = plane.vox_to_disp(cursor, seg.data.shape)
    ii, jj, kk = plane.disp_to_vox_arrays(np.array([v]), np.array([h]), cursor, seg.data.shape)
    rec = StrokeRecorder(seg, "paint")
    rec.stamp_voxels(ii, jj, kk, 1)
    cmd = rec.commit()
    assert cmd is not None
    assert seg.data[target_vox] == 1
    assert int((seg.data == 1).sum()) == 1


def test_flood_fill_plane():
    from pkdqc.core.planes import PLANES, CORONAL
    from pkdqc.core import segops
    seg = Segmentation(np.zeros((20, 20, 20), dtype=np.uint16))
    # make a coronal-plane blob at j=10
    seg.data[5:12, 10, 4:14] = 3
    plane = PLANES[CORONAL]
    cursor = [8, 10, 9]
    sl = plane.slice2d(seg.data, cursor)
    vs, hs = np.nonzero(sl == 3)
    from pkdqc.core.label_policy import LabelProtectionPolicy, DrawOver
    cmd = segops.flood_fill_plane(seg, plane, cursor, int(vs[0]), int(hs[0]), 5,
                                  policy=LabelProtectionPolicy(DrawOver.ALL_PERMITTED))
    assert cmd is not None
    History(seg).push(cmd)
    assert int((seg.data == 5).sum()) == 70
    assert int((seg.data == 3).sum()) == 0


# ---------------------------------------------------------------------- lasso
def test_lasso_rasterization_and_plane_add_remove_undo():
    from pkdqc.core.planes import PLANES, AXIAL
    from pkdqc.core import segops
    seg = Segmentation(np.zeros((16, 16, 5), dtype=np.uint16))
    plane = PLANES[AXIAL]
    cursor = [8, 8, 2]
    vertices = [(3, 3), (3, 11), (11, 11), (11, 3)]
    mask = segops.rasterize_lasso((16, 16), vertices)
    assert mask.shape == (16, 16)
    assert mask[5, 5] and not mask[1, 1]

    hist = History(seg)
    add = segops.apply_lasso_plane(seg, plane, cursor, vertices, 2, protect_existing=True)
    assert add is not None
    hist.push(add)
    added = int((seg.data[:, :, 2] == 2).sum())
    assert added == int(mask.sum())
    assert seg.revision == 1 and 2 in seg.edited_slices
    hist.undo()
    assert int((seg.data == 2).sum()) == 0
    hist.redo()
    assert int((seg.data == 2).sum()) == added

    seg.active_id = 2
    remove = segops.apply_lasso_plane(seg, plane, cursor, vertices, 0)
    assert remove is not None
    hist.push(remove)
    assert int((seg.data == 2).sum()) == 0
    hist.undo()
    assert int((seg.data == 2).sum()) == added

    seg.data[5, 5, 2] = 8
    protected_remove = segops.apply_lasso_plane(seg, plane, cursor, vertices, 0, remove_label=2)
    assert protected_remove is not None
    hist.push(protected_remove)
    assert seg.data[5, 5, 2] == 8  # remove affects only the active label


def test_lasso_protect_labels_and_coronal_geometry():
    from pkdqc.core.planes import PLANES, CORONAL
    from pkdqc.core import segops
    seg = Segmentation(np.zeros((12, 12, 12), dtype=np.uint16))
    # The lasso occupies display rows Z=3..8 and columns X=3..8 at Y=6.
    seg.data[5, 6, 5] = 9
    plane = PLANES[CORONAL]
    cursor = [6, 6, 6]
    vertices = [(3, 3), (3, 9), (9, 9), (9, 3)]
    cmd = segops.apply_lasso_plane(seg, plane, cursor, vertices, 2, protect_existing=True)
    assert cmd is not None
    History(seg).push(cmd)
    assert seg.data[5, 6, 5] == 9  # never overwrite a protected label
    assert seg.data[4, 6, 4] == 2  # plane mapping writes X,Y,Z, not axial-only
    assert np.count_nonzero(seg.data[:, 6, :] == 2) > 0


def test_freehand_lasso_contour_and_sagittal_mapping():
    from pkdqc.core.planes import PLANES, SAGITTAL
    from pkdqc.core import segops
    seg = Segmentation(np.zeros((14, 14, 14), dtype=np.uint16))
    # An irregular freehand contour, unlike the former rectangle-like selection.
    contour = [(3, 4), (4, 8), (6, 10), (9, 8), (10, 5), (8, 3), (5, 3)]
    mask = segops.rasterize_lasso((14, 14), contour)
    assert mask[6, 6] and not mask[2, 2]
    cmd = segops.apply_lasso_plane(seg, PLANES[SAGITTAL], [7, 7, 7], contour, 4)
    assert cmd is not None
    History(seg).push(cmd)
    assert np.count_nonzero(seg.data[7, :, :] == 4) == int(mask.sum())


# --------------------------------------------------------------- display aspect
def test_display_aspect_isotropic_is_one():
    from pkdqc.core.planes import display_aspect
    assert display_aspect(1.0, 1.0) == pytest.approx(1.0)


def test_display_aspect_thick_vertical_axis_is_stretched_not_squashed():
    """Regression: a pane whose VERTICAL voxels are thick must be stretched
    vertically, i.e. aspect < 1. The inverted form (7.68) rendered the user's
    24-slice 12mm coronal MRI as a 549x7 line."""
    from pkdqc.core.planes import display_aspect
    a = display_aspect(12.0, 1.5625)     # vertical 12mm, horizontal 1.5625mm
    assert a == pytest.approx(1.5625 / 12.0)
    assert a < 1.0


def test_display_aspect_thick_horizontal_axis():
    from pkdqc.core.planes import display_aspect
    a = display_aspect(1.5625, 12.0)
    assert a == pytest.approx(12.0 / 1.5625)
    assert a > 1.0


def test_display_aspect_rejects_bad_spacing():
    from pkdqc.core.planes import display_aspect
    for bad in [(0.0, 1.0), (1.0, 0.0), (float("nan"), 1.0), (float("inf"), 1.0)]:
        assert display_aspect(*bad) == 1.0


def test_segmentation_affine_mismatch_raises(tmp_path):
    nib = pytest.importorskip("nibabel")
    from pkdqc.core import io
    image_path = tmp_path / "img.nii.gz"
    seg_path = tmp_path / "seg.nii.gz"
    nib.save(nib.Nifti1Image(np.zeros((10, 10, 3), np.float32), np.eye(4)), image_path)
    shifted = np.eye(4); shifted[0, 3] = 5.0
    nib.save(nib.Nifti1Image(np.zeros((10, 10, 3), np.uint16), shifted), seg_path)
    image = io.load_image(str(image_path))
    with pytest.raises(io.LoadError, match="affine"):
        io.load_segmentation(str(seg_path), image.shape, image.affine)


def test_protected_paint_only_targets_background_or_same_label():
    from pkdqc.core.segops import paintable_mask
    labels = np.array([0, 1, 2, 1], dtype=np.uint16)
    assert np.array_equal(paintable_mask(labels, 1, True), [True, True, False, True])
    assert np.array_equal(paintable_mask(labels, 1, False), [True, True, True, True])
    assert np.array_equal(paintable_mask(labels, 0, True), [False, True, True, True])


def test_main_window_references_only_registered_actions():
    """Keep merge conflicts from leaving menu actions without an action object."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("pkdqc/ui/main_window.py").read_text(encoding="utf-8"))
    actions = set()
    referenced = set()

    class ActionVisitor(ast.NodeVisitor):
        def visit_Call(self, node):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_mk"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                actions.add(node.args[0].value)
            self.generic_visit(node)

        def visit_Subscript(self, node):
            value = node.value
            key = node.slice
            if (isinstance(value, ast.Attribute) and value.attr == "act"
                    and isinstance(key, ast.Constant) and isinstance(key.value, str)):
                referenced.add(key.value)
            self.generic_visit(node)

    ActionVisitor().visit(tree)
    # These registries are constructed through loops in _make_actions.
    actions.update({"crosshair", "pan", "brush", "fill", "lasso"})
    actions.update({"grow", "shrink", "islands", "holes", "interpolate"})
    actions.update({"layout_grid", "layout_axial", "layout_coronal", "layout_sagittal", "layout_3d"})

    assert referenced <= actions
