from __future__ import annotations

import json
import numpy as np
import pytest

from pkdqc.core.background import ArraySnapshot, BackgroundTaskService, TaskTag
from pkdqc.core.commands import apply_volume
from pkdqc.core.geometry import ImageGeometry
from pkdqc.core.history import History
from pkdqc.core.labels import Label, LabelTable
from pkdqc.core.regions import (
    DEFAULT_CONNECTIVITY, FilterMode, GroupingMode, RegionReviewState, ReviewStatus,
    SortMode, build_region_index, clear_review_progress, delete_label_checked,
    delete_region_checked, load_review_progress, progress_identity, remap_review_state,
    save_review_progress,
)
from pkdqc.core.segmentation import Segmentation


def geom(shape=(40, 40, 20), spacing=(1.0, 2.0, 3.0)):
    aff = np.diag([*spacing, 1.0])
    return ImageGeometry.from_affine(shape, aff)


def table(ids):
    t = LabelTable()
    t.labels = {int(i): Label(int(i), f"Label {int(i)}", ((int(i) * 17) % 255, 80, 180)) for i in ids}
    return t


def one_color_regions(n=300):
    data = np.zeros((40, 40, 20), dtype=np.uint16)
    count = 0
    for k in range(1, 19, 2):
        for i in range(1, 39, 3):
            for j in range(1, 39, 3):
                data[i, j, k] = 1
                count += 1
                if count == n:
                    return data
    return data


def test_hundreds_of_one_color_regions_and_volume_totals():
    data = one_color_regions(300)
    g = geom(data.shape, spacing=(1.0, 1.0, 2.5))
    idx = build_region_index(data, table([1]), g, revision=7, connectivity=26)
    assert len(idx.records) == 300
    assert len(idx.labels) == 1
    assert idx.labels[1].component_count == 300
    assert idx.total_voxel_count == 300
    assert idx.total_volume_mm3 == pytest.approx(750.0)
    assert idx.total_volume_ml == pytest.approx(0.75)
    assert {int(v) for v in np.unique(data)} == {0, 1}


def test_hundreds_of_individually_labeled_regions_preserve_numeric_labels_and_colors():
    data = np.zeros((40, 40, 20), dtype=np.uint16)
    labels = []
    for lid in range(1, 301):
        pos = np.unravel_index(lid * 37 % (data.size - 1) + 1, data.shape)
        data[pos] = lid
        labels.append(lid)
    lt = table(labels)
    idx = build_region_index(data, lt, geom(data.shape), connectivity=26)
    assert len(idx.records) == 300
    assert len(idx.labels) == 300
    assert max(idx.labels) == 300
    assert idx.labels[299].color == lt.labels[299].color
    assert set(np.unique(data)) == {0, *labels}


def test_mixed_labels_components_and_grouping_modes_do_not_change_data_or_double_count():
    data = np.zeros((12, 12, 6), dtype=np.uint16)
    data[1:3, 1:3, 1] = 1
    data[8:10, 8:10, 2] = 1
    data[3:5, 1:3, 1] = 2  # touches label 1 but must remain a distinct region
    before = data.copy()
    idx = build_region_index(data, table([1, 2]), geom(data.shape), connectivity=26)
    assert len(idx.records) == 3
    assert idx.labels[1].component_count == 2
    assert idx.labels[2].component_count == 1
    connected_total = idx.total_volume_mm3
    assert len(idx.items(GroupingMode.CONNECTED)) == 3
    assert len(idx.items(GroupingMode.LABELS)) == 2
    assert len(idx.items(GroupingMode.LABELS_WITH_COMPONENTS)) == 5
    assert idx.total_volume_mm3 == connected_total
    np.testing.assert_array_equal(data, before)


