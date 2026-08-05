from pathlib import Path
import ast

import numpy as np
import pytest

from pkdqc.core import commands, io
from pkdqc.core.document import Disposition, SegmentationDocument
from pkdqc.core.history import History
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume


@pytest.fixture
def image(tmp_path):
    return ImageVolume(np.zeros((3, 4, 5), np.float32), (1.2, 2.3, 3.4),
                       np.diag([1.2, 2.3, 3.4, 1]), str(tmp_path / "image.nii.gz"))


def edit(seg, history):
    changed = seg.data.copy()
    changed[1, 2, 3] = 7
    history.push(commands.apply_volume(seg, changed, "test edit"))


def test_blank_geometry_clean_then_edit_dirty(image):
    doc = SegmentationDocument.blank(image)
    assert doc.has_image and doc.has_segmentation
    assert doc.segmentation_path is None and doc.never_saved and not doc.dirty
    assert doc.segmentation.data.shape == image.shape
    assert np.all(doc.segmentation.data == 0)
    edit(doc.segmentation, History(doc.segmentation))
    assert doc.dirty


def test_save_current_path_overwrites_and_clears_dirty(image, tmp_path):
    path = tmp_path / "existing.nii.gz"
    path.write_bytes(b"old")
    seg = Segmentation.empty_like(image.shape)
    doc = SegmentationDocument.loaded(image, seg, str(path))
    history = History(seg); edit(seg, history)
    before_revision = seg.revision
    assert doc.save(io.save_segmentation)
    assert doc.segmentation_path == str(path)
    assert doc.saved_revision == before_revision and not doc.dirty
    loaded = io.load_segmentation(str(path), image.shape, image.affine)
    np.testing.assert_array_equal(loaded.data, seg.data)


@pytest.mark.parametrize("name", ["kidney_QC.nii", "kidney_quality_checked.nii.gz",
                                   "anything.nii.gz"])
def test_save_as_preserves_selected_name_and_future_save(image, tmp_path, name):
    seg = Segmentation.empty_like(image.shape)
    doc = SegmentationDocument.blank(image)
    path = tmp_path / name
    assert doc.save_as(io.save_segmentation, lambda: str(path), lambda _p: True)
    assert path.exists() and doc.segmentation_path == str(path)
    assert not Path(str(path) + ".nii.gz").exists()
    edit(seg := doc.segmentation, History(seg))
    assert doc.save(io.save_segmentation)
    assert io.load_segmentation(str(path), image.shape, image.affine).data[1, 2, 3] == 7


def test_cancel_and_rejected_overwrite_change_nothing(image, tmp_path):
    doc = SegmentationDocument.blank(image)
    edit(doc.segmentation, History(doc.segmentation))
    snapshot = doc.segmentation.data.copy(), doc.segmentation.revision, doc.dirty
    assert not doc.save_as(io.save_segmentation, lambda: None)
    existing = tmp_path / "exists.nii"; existing.write_bytes(b"old")
    assert not doc.save_as(io.save_segmentation, lambda: str(existing), lambda _p: False)
    np.testing.assert_array_equal(doc.segmentation.data, snapshot[0])
    assert (doc.segmentation_path, doc.segmentation.revision, doc.dirty) == (None, snapshot[1], snapshot[2])
    assert existing.read_bytes() == b"old"


def test_failed_save_preserves_all_document_state(image, tmp_path):
    old = tmp_path / "old.nii.gz"
    doc = SegmentationDocument.loaded(image, Segmentation.empty_like(image.shape), str(old))
    history = History(doc.segmentation); edit(doc.segmentation, history)
    state = doc.segmentation_path, doc.saved_revision, doc.segmentation.revision, doc.dirty
    def fail(*_args):
        raise OSError("disk full")
    with pytest.raises(OSError, match="disk full"):
        doc.save_as(fail, lambda: str(tmp_path / "new.nii.gz"))
    assert (doc.segmentation_path, doc.saved_revision,
            doc.segmentation.revision, doc.dirty) == state
    assert history.can_undo


