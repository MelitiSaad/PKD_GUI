"""Real Qt acceptance coverage for Round 1H (run with QT_QPA_PLATFORM=offscreen)."""
import os
import numpy as np
import pytest


def _qt():
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QPushButton, QLineEdit
        from pkdqc.ui.main_window import MainWindow
    except ImportError as exc:
        pytest.skip(f"Qt runtime unavailable: {exc}")
    return Qt, QTest, QPushButton, QLineEdit, MainWindow


def _case(tmp_path, qtbot):
    import nibabel as nib
    from pkdqc.core import io
    Qt, QTest, QPushButton, QLineEdit, MainWindow = _qt()
    image_path = tmp_path / "image.nii.gz"
    nib.save(nib.Nifti1Image(np.arange(8 * 9 * 4, dtype=np.float32).reshape(8, 9, 4), np.eye(4)), image_path)
    win = MainWindow(enable_3d=False); qtbot.addWidget(win); win.show()
    win._set_image_only(io.load_image(str(image_path)))
    return win


def _choose_button(monkeypatch, text):
    from PySide6.QtWidgets import QMessageBox, QPushButton
    def execute(box):
        button = next(b for b in box.findChildren(QPushButton) if b.text() == text)
        button.click(); return 0
    monkeypatch.setattr(QMessageBox, "exec", execute)


def test_real_layers_dock_add_switch_render_edit_and_history(qtbot, tmp_path, monkeypatch):
    from pkdqc.core import commands
    from pkdqc.core.segmentation import Segmentation
    Qt, QTest, _button, _line, _window = _qt(); win = _case(tmp_path, qtbot)
    assert len(win.layers) == 0 and win.layers_panel.list.count() == 0
    organs = Segmentation(np.ones(win.image.shape, np.uint16))
    win._integrate_loaded_seg(organs, str(tmp_path / "organs.nii.gz"))
    first = win.layers.active; assert len(win.layers) == 1 and first.segmentation is organs
    cysts = Segmentation(np.ones(win.image.shape, np.uint16))
    _choose_button(monkeypatch, "Add as Another Layer")
    win._integrate_loaded_seg(cysts, str(tmp_path / "cysts.nii.gz"))
    second = win.layers.active; assert len(win.layers) == 2 and second is not first
    assert int(first.segmentation.data[0, 0, 0]) == int(second.segmentation.data[0, 0, 0]) == 1
    qtbot.waitUntil(lambda: all(len(p.layer_items) == 1 for p in win.ortho.planes.values()))

    # Select the first row through the real dock, then edit only that layer.
    win.layers_panel.list.setCurrentRow(0); qtbot.waitUntil(lambda: win.layers.active is first)
    untouched = second.segmentation.data.copy(); changed = first.segmentation.data.copy(); changed[0, 0, 0] = 0
    first.history.push(commands.apply_volume(first.segmentation, changed, "acceptance edit")); win._mark_dirty()
    assert np.array_equal(second.segmentation.data, untouched)
    win.act["undo"].trigger(); assert int(first.segmentation.data[0, 0, 0]) == 1
    win.act["redo"].trigger(); assert int(first.segmentation.data[0, 0, 0]) == 0
    win.layers_panel.list.setCurrentRow(1); assert win.history is second.history and not second.history.can_undo

    # Visibility, opacity and ordering are driven by real widgets/signals.
    item = win.layers_panel.list.item(1); item.setCheckState(Qt.CheckState.Unchecked)
    assert not second.visible
    win.layers_panel.opacity.setValue(73); assert second.opacity == pytest.approx(.73)
    before = [x.layer_id for x in win.layers]; win.layers_panel.down.click()
    assert [x.layer_id for x in win.layers] != before


def test_real_global_s_restores_visibility_and_respects_text_focus(qtbot, tmp_path):
    from pkdqc.core.segmentation import Segmentation
    Qt, QTest, _button, QLineEdit, _window = _qt(); win = _case(tmp_path, qtbot)
    a = win.layers.add("a", Segmentation.empty_like(win.image.shape), visible=True, make_active=True)
    b = win.layers.add("b", Segmentation.empty_like(win.image.shape), visible=False)
    win._begin_layer_session(a); win._begin_layer_session(b); win._activate_layer(a.layer_id)
    win.activateWindow(); win.setFocus(); QTest.keyClick(win, Qt.Key.Key_S)
    qtbot.waitUntil(lambda: not win.layers.global_overlay_visible)
    QTest.keyClick(win, Qt.Key.Key_S); qtbot.waitUntil(lambda: win.layers.global_overlay_visible)
    assert [a.visible, b.visible] == [True, False]
    editor = QLineEdit(win); editor.show(); editor.setFocus(); qtbot.waitUntil(lambda: editor.hasFocus())
    QTest.keyClicks(editor, "S"); assert editor.text() == "S" and win.layers.global_overlay_visible


def test_real_active_save_save_all_recovery_and_stale_identity(qtbot, tmp_path, monkeypatch):
    from pkdqc.core.segmentation import Segmentation
    from pkdqc.core.background import TaskTag
    from pkdqc.ui import main_window as module
    win = _case(tmp_path, qtbot)
    a = win.layers.add("a", Segmentation.empty_like(win.image.shape), make_active=True)
    b = win.layers.add("b", Segmentation.empty_like(win.image.shape))
    win._begin_layer_session(a); win._begin_layer_session(b); win._activate_layer(a.layer_id)
    a.segmentation.mark_edited([0]); b.segmentation.mark_edited([1]); win._refresh_layers()
    outputs = {a.layer_id: str(tmp_path / "a.nii.gz"), b.layer_id: str(tmp_path / "b.nii.gz")}
    monkeypatch.setattr(win, "_choose_save_path_for", lambda layer: outputs[layer.layer_id])
    monkeypatch.setattr(win, "_choose_save_path", lambda: outputs[win.layers.active_layer_id])
    writes = []
    monkeypatch.setattr(module.io, "save_segmentation", lambda seg, image, path: writes.append((path, seg.data.copy())))
    assert win._save_impl(False) and not a.dirty and b.dirty
    assert b.layer_id in win._layer_sessions and a.layer_id not in win._layer_sessions
    assert win._save_all() and not b.dirty and len(writes) == 2
    win.background.update_layer_revision(b.layer_id, b.segmentation.revision)
    assert win.background.stale_reason(TaskTag.make(win._case_id, b.segmentation.revision + 1,
                                                    "volumetry", layer_id=b.layer_id)) == "revision changed"
