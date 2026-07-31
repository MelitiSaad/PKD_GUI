"""Proof-oriented regression coverage for Round 1A integrity guarantees."""
import numpy as np
import pytest

from pkdqc.core import io, segops
from pkdqc.core.commands import EditCommand, StrokeRecorder, apply_volume
from pkdqc.core.history import History
from pkdqc.core.label_policy import DrawOver, LabelProtectionPolicy
from pkdqc.core.planes import ORDER, PLANES
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.validation import SegmentationValidationError, validated_labels


@pytest.mark.parametrize("bad, message", [
    (np.array([[[-1]]], np.int16), "negative"),
    (np.array([[[1.5]]], np.float32), "fractional"),
    (np.array([[[np.nan]]]), "NaN"),
    (np.array([[[np.inf]]]), "infinite"),
    (np.array([[[-np.inf]]]), "infinite"),
    (np.array([[[65536]]], np.uint32), "maximum"),
    (np.empty((0, 2, 2), np.uint16), "non-empty"),
    (np.zeros((2, 2), np.uint16), "3D"),
    (np.array([[['1']]], dtype=object), "Unsupported"),
])
def test_invalid_source_values_are_rejected_before_conversion(bad, message):
    original = bad.copy()
    with pytest.raises(SegmentationValidationError, match=message):
        validated_labels(bad)
    assert bad.dtype == original.dtype and bad.shape == original.shape
    assert bad.tobytes() == original.tobytes()


@pytest.mark.parametrize("dtype", [np.int8, np.int16, np.int32, np.int64,
                                    np.uint8, np.uint16, np.uint32, np.uint64])
