"""Real Qt acceptance coverage for Round 1H (run with QT_QPA_PLATFORM=offscreen)."""
import os
from contextlib import contextmanager
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


@contextmanager
def _choose_button(monkeypatch, text, *, title=None):
    """Answer exactly one expected modal dialog, then restore QMessageBox.exec."""
    from PySide6.QtWidgets import QMessageBox, QPushButton
    calls = []
    with monkeypatch.context() as scoped:
        def execute(box):
            buttons = {button.text(): button for button in box.findChildren(QPushButton)}
            actual_title = box.windowTitle()
            assert not calls, f"Unexpected extra QMessageBox: {actual_title!r}"
            assert title is None or actual_title == title
            assert text in buttons, (
                f"Expected QMessageBox button {text!r}, got {sorted(buttons)!r} "
                f"for {actual_title!r}"
            )
            calls.append(actual_title)
            buttons[text].click()
            return 0
        scoped.setattr(QMessageBox, "exec", execute)
        yield
    assert len(calls) == 1, f"Expected one QMessageBox for {text!r}, got {len(calls)}"


def _close_window(win, qtbot, monkeypatch):
    """Exercise the real close guard when needed and finish all UI services."""
    if win.layers.dirty_layers:
        with _choose_button(monkeypatch, "Discard All", title="Unsaved segmentation layers"):
            assert win.close()
    else:
        assert win.close()
    qtbot.waitUntil(lambda: not win.isVisible())
    assert win.background.closed


def test_real_layers_dock_add_switch_render_edit_and_history(qtbot, tmp_path, monkeypatch):
    from pkdqc.core import commands
    from pkdqc.core.segmentation import Segmentation
    Qt, QTest, _button, _line, _window = _qt(); win = _case(tmp_path, qtbot)
    try:
        assert len(win.layers) == 0 and win.layers_panel.list.count() == 0
        organs = Segmentation(np.ones(win.image.shape, np.uint16))
        win._integrate_loaded_seg(organs, str(tmp_path / "organs.nii.gz"))
        first = win.layers.active; assert len(win.layers) == 1 and first.segmentation is organs
        cysts = Segmentation(np.ones(win.image.shape, np.uint16))
        with _choose_button(monkeypatch, "Add as Another Layer", title="Load segmentation"):
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
    finally:
        _close_window(win, qtbot, monkeypatch)


def test_real_global_s_restores_visibility_and_respects_text_focus(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication
    from pkdqc.core.segmentation import Segmentation
    Qt, QTest, _button, QLineEdit, _window = _qt(); win = _case(tmp_path, qtbot)
    try:
        a = win.layers.add("a", Segmentation.empty_like(win.image.shape), visible=True, make_active=True)
        b = win.layers.add("b", Segmentation.empty_like(win.image.shape), visible=False)
        win._begin_layer_session(a); win._begin_layer_session(b); win._activate_layer(a.layer_id)
        action = win.act["toggle_segmentations"]
        assert action.shortcut() == QKeySequence("S")
        assert action.isEnabled()
        assert action.shortcutContext() == Qt.ShortcutContext.WindowShortcut

        # QMainWindow itself is not a reliable focus target under the offscreen
        # platform.  Activate the top-level window, then deliver the real key
        # event to a visible, non-editor child in that window.
        win.raise_(); win.activateWindow()
        qtbot.waitUntil(lambda: QApplication.activeWindow() is win)
        win.layers_panel.list.setFocus(Qt.FocusReason.OtherFocusReason)
        qtbot.waitUntil(lambda: win.layers_panel.list.hasFocus())
        QTest.keyClick(win.layers_panel.list, Qt.Key.Key_S)
        qtbot.waitUntil(lambda: not win.layers.global_overlay_visible)
        QTest.keyClick(win.layers_panel.list, Qt.Key.Key_S)
        qtbot.waitUntil(lambda: win.layers.global_overlay_visible)
        assert [a.visible, b.visible] == [True, False]
        editor = QLineEdit(win); editor.show(); editor.setFocus(); qtbot.waitUntil(lambda: editor.hasFocus())
        QTest.keyClicks(editor, "S"); assert editor.text() == "S" and win.layers.global_overlay_visible
    finally:
        _close_window(win, qtbot, monkeypatch)


def test_real_active_save_save_all_recovery_and_stale_identity(qtbot, tmp_path, monkeypatch):
    from pkdqc.core.segmentation import Segmentation
    from pkdqc.core.background import TaskTag
    from pkdqc.ui import main_window as module
    win = _case(tmp_path, qtbot)
    try:
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
    finally:
        _close_window(win, qtbot, monkeypatch)
