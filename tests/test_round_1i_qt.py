"""Real Qt acceptance tests for Intelligent Fill."""
import numpy as np


def test_intelligent_fill_action_preview_apply_cancel_and_layer_scope(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QKeySequence
    from pkdqc.core.segmentation import Segmentation
    from tests.test_round_1h_qt import _case, _close_window
    win = _case(tmp_path, qtbot)
    try:
        assert win.act["intelligent_fill"].shortcut() == QKeySequence()
        image = win.image.data; image[...] = 0; image[1:4, 1:4, 1] = 5
        organ = win.layers.add("organ", Segmentation.empty_like(image.shape), make_active=True)
        cyst = win.layers.add("cyst", Segmentation.empty_like(image.shape)); cyst.segmentation.data[0, 0, 0] = 1
        win._begin_layer_session(organ); win._begin_layer_session(cyst); win._activate_layer(organ.layer_id)
        other = cyst.segmentation.data.copy(); revision = organ.segmentation.revision

        win.act["intelligent_fill"].trigger()
        assert win._ifill_dialog is not None and win._ifill_seed is None
        win._ifill_dialog.lower.setValue(4); win._ifill_dialog.upper.setValue(6)
        win.ortho.seedClicked.emit("axial", 2, 2, 1)
        qtbot.waitUntil(lambda: (win._drain_background() or True) and win._ifill_result is not None, timeout=3000)
        assert win._ifill_result.changed_voxels == 9
        assert organ.segmentation.revision == revision and not organ.dirty
        assert win.ortho.intelligent_fill_preview is not None
        win._ifill_dialog.apply.click()
        assert organ.history.can_undo and organ.dirty and np.array_equal(cyst.segmentation.data, other)
        organ.history.undo(); assert not organ.segmentation.data.any()
        organ.history.redo(); assert int((organ.segmentation.data == 1).sum()) == 9

        win.act["intelligent_fill"].trigger(); win.ortho.seedClicked.emit("coronal", 2, 2, 1)
        win._ifill_dialog.cancel.click()
        assert win._ifill_dialog is None and win.ortho.intelligent_fill_preview is None
    finally:
        _close_window(win, qtbot, monkeypatch)


def test_intelligent_fill_layer_switch_cancels_preview(qtbot, tmp_path, monkeypatch):
    from pkdqc.core.segmentation import Segmentation
    from tests.test_round_1h_qt import _case, _close_window
    win = _case(tmp_path, qtbot)
    try:
        a = win.layers.add("a", Segmentation.empty_like(win.image.shape), make_active=True)
        b = win.layers.add("b", Segmentation.empty_like(win.image.shape))
        win._begin_layer_session(a); win._begin_layer_session(b); win._activate_layer(a.layer_id)
        win.act["intelligent_fill"].trigger(); assert win._ifill_dialog is not None
        win._activate_layer(b.layer_id)
        assert win._ifill_dialog is None and win.ortho.intelligent_fill_preview is None
    finally:
        _close_window(win, qtbot, monkeypatch)