def test_valid_integer_source_dtypes_preserve_ids_exactly(dtype):
    limit = min(65535, int(np.iinfo(dtype).max))
    expected = [0, 1, limit // 2, limit]
    source = np.array(expected, dtype=dtype).reshape(2, 2, 1)
    result = validated_labels(source)
    assert result.dtype == np.uint16
    assert result.ravel().tolist() == expected


def test_failed_nifti_load_preserves_already_open_segmentation(tmp_path):
    nib = pytest.importorskip("nibabel")
    existing = Segmentation(np.array([0, 7], np.uint16).reshape(1, 1, 2))
    before = existing.data.tobytes()
    path = tmp_path / "fractional.nii.gz"
    nib.save(nib.Nifti1Image(np.full((1, 1, 2), 1.25, np.float32), np.eye(4)), path)
    with pytest.raises(io.LoadError, match="fractional"):
        io.load_segmentation(str(path), existing.data.shape)
    assert existing.data.tobytes() == before


def history_state(history):
    return (tuple(history._undo), tuple(history._redo), history._bytes)


class FailingMutation(EditCommand):
    def redo(self, seg):
        seg.data.reshape(-1)[self.flat_idx[0]] = self.new_vals[0]
        raise RuntimeError("injected during mutation")


def test_failure_before_mutation_changes_nothing():
    seg = Segmentation(np.zeros((2, 2, 2), np.uint16)); hist = History(seg)
    before, stacks = seg.data.copy(), history_state(hist)
    with pytest.raises(IndexError):
        hist.push(EditCommand([999], [0], [1], [0]))
    assert np.array_equal(seg.data, before) and history_state(hist) == stacks


def test_failure_during_mutation_rolls_back_data_and_histories():
    seg = Segmentation(np.zeros((2, 2, 2), np.uint16)); hist = History(seg)
    hist.push(EditCommand([1], [0], [2], [0])); hist.undo()  # establish redo state
    before, stacks = seg.data.copy(), history_state(hist)
    with pytest.raises(RuntimeError, match="during mutation"):
        hist.push(FailingMutation([0, 1], [0, 0], [3, 3], [0]))
    assert np.array_equal(seg.data, before) and history_state(hist) == stacks


def test_failure_before_history_insertion_rolls_back_completed_mutation():
    class RejectAppend(list):
        def append(self, value):
            raise RuntimeError("before history insertion")

    seg = Segmentation(np.zeros((2, 2, 2), np.uint16)); hist = History(seg)
    hist._undo = RejectAppend(hist._undo)
    before, stacks = seg.data.copy(), history_state(hist)
    with pytest.raises(RuntimeError, match="before history insertion"):
        hist.push(EditCommand([0], [0], [9], [0]))
    assert np.array_equal(seg.data, before) and history_state(hist) == stacks


def test_failure_during_history_insertion_rolls_back_and_preserves_redo():
    seg = Segmentation(np.zeros((2, 2, 2), np.uint16)); hist = History(seg)
    hist.push(EditCommand([1], [0], [2], [0])); hist.undo()
    before, stacks = seg.data.copy(), history_state(hist)
    hist.on_change = lambda: (_ for _ in ()).throw(RuntimeError("insertion"))
    with pytest.raises(RuntimeError, match="insertion"):
        hist.push(EditCommand([0], [0], [1], [0]))
    assert np.array_equal(seg.data, before) and history_state(hist) == stacks


def test_live_stroke_history_failure_restores_byte_exact_data():
    seg = Segmentation(np.zeros((3, 3, 1), np.uint16)); hist = History(seg)
    rec = StrokeRecorder(seg); rec.stamp_voxels([1], [1], [0], 5); cmd = rec.commit()
    hist.on_change = lambda: (_ for _ in ()).throw(RuntimeError("insertion"))
    with pytest.raises(RuntimeError):
        hist.record_applied(cmd)
    assert seg.data.tobytes() == np.zeros((3, 3, 1), np.uint16).tobytes()
    assert history_state(hist) == ((), (), 0)


def test_successful_command_has_exact_undo_redo_in_all_planes():
    for name in ORDER:
        seg = Segmentation(np.zeros((5, 6, 7), np.uint16)); hist = History(seg)
        plane = PLANES[name]; cursor = [2, 3, 4]
        v, h = plane.vox_to_disp(cursor, seg.data.shape)
        sl = plane.slice2d(seg.data, cursor).copy(); sl[v, h] = 65535
        from pkdqc.core.commands import apply_plane_slice
        hist.push(apply_plane_slice(seg, plane, cursor, sl, name))
        changed = seg.data.copy(); assert changed[tuple(cursor)] == 65535
        hist.undo(); assert not seg.data.any()
        hist.redo(); assert np.array_equal(seg.data, changed)


def test_shared_policy_background_selected_all_hidden_and_locked():
    values = np.array([0, 1, 2, 3], np.uint16)
    bg = LabelProtectionPolicy(DrawOver.BACKGROUND_ONLY, 1, frozenset({3}))
    selected = LabelProtectionPolicy(DrawOver.SELECTED_LABEL, 2, frozenset({3}))
    all_allowed = LabelProtectionPolicy(DrawOver.ALL_PERMITTED, 1, frozenset({3}), False)
    assert bg.writable(values, 1).tolist() == [True, True, False, False]
    assert selected.writable(values, 1).tolist() == [True, True, True, False]
    assert all_allowed.writable(values, 1).tolist() == [True, True, True, False]
    # Visibility is intentionally absent from protection: hidden labels are protected too.
    assert bg.writable(values, 0).tolist() == [False, True, False, False]


def test_cleanup_interpolation_and_morphology_never_overwrite_other_or_locked_labels():
    data = np.zeros((9, 9, 5), np.uint16)
    data[2:7, 2:7, 0] = 1; data[2:7, 2:7, 4] = 1
    data[4, 4, 2] = 2
    seg = Segmentation(data); seg.active_id = 1
    seg.labels.labels[2].locked = True
    hist = History(seg)
    hist.push(segops.interpolate_between(seg, 1, 0, 4))
    assert seg.data[4, 4, 2] == 2
    before_two = (seg.data == 2).copy()
    for builder in (
        lambda: segops.grow(seg, 1), lambda: segops.shrink(seg, 1),
        lambda: segops.fill_holes(seg, 1),
        lambda: segops.remove_islands(seg, 1, min_size=1000),
    ):
        cmd = builder()
        if cmd is not None: hist.push(cmd)
        assert np.array_equal(seg.data == 2, before_two)


def test_lasso_and_fill_obey_background_only_and_selected_erase():
    from pkdqc.core.planes import AXIAL
    data = np.zeros((8, 8, 2), np.uint16); data[3, 3, 1] = 2
    seg = Segmentation(data)
    seg.labels.labels[2].locked = True; seg.active_id = 1; hist = History(seg)
    vertices = [(1, 1), (1, 7), (7, 7), (7, 1)]
    hist.push(segops.apply_lasso_plane(seg, PLANES[AXIAL], [4, 4, 1], vertices, 1))
    assert seg.data[3, 3, 1] == 2 and np.count_nonzero(seg.data == 1) > 0
    # Eraser removes selected label but not locked/other labels.
    hist.push(segops.apply_lasso_plane(seg, PLANES[AXIAL], [4, 4, 1], vertices, 0,
                                       remove_label=1))
    assert seg.data[3, 3, 1] == 2 and np.count_nonzero(seg.data == 1) == 0

    # Flood fill uses the same policy and cannot relabel the locked seed.
    policy = LabelProtectionPolicy(DrawOver.ALL_PERMITTED, 1, frozenset({2}))
    assert segops.flood_fill(seg, 1, 3, 3, 1, policy=policy) is None
    assert seg.data[3, 3, 1] == 2