def test_missing_state_and_unsupported_extension(image, tmp_path):
    assert not SegmentationDocument().save(io.save_segmentation)
    doc = SegmentationDocument.blank(image)
    with pytest.raises(ValueError, match="Unsupported"):
        doc.save_as(io.save_segmentation, lambda: str(tmp_path / "mask.mha"))
    assert doc.segmentation_path is None


def test_undo_and_redo_track_saved_revision(image, tmp_path):
    doc = SegmentationDocument.blank(image); seg = doc.segmentation; history = History(seg)
    edit(seg, history)
    doc.save_as(io.save_segmentation, lambda: str(tmp_path / "saved.nii.gz"))
    saved = doc.saved_revision
    changed = seg.data.copy(); changed[0, 0, 0] = 2
    history.push(commands.apply_volume(seg, changed, "second"))
    assert doc.dirty
    history.undo()
    assert seg.revision == saved and not doc.dirty
    history.redo()
    assert seg.revision != saved and doc.dirty


@pytest.mark.parametrize("choice,save_result,allowed,discarded", [
    (Disposition.SAVE, True, True, False),
    (Disposition.SAVE, False, False, False),
    (Disposition.DISCARD, False, True, True),
    (Disposition.CANCEL, True, False, False),
])
def test_central_guard_save_discard_cancel(image, choice, save_result, allowed, discarded):
    doc = SegmentationDocument.blank(image); edit(doc.segmentation, History(doc.segmentation))
    calls = []
    result = doc.guard(lambda: choice, lambda: save_result, lambda: calls.append("discard"))
    assert result is allowed
    assert bool(calls) is discarded
    assert doc.segmentation.data[1, 2, 3] == 7  # guard never mutates the case


def test_clean_guard_does_not_prompt(image):
    doc = SegmentationDocument.blank(image)
    doc.guard(lambda: pytest.fail("prompted"), lambda: False, lambda: None)


def test_atomic_writer_failure_keeps_destination_and_removes_temp(image, tmp_path, monkeypatch):
    path = tmp_path / "mask.nii.gz"; path.write_bytes(b"original")
    def fail(_src, _dst):
        raise PermissionError("replace denied")
    monkeypatch.setattr(io.os, "replace", fail)
    with pytest.raises(PermissionError):
        io.save_segmentation(Segmentation.empty_like(image.shape), image, str(path))
    assert path.read_bytes() == b"original"
    assert not (tmp_path / "mask.saving.nii.gz").exists()


def test_ui_save_actions_shortcut_enablement_and_indicator(image, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
        from pkdqc.ui.main_window import MainWindow
    except ImportError as exc:
        pytest.skip(f"Qt runtime unavailable: {exc}")
    app = QApplication.instance() or QApplication([])
    win = MainWindow(enable_3d=False)
    assert win.act["save"].shortcut().toString() == "Ctrl+S"
    assert not win.act["save"].isEnabled() and not win.act["save_as"].isEnabled()
    Path(image.path).write_bytes(b"test image")
    win._set_case(image, Segmentation.empty_like(image.shape), None)
    assert win.act["save"].isEnabled() and win.act["save_as"].isEnabled()
    assert "Untitled segmentation" in win.lbl_document.text()
    edit(win.seg, win.history); win._mark_dirty()
    assert win.lbl_document.text().endswith("*")
    assert win.windowTitle().startswith("*")
    win.document.saved_revision = win.seg.revision
    win.session.mark_clean(); win._autosave_timer.stop(); win._idle_timer.stop(); win.close()
    app.processEvents()


def test_ui_save_and_save_as_are_wired_without_importing_qt():
    source = Path("pkdqc/ui/main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "Ctrl+S" in Path("pkdqc/core/shortcuts.py").read_text(encoding="utf-8")
    assert 'self.act["save"].triggered.connect(self._save)' in source
    assert 'self.act["save_as"].triggered.connect(self._save_as)' in source
    assert 'for aid in ("load_seg", "save", "save_as", "new_seg")' in source
    assert any(isinstance(node, ast.FunctionDef) and node.name == "_sync_document_state"
               for node in ast.walk(tree))
