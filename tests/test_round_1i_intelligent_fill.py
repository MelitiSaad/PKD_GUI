import numpy as np
import pytest

from pkdqc.core.background import CancellationToken
from pkdqc.core.history import History
from pkdqc.core.intelligent_fill import (IntelligentFillRequest, command_for_preview,
                                         compute_preview)
from pkdqc.core.label_policy import DrawOver, LabelProtectionPolicy
from pkdqc.core.layers import SegmentationLayers
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume


def request(image, seg=None, **kwargs):
    seg = np.zeros(image.shape, np.uint16) if seg is None else seg
    defaults = dict(seed=(2, 2, 1), target_label=1, lower=4, upper=6,
                    scope="axial", connectivity=4,
                    policy=LabelProtectionPolicy(DrawOver.BACKGROUND_ONLY),
                    case_id="case", layer_id="layer", source_revision=0)
    defaults.update(kwargs)
    return IntelligentFillRequest(image, seg, **defaults)


def test_2d_connected_threshold_is_inclusive_and_disconnected():
    image = np.zeros((6, 6, 3), float)
    image[1:4, 1:4, 1] = 5; image[1, 1, 1] = 4; image[3, 3, 1] = 6
    image[5, 5, 1] = 5; before = image.copy()
    result = compute_preview(request(image))
    assert result.status == "success" and result.changed_voxels == 9
    assert result.bounding_box == ((1, 1, 1), (3, 3, 1))
    assert np.array_equal(image, before)


@pytest.mark.parametrize("connectivity,offset,expected", [
    (6, (1, 0, 0), 2), (6, (1, 1, 0), 1),
    (18, (1, 1, 0), 2), (18, (1, 1, 1), 1),
    (26, (1, 1, 1), 2),
])
def test_3d_connectivity(connectivity, offset, expected):
    image = np.zeros((5, 5, 5), float); seed = (2, 2, 2); image[seed] = 5
    image[tuple(seed[a] + offset[a] for a in range(3))] = 5
    result = compute_preview(request(image, seed=seed, scope="3d", connectivity=connectivity))
    assert result.changed_voxels == expected


@pytest.mark.parametrize("scope,seed,other", [
    ("axial", (2, 2, 1), (2, 2, 2)),
    ("coronal", (2, 1, 2), (2, 2, 2)),
    ("sagittal", (1, 2, 2), (2, 2, 2)),
])
def test_plane_scope_stays_on_seed_slice(scope, seed, other):
    image = np.zeros((4, 4, 4), float); image[seed] = image[other] = 5
    result = compute_preview(request(image, seed=seed, scope=scope, connectivity=4))
    assert result.changed_voxels == 1


def test_nan_inf_out_of_range_and_invalid_inputs():
    image = np.zeros((5, 5, 3), float); image[2, 2, 1] = 5
    image[2, 3, 1] = np.nan; image[2, 1, 1] = np.inf
    assert compute_preview(request(image)).changed_voxels == 1
    assert compute_preview(request(image, lower=6, upper=7)).status == "rejected"
    image[2, 2, 1] = np.nan
    assert compute_preview(request(image)).status == "rejected"
    with pytest.raises(ValueError): compute_preview(request(image, lower=8, upper=7))
    with pytest.raises(ValueError): compute_preview(request(image, seed=(-1, 0, 0)))
    with pytest.raises(ValueError): compute_preview(request(image, connectivity=6))


def test_protected_barrier_counts_conflict_and_existing_active_voxels():
    image = np.zeros((7, 3, 1), float); image[:, 1, 0] = 5
    seg = np.zeros(image.shape, np.uint16); seg[1, 1, 0] = 1; seg[3, 1, 0] = 2
    result = compute_preview(request(image, seg, seed=(1, 1, 0)))
    assert result.changed_voxels == 2 and result.already_active_voxels == 1
    assert result.protected_voxels == 1
    assert np.ravel_multi_index((3, 1, 0), seg.shape) not in set(result.flat_indices.tolist())


def test_cancellation_returns_no_partial_result():
    token = CancellationToken(); token.cancel()
    result = compute_preview(request(np.full((40, 40, 10), 5.0), scope="3d", connectivity=26), token)
    assert result.status == "cancelled" and result.flat_indices.size == 0


def test_sparse_high_label_ids_do_not_affect_region_allocation():
    image = np.zeros((8, 8, 2), float); image[2:5, 2:5, 1] = 5
    seg = np.zeros(image.shape, np.uint16); seg[7, 7, 1] = 65535
    result = compute_preview(request(image, seg))
    assert result.changed_voxels == 9 and result.flat_indices.nbytes == 9 * 8


def test_preview_is_non_mutating_and_apply_is_exactly_undoable():
    image = np.zeros((6, 6, 3), float); image[1:4, 1:4, 1] = 5
    seg = Segmentation(np.zeros(image.shape, np.uint16)); history = History(seg)
    before = seg.data.copy(); result = compute_preview(request(image, seg.data))
    assert np.array_equal(seg.data, before) and seg.revision == 0 and not seg.dirty and not history.can_undo
    cmd = command_for_preview(seg, result, case_id="case", layer_id="layer")
    history.push(cmd); applied = seg.data.copy()
    assert history.can_undo and seg.revision == 1 and seg.dirty
    history.undo(); assert np.array_equal(seg.data, before)
    history.redo(); assert np.array_equal(seg.data, applied)


def test_layer_and_revision_staleness_and_other_layer_isolation():
    image = np.zeros((6, 6, 3), float); image[1:4, 1:4, 1] = 5
    volume = ImageVolume(image, (1, 1, 1), np.eye(4)); layers = SegmentationLayers(volume, case_id="case")
    organ = layers.add("organ", Segmentation.empty_like(image.shape), layer_id="organ")
    cyst = layers.add("cyst", Segmentation.empty_like(image.shape), layer_id="cyst")
    cyst.segmentation.data[0, 0, 0] = 1; other = cyst.segmentation.data.copy()
    result = compute_preview(request(image, organ.segmentation.data, layer_id="organ"))
    with pytest.raises(ValueError): command_for_preview(organ.segmentation, result, case_id="wrong", layer_id="organ")
    with pytest.raises(ValueError): command_for_preview(organ.segmentation, result, case_id="case", layer_id="cyst")
    organ.history.push(command_for_preview(organ.segmentation, result, case_id="case", layer_id="organ"))
    assert np.array_equal(cyst.segmentation.data, other)
    with pytest.raises(ValueError): command_for_preview(organ.segmentation, result, case_id="case", layer_id="organ")
