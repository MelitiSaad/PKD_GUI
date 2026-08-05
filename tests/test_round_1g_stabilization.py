import threading
import time

import numpy as np
import pytest

from pkdqc.core.background import BackgroundTaskService, TaskTag
from pkdqc.core.regions import GroupingMode, RegionReviewState, build_region_index, remap_review_state
from pkdqc.core.shortcuts import RECOMMENDED_DEFAULTS, build_command_registry, migrate_shortcuts, shortcut_conflicts
from pkdqc.core.geometry import ImageGeometry
from pkdqc.core.labels import LabelTable
TOOLS = [("crosshair", "Crosshair", "crosshair", "V"), ("pan", "Pan", "navigate", "H"), ("brush", "Brush", "brush", "B"), ("fill", "Fill", "fill", "F"), ("lasso", "Lasso", "lasso", "L")]
OPERATIONS = [("grow", "Grow", "grow", "G"), ("shrink", "Shrink", "shrink", "Shift+G"), ("islands", "Remove islands", "islands", "K"), ("holes", "Fill holes", "holes", "J"), ("interpolate", "Interpolate slices", "interpolate", "I")]


def _geom(shape):
    return ImageGeometry.from_affine(shape, np.eye(4), spacing=(1, 1, 1))


def test_minimal_recommended_shortcut_defaults_and_registry_complete():
    reg = build_command_registry(TOOLS, OPERATIONS)
    assigned = {aid: spec.default for aid, spec in reg.items() if spec.default}
    assert assigned == RECOMMENDED_DEFAULTS
    for aid in ["region_next", "region_delete", "layout_grid", "brush_plus", "grow"]:
        assert aid in reg
        assert reg[aid].default == ""
        assert reg[aid].category


def test_shortcut_assign_clear_persist_conflict_reset_and_migration():
    reg = build_command_registry(TOOLS, OPERATIONS)
    migrated = migrate_shortcuts({"grow": "G", "open_image": "Alt+O", "unknown": "X"}, reg)
    assert migrated["grow"] == "G"
    assert migrated["open_image"] == "Alt+O"
    assert "unknown" not in migrated
    migrated["grow"] = ""
    assert migrated["grow"] == ""
    migrated["save"] = "Alt+O"
    assert shortcut_conflicts(migrated, reg)["alt+o"] == ["open_image", "save"]
    reset = {aid: spec.default for aid, spec in reg.items()}
    assert {aid: key for aid, key in reset.items() if key} == RECOMMENDED_DEFAULTS


def test_real_qaction_shortcuts_menu_tooltips_and_text_focus():
    try:
        from PySide6.QtGui import QKeySequence
        from PySide6.QtWidgets import QApplication, QLineEdit
        from pkdqc.ui.main_window import MainWindow
    except ImportError as exc:
        pytest.skip(f"Qt unavailable: {exc}")
    app = QApplication.instance() or QApplication([])
    win = MainWindow(enable_3d=False)
    assert win.act["open_image"].shortcut() == QKeySequence("Ctrl+O")
    assert win.act["grow"].shortcut().isEmpty()
    win.act["grow"].setShortcut(QKeySequence("Alt+G")); win._refresh_action_text("grow")
    assert "Alt+G" in win.act["grow"].toolTip()
    editor = QLineEdit(win); editor.show(); editor.setFocus()
    assert QApplication.focusWidget() is editor


def test_region_review_grouping_modes_have_distinct_navigation():
    data = np.zeros((8, 8, 8), dtype=np.uint16)
    data[1, 1, 1] = 1; data[5, 5, 5] = 1; data[2, 5, 2] = 2
    idx = build_region_index(data, LabelTable(), _geom(data.shape), connectivity=6)
    st = RegionReviewState(grouping_mode=GroupingMode.CONNECTED.value)
    assert len(st.queue(idx)) == 3
    st.grouping_mode = GroupingMode.LABELS.value
    q = st.queue(idx)
    assert len(q) == 2
    assert [r.label_id for r in q] == [1, 2]
    st.grouping_mode = GroupingMode.LABELS_WITH_COMPONENTS.value
    assert [r.label_id for r in st.queue(idx)] == [1, 1, 2]


def test_region_index_conventions_sparse_high_labels_and_remap():
    data = np.zeros((12, 12, 12), dtype=np.uint16)
    data[1, 1, 1] = 7; data[3, 3, 3] = 7; data[5, 5, 5] = 30000; data[6, 6, 6] = 8
    idx = build_region_index(data, LabelTable(), _geom(data.shape), connectivity=6)
    assert len(idx.records) == 4
    assert set(idx.labels) == {7, 8, 30000}
    state = {idx.records[0].fingerprint.key(): "reviewed"}
    same = build_region_index(data.copy(), LabelTable(), _geom(data.shape), connectivity=6)
    assert remap_review_state(idx, same, state) == state
    changed = data.copy(); changed[1, 1, 2] = idx.records[0].label_id
    new = build_region_index(changed, LabelTable(), _geom(data.shape), connectivity=6)
    assert "changed" in remap_review_state(idx, new, state, threshold=0.5).values()


def test_background_autosave_running_rejected_after_retirement(tmp_path):
    bg = BackgroundTaskService(max_workers=1)
    bg.set_document("doc", 1)
    started = threading.Event(); release = threading.Event(); writes = []
    tag = TaskTag.make("doc", 1, "autosave")
    def work(token):
        started.set(); release.wait(2)
        if not token.cancelled:
            writes.append("write")
        return True
    applied = []
    bg.submit_latest(tag, work, applied.append)
    assert started.wait(2)
    bg.cancel_task_type("autosave")
    bg.set_document("new-doc", 0)
    release.set(); time.sleep(0.05)
    outcomes = bg.drain_completed()
    assert not applied
    assert writes == []
    assert outcomes and outcomes[0].status in {"cancelled", "stale"}
