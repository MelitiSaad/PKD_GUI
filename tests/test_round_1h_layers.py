import numpy as np
import pytest

from pkdqc.core import commands
from pkdqc.core.layers import SegmentationLayers
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume
from pkdqc.core.shortcuts import build_command_registry, migrate_shortcuts


def image(shape=(8, 9, 4)):
    return ImageVolume(np.zeros(shape, np.float32), (1, 1, 1), np.eye(4))


def test_independent_label_namespaces_history_and_rendering():
    case = SegmentationLayers(image())
    a = case.add("organs", Segmentation(np.ones(case.image.shape, np.uint16)), path="organs.nii.gz")
    b = case.add("cysts", Segmentation(np.ones(case.image.shape, np.uint16)), path="cysts.nii.gz", make_active=True)
    original = b.segmentation.data.copy()
    new = a.segmentation.data.copy(); new[0, 0, 0] = 0
    a.history.push(commands.apply_volume(a.segmentation, new, "organ edit"))
    assert np.array_equal(b.segmentation.data, original)
    assert a.dirty and not b.dirty and a.history.can_undo and not b.history.can_undo
    case.set_active(a.layer_id); a.history.undo()
    assert np.all(a.segmentation.data == 1)
    case.set_visible(a.layer_id, False); case.set_opacity(b.layer_id, .8)
    case.move_down(b.layer_id)
    assert [x.layer_id for x in case] == [b.layer_id, a.layer_id]
    assert case.rendering_layers()[0].opacity == .8
    before = [x.visible for x in case.rendering_layers()]
    case.toggle_overlays(); assert not any(x.visible for x in case.rendering_layers())
    case.toggle_overlays(); assert [x.visible for x in case.rendering_layers()] == before


def test_blank_validation_replacement_and_stale_task_identity():
    case = SegmentationLayers(image())
    blank = case.add_blank(make_active=True)
    assert not blank.dirty and blank.path is None and blank.never_saved
    with pytest.raises(ValueError): case.add("bad", Segmentation.empty_like((2, 2, 2)))
    assert len(case) == 1 and case.active is blank
    with pytest.raises(ValueError): case.replace_active("bad", Segmentation.empty_like(case.image.shape), affine=np.diag([2, 1, 1, 1]))
    assert case.active is blank
    tag = (case.case_id, blank.layer_id, blank.segmentation.revision)
    assert case.accepts_task(*tag)
    case.remove(blank.layer_id)
    assert not case.accepts_task(*tag)


def test_save_and_save_all_commit_only_the_successful_layer(tmp_path):
    case = SegmentationLayers(image())
    a = case.add_blank("a", make_active=True); b = case.add_blank("b")
    a.segmentation.mark_edited([0]); b.segmentation.mark_edited([1])
    writes = []
    def writer(seg, image_, path): writes.append((path, seg.data.copy()))
    paths = {a.layer_id: str(tmp_path / "a.nii.gz"), b.layer_id: str(tmp_path / "b.nii.gz")}
    assert case.save_layer(a.layer_id, writer, lambda layer: paths[layer.layer_id])
    assert not a.dirty and b.dirty and b.path is None
    assert case.save_all(writer, lambda layer: paths[layer.layer_id])
    assert not case.dirty and [x[0] for x in writes] == [paths[a.layer_id], paths[b.layer_id]]


def test_save_failure_is_transactional_and_save_all_stops(tmp_path):
    case = SegmentationLayers(image()); a = case.add_blank("a"); b = case.add_blank("b")
    a.segmentation.mark_edited([0]); b.segmentation.mark_edited([0])
    def fail(seg, image_, path): raise OSError("disk full")
    with pytest.raises(OSError): case.save_layer(a.layer_id, fail, lambda _: str(tmp_path / "a.nii.gz"))
    assert a.path is None and a.dirty and b.dirty
    assert not case.save_all(lambda *args: None, lambda layer: None)
    assert a.dirty and b.dirty


def test_new_s_shortcut_yields_to_an_existing_customization():
    registry = build_command_registry([], [])
    assert migrate_shortcuts({}, registry)["toggle_segmentations"] == "S"
    assert migrate_shortcuts({"contrast": "S"}, registry)["toggle_segmentations"] == ""
    assert migrate_shortcuts({"toggle_segmentations": ""}, registry)["toggle_segmentations"] == ""