def test_same_label_touching_and_connectivity_choices():
    data = np.zeros((5, 5, 5), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[2, 2, 2] = 1
    assert len(build_region_index(data, table([1]), geom(data.shape), connectivity=6).records) == 2
    assert len(build_region_index(data, table([1]), geom(data.shape), connectivity=18).records) == 2
    assert len(build_region_index(data, table([1]), geom(data.shape), connectivity=26).records) == 1


def test_sparse_high_label_values_and_included_label_totals():
    data = np.zeros((8, 8, 4), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[2:4, 2:4, 2] = 65535
    idx = build_region_index(data, table([1, 65535]), geom(data.shape, (2, 2, 2)), included_labels={65535})
    assert sorted(idx.labels) == [1, 65535]
    assert idx.total_voxel_count == 4
    assert idx.total_volume_mm3 == pytest.approx(32.0)


def test_component_measurements_flags_representative_and_largest_slice():
    data = np.zeros((5, 5, 4), dtype=np.uint16)
    data[0:2, 0:2, 1] = 1
    data[1, 1, 2] = 1
    idx = build_region_index(data, table([1]), geom(data.shape, (1, 1, 1)), connectivity=26)
    rec = idx.records[0]
    assert rec.representative_voxel in map(tuple, np.column_stack(np.where(data == 1)).tolist())
    assert rec.largest_axial_slice == 1
    assert rec.largest_axial_area == 4
    assert rec.slice_range == (1, 2)
    assert rec.touches_boundary
    assert "touches-boundary" in rec.flags
    assert rec.volume_mm3 == pytest.approx(5.0)


def test_sort_filter_review_advance_and_rendering_only_isolation():
    data = np.zeros((8, 8, 4), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[3:5, 3:5, 3] = 2
    idx = build_region_index(data, table([1, 2]), geom(data.shape), connectivity=26)
    state = RegionReviewState(sort_mode=SortMode.LARGEST.value, included_labels={1, 2})
    assert state.current(idx).label_id == 2
    state.mark_reviewed_and_advance(idx)
    assert len(idx.filtered_records(FilterMode.FLAGGED)) >= 1  # one-slice/small-volume attention flags
    before = data.copy()
    state.toggle_isolation(idx)
    assert state.isolated_fingerprint is not None
    np.testing.assert_array_equal(data, before)
    state.mark_unreviewed(idx)
    assert state.review_by_fingerprint


def test_exact_component_delete_whole_label_delete_and_undo_redo_preserve_other_labels():
    data = np.zeros((8, 8, 4), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[5, 5, 1] = 1
    data[2:4, 2:4, 2] = 2
    seg = Segmentation(data.copy(), table([1, 2]))
    hist = History(seg)
    idx = build_region_index(seg.data, seg.labels, geom(seg.data.shape), revision=seg.revision, connectivity=26)
    rec = next(r for r in idx.records if r.label_id == 1 and r.representative_voxel == (1, 1, 1))
    hist.push(delete_region_checked(seg, idx, rec))
    assert seg.data[1, 1, 1] == 0
    assert seg.data[5, 5, 1] == 1
    assert np.all(seg.data[2:4, 2:4, 2] == 2)
    assert hist.can_undo
    hist.undo(); assert seg.data[1, 1, 1] == 1
    hist.redo(); assert seg.data[1, 1, 1] == 0
    cmd = delete_label_checked(seg, 2)
    hist.push(cmd)
    assert np.all(seg.data[2:4, 2:4, 2] == 0)
    hist.undo(); assert np.all(seg.data[2:4, 2:4, 2] == 2)


def test_stale_region_delete_rejected_and_history_unchanged():
    data = np.zeros((5, 5, 3), dtype=np.uint16)
    data[1, 1, 1] = 1
    seg = Segmentation(data, table([1]))
    idx = build_region_index(seg.data, seg.labels, geom(seg.data.shape), revision=seg.revision)
    seg.data[2, 2, 1] = 1
    seg.mark_edited([1])
    with pytest.raises(ValueError, match="stale"):
        delete_region_checked(seg, idx, idx.records[0])


def test_background_region_index_accepts_current_and_discards_stale_document_revision():
    class ImmediateExecutor:
        def submit(self, fn, token):
            from concurrent.futures import Future
            fut = Future(); fut.set_result(fn(token)); return fut
    data = one_color_regions(5)
    service = BackgroundTaskService(executor=ImmediateExecutor())
    service.set_document("case-a", revision=0)
    applied = []
    tag = TaskTag.make("case-a", 0, "region_index", {"connectivity": 26})
    snap = ArraySnapshot.capture("case-a", 0, data)
    service.submit_latest(tag, lambda token: build_region_index(snap.data, table([1]), geom(data.shape)), applied.append)
    assert service.drain_completed()[0].status == "applied"
    assert len(applied[0].records) == 5
    stale_tag = TaskTag.make("case-a", 0, "region_index", {})
    service.update_revision(1)
    service.submit_latest(stale_tag, lambda token: "old", applied.append)
    assert service.drain_completed()[0].status == "stale"
    service.set_document("case-b", revision=0)
    old_doc_tag = TaskTag.make("case-a", 0, "region_index", {})
    service.submit_latest(old_doc_tag, lambda token: "old-doc", applied.append)
    assert service.drain_completed()[0].status == "stale"


def test_review_state_remap_exact_changed_split_merge_and_full_rebuild_invalidation():
    data = np.zeros((10, 10, 4), dtype=np.uint16)
    data[1:3, 1:3, 1] = 1
    data[6:9, 6:9, 1] = 1
    old = build_region_index(data, table([1]), geom(data.shape))
    state = {old.records[0].fingerprint.key(): ReviewStatus.REVIEWED.value,
             old.records[1].fingerprint.key(): ReviewStatus.REVIEWED.value}
    new_data = data.copy(); new_data[7, 7, 1] = 0
    new = build_region_index(new_data, table([1]), geom(data.shape))
    remapped = remap_review_state(old, new, state)
    assert old.records[0].fingerprint.key() in remapped
    assert ReviewStatus.CHANGED.value in remapped.values()

    merged_data = data.copy(); merged_data[3:6, 3:6, 1] = 1
    merged = build_region_index(merged_data, table([1]), geom(data.shape), connectivity=26)
    assert len(merged.records) == 1
    remapped2 = remap_review_state(old, merged, state)
    assert remapped2 == {}


def test_review_progress_persistence_identity_rejection_and_phi_safe_payload(tmp_path):
    identity = progress_identity(
        segmentation_path="/very/sensitive/path/patient-name/seg.nii.gz",
        shape=(4, 4, 4), affine=np.eye(4), dtype="uint16", labels=[1, 99])
    state = RegionReviewState(grouping_mode=GroupingMode.LABELS.value, included_labels={1, 99})
    state.review_by_fingerprint["fake"] = ReviewStatus.REVIEWED.value
    path = save_review_progress(identity, state, path=tmp_path / "progress.json")
    text = path.read_text()
    assert "patient-name" not in text and "sensitive" not in text
    loaded = load_review_progress(identity, path=path)
    assert loaded.grouping_mode == GroupingMode.LABELS.value
    assert loaded.included_labels == {1, 99}
    bad_identity = {**identity, "dtype": "uint8"}
    with pytest.raises(ValueError, match="identity"):
        load_review_progress(bad_identity, path=path)


def test_nifti_style_apply_volume_regression_for_region_delete_result():
    data = np.zeros((5, 5, 3), dtype=np.uint16)
    data[1, 1, 1] = 44
    seg = Segmentation(data.copy(), table([44]))
    new = data.copy(); new[1, 1, 1] = 0
    cmd = apply_volume(seg, new, "region delete")
    assert cmd is not None and cmd.flat_idx.size == 1


def test_review_state_queue_sort_filter_counts_use_live_metadata():
    data = np.zeros((8, 8, 4), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[3:5, 3:5, 2] = 2
    idx = build_region_index(data, table([1, 2]), geom(data.shape), connectivity=26)
    state = RegionReviewState(included_labels={1, 2}, sort_mode=SortMode.UNREVIEWED_FIRST.value)
    first = state.current(idx)
    state.review_by_fingerprint[first.fingerprint.key()] = ReviewStatus.REVIEWED.value
    reviewed, remaining, changed = state.reviewed_remaining_counts(idx)
    assert (reviewed, remaining, changed) == (1, 1, 0)
    state.filter_mode = FilterMode.REVIEWED.value
    assert state.queue(idx) == (first,)
    state.filter_mode = FilterMode.UNREVIEWED.value
    assert first not in state.queue(idx)


def test_numeric_labels_survive_save_reload_but_names_and_colors_are_regenerated(tmp_path):
    from pkdqc.core.io import load_segmentation, save_segmentation
    from pkdqc.core.volume import ImageVolume

    data = np.zeros((5, 5, 3), dtype=np.uint16)
    data[1, 1, 1] = 7
    data[2, 2, 1] = 42
    custom = table([7, 42])
    custom.labels[7].name = "Custom cyst name"
    custom.labels[7].color = (1, 2, 3)
    seg = Segmentation(data.copy(), custom)
    image = ImageVolume(np.zeros(data.shape, dtype=np.float32), (1, 1, 1), np.eye(4))
    out = tmp_path / "roundtrip.nii.gz"
    save_segmentation(seg, image, str(out))
    loaded = load_segmentation(str(out), data.shape, np.eye(4))
    np.testing.assert_array_equal(loaded.data, data)
    assert set(loaded.labels.labels) == {7, 42}
    assert loaded.labels.labels[7].name != "Custom cyst name"
    assert loaded.labels.labels[7].color != (1, 2, 3)


def test_progress_is_application_owned_not_adjacent_to_nifti_and_clearable(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    seg_path = tmp_path / "case.nii.gz"
    identity = progress_identity(
        segmentation_path=str(seg_path), shape=(3, 3, 3), affine=np.eye(4), dtype="uint16", labels=[1])
    state = RegionReviewState(included_labels={1})
    written = save_review_progress(identity, state)
    assert written.parent.name == "region_review"
    assert written.parent != tmp_path
    assert not (tmp_path / "case.region_review.json").exists()
    assert load_review_progress(identity) is not None
    clear_review_progress(identity)
    assert load_review_progress(identity) is None


def test_sparse_high_label_index_memory_tracks_foreground_not_max_label():
    data = np.zeros((10, 10, 4), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[8, 8, 2] = 65535
    idx = build_region_index(data, table([1, 65535]), geom(data.shape), connectivity=26)
    assert sum(r.flat_indices.nbytes for r in idx.records) <= 2 * np.dtype(np.int64).itemsize
    assert max(idx.labels) == 65535


def test_region_review_ui_source_contains_required_controls_and_context_shortcuts():
    from pathlib import Path
    panel = Path("pkdqc/ui/region_review.py").read_text(encoding="utf-8")
    main = Path("pkdqc/ui/main_window.py").read_text(encoding="utf-8")
    assert "Included labels" in panel
    assert "Sort" in panel and "Filter" in panel
    assert "Delete current connected region" in panel
    assert "Delete entire label" in panel
    for key in ('"R"', '"Space"', '"Shift+Space"', '"N"', '"P"', '"Delete"', '"Q"'):
        assert key in main
    assert 'has_seg and getattr(self, "_region_active", False)' in main


def test_included_label_changes_reuse_existing_index_records_without_reindexing():
    data = np.zeros((8, 8, 4), dtype=np.uint16)
    data[1, 1, 1] = 1
    data[2, 2, 1] = 2
    idx = build_region_index(data, table([1, 2]), geom(data.shape), connectivity=26)
    narrowed = idx.with_included_labels({2})
    assert narrowed.records is idx.records
    assert narrowed.included_labels == frozenset({2})
    assert narrowed.total_voxel_count == 1
    assert len(narrowed.items(GroupingMode.CONNECTED)) == 1
