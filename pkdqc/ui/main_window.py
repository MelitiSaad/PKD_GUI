"""The application window.

Layout philosophy, after a usability review:

* The **left rail holds only modal tools** — things that change what the mouse
  does (Crosshair, Pan, Brush, Fill). Nothing else lives there, so every label
  fits and nothing is truncated.
* **One-shot operations** (grow, shrink, remove islands, fill holes,
  interpolate) are *actions*, not modes, so they live under "Clean up" in the
  toolbar and in the Segmentation menu.
* The eraser is not a separate tool: the right mouse button erases while the
  Brush is active, which is one fewer thing to click.
* Everything reachable from a toolbar is also reachable from the menu bar.
"""
from __future__ import annotations

import copy
import logging
import os
import time
import uuid
from typing import Optional

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QSlider, QSpinBox, QToolBar, QToolButton, QToolTip, QVBoxLayout,
    QWidget,
)

from .. import config, icons, theme
from ..core import commands, io, segops
from ..core.shortcuts import build_command_registry, migrate_shortcuts
from ..core.regions import (
    DEFAULT_CONNECTIVITY, RegionReviewState, build_region_index,
    clear_review_progress, delete_label_checked, delete_region_checked,
    invalidate_after_edit, load_review_progress, progress_identity, save_review_progress,
)
from ..core.background import ArraySnapshot, BackgroundTaskService, TaskTag
from ..core.history import History
from ..core.document import Disposition, SegmentationDocument
from ..core.layers import SegmentationLayers
from ..core.segmentation import Segmentation
from ..core.volumetry import compute_volumes
from ..core.session import Session
from ..errors import gui_guard
from .contrast import ContrastDialog
from .dialogs import DicomSeriesDialog, ShortcutsDialog, about_html
from .label_panel import LabelPanel
from .ortho import OrthoView
from .region_review import RegionReviewPanel
from .tools import ToolController
from . import volume_view

log = logging.getLogger(__name__)

# modal tools only
TOOLS = [
    ("crosshair", "Crosshair", "crosshair", "V"),
    ("pan", "Pan", "navigate", "H"),
    ("brush", "Brush", "brush", "B"),
    ("fill", "Fill", "fill", "F"),
    ("lasso", "Lasso", "lasso", "L"),
]

TOOL_HINTS = {
    "crosshair": "Left-drag moves the crosshair · click selects the object under it "
                 "· right-drag zooms · middle-drag pans",
    "pan": "Left-drag moves the image · right-drag zooms · wheel changes slice",
    "brush": "Left paints the active object · right erases · Alt+wheel or [ ] resizes",
    "fill": "Left fills the connected region · right clears it",
    "lasso": "Left-drag adds the active object · right-drag removes it",
}

# one-shot operations (never in the tool rail)
OPERATIONS = [
    ("grow", "Grow", "grow", "G"),
    ("shrink", "Shrink", "shrink", "Shift+G"),
    ("islands", "Remove islands", "islands", "K"),
    ("holes", "Fill holes", "holes", "J"),
    ("interpolate", "Interpolate slices", "interpolate", "I"),
]

COMMANDS = build_command_registry(TOOLS, OPERATIONS)
_SHORTCUTS = {aid: (spec.label, spec.default) for aid, spec in COMMANDS.items()}

_LAYOUT_OF = {"layout_grid": "grid", "layout_axial": "axial", "layout_coronal": "coronal",
              "layout_sagittal": "sagittal", "layout_3d": "3d"}


class MainWindow(QMainWindow):
    def __init__(self, enable_3d: bool = True):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.resize(1480, 940)
        self.setMinimumSize(1080, 700)
        self.setAcceptDrops(True)
        from PySide6.QtCore import QSettings
        self.settings = QSettings(config.APP_ORG, config.APP_NAME)

        self.image = None
        self.seg: Optional[Segmentation] = None
        self.history: Optional[History] = None
        self.session: Optional[Session] = None
        self.document = SegmentationDocument()
        self.layers = SegmentationLayers()
        self._edits_since_save = 0
        self._contrast_dlg: Optional[ContrastDialog] = None
        self._enable_3d = enable_3d and volume_view.available()
        self._case_id = uuid.uuid4().hex
        self._retired_sessions: set[str] = set()

        self.act: dict[str, QAction] = {}
        self._make_actions()
        self._build_central()
        self._build_menubar()
        self._build_tool_rail()
        self._build_main_bar()
        self._build_view_bar()
        self._build_right_panel()
        self._build_statusbar()
        self._apply_shortcuts()

        self.controller = ToolController(self.ortho, self)
        self.controller.brushRadiusChanged.connect(self._on_brush_changed)
        self.controller.edited.connect(self._on_edited)
        self._connect()
        self._set_tool("crosshair")

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(config.AUTOSAVE_INTERVAL_MS)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()
        self._idle_timer = QTimer(self); self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._autosave)
        self.background = BackgroundTaskService()
        self._bg_timer = QTimer(self); self._bg_timer.setInterval(50)
        self._bg_timer.timeout.connect(self._drain_background)
        self._bg_timer.start()
        self._vol_timer = QTimer(self); self._vol_timer.setSingleShot(True)
        self._vol_timer.timeout.connect(self._submit_volumetry)
        self.controller.background_runner = self._submit_cleanup
        self.region_state = RegionReviewState(connectivity=DEFAULT_CONNECTIVITY)
        self.region_index = None
        self._region_active = False
        self._region_stale = False

        self._update_enabled()
        self._restore_window_state()
        self._set_saved_state("no data")

    # ================================================================ actions
    def _mk(self, aid, icon_name=None, checkable=False):
        label, key = _SHORTCUTS[aid]
        a = QAction(label, self)
        if icon_name:
            a.setIcon(icons.icon(icon_name, theme.TEXT))
        a.setCheckable(checkable)
        a.setToolTip(label + (f"  ({key})" if key else ""))
        self.act[aid] = a
        return a

    def _make_actions(self):
        self.tool_group = QActionGroup(self); self.tool_group.setExclusive(True)
        for tid, _label, ic, _key in TOOLS:
            self.tool_group.addAction(self._mk(tid, ic, checkable=True))
        self.act["crosshair"].setChecked(True)

        for oid, _label, ic, _key in OPERATIONS:
            self._mk(oid, ic)

        self._mk("undo", "undo"); self._mk("redo", "redo")
        self._mk("open_image", "open"); self._mk("load_seg", "layers"); self._mk("save", "save")
        self._mk("save_as", "save")
        self._mk("new_seg")
        self._mk("quit")
        self._mk("next_edited", "next_edit"); self._mk("prev_edited", "prev_edit")
        self._mk("brush_minus"); self._mk("brush_plus")
        self._mk("reset_view", "reset_view"); self._mk("update_3d", "cube")
        self._mk("contrast", "threshold"); self._mk("remove_unused")
        self._mk("toggle_segmentations", checkable=True)
        self.act["toggle_segmentations"].setChecked(True)
        self._mk("region_toggle")
        self._mk("region_next")
        self._mk("region_prev")
        self._mk("region_reviewed")
        self._mk("region_unreviewed")
        self._mk("region_delete")
        self._mk("region_isolate")
        self._mk("brush_threshold", checkable=True)
        self._mk("brush_protect", checkable=True); self.act["brush_protect"].setChecked(True)
        self._mk("continuous_3d", checkable=True)
        self._mk("axes_3d", checkable=True); self.act["axes_3d"].setChecked(True)

        self.layout_group = QActionGroup(self); self.layout_group.setExclusive(True)
        for aid in _LAYOUT_OF:
            self.layout_group.addAction(self._mk(aid, checkable=True))
        self.act["layout_grid"].setChecked(True)

    # ================================================================ layout
    def _build_central(self):
        central = QWidget(); central.setObjectName("Panel")
        v = QVBoxLayout(central); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)
        self.ortho = OrthoView(enable_3d=self._enable_3d)
        v.addWidget(self.ortho, 1)

        bar = QWidget(); bar.setObjectName("Panel")
        hb = QHBoxLayout(bar); hb.setContentsMargins(12, 8, 12, 8); hb.setSpacing(10)
        hb.addWidget(_btn(self.act["prev_edited"]))
        self.slice_slider = QSlider(Qt.Orientation.Horizontal)
        self.slice_slider.setRange(0, 0)
        hb.addWidget(self.slice_slider, 1)
        hb.addWidget(_btn(self.act["next_edited"]))
        self.slice_label = QLabel("\u2014"); self.slice_label.setProperty("role", "muted")
        self.slice_label.setMinimumWidth(170)
        self.slice_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hb.addWidget(self.slice_label)
        v.addWidget(bar)
        self.setCentralWidget(central)

    def _build_menubar(self):
        mb = self.menuBar()
        m_file = mb.addMenu("&File")
        for aid in ("open_image", "load_seg"):
            m_file.addAction(self.act[aid])
        m_file.addSeparator()
        for aid in ("save", "save_as", "new_seg"):
            m_file.addAction(self.act[aid])
        m_file.addSeparator()
        self.act["quit"].triggered.connect(self.close); m_file.addAction(self.act["quit"])

        m_edit = mb.addMenu("&Edit")
        m_edit.addAction(self.act["undo"]); m_edit.addAction(self.act["redo"])

        m_seg = mb.addMenu("&Segmentation")
        for aid in ("load_seg", "save", "save_as", "new_seg"):
            m_seg.addAction(self.act[aid])
        m_seg.addSeparator()
        m_cleanup = m_seg.addMenu("Clean up")
        for oid, _l, _i, _k in OPERATIONS:
            m_seg.addAction(self.act[oid])
        m_seg.addSeparator()
        m_seg.addAction(self.act["remove_unused"])

        m_tools = mb.addMenu("&Tools")
        for tid, _l, _i, _k in TOOLS:
            m_tools.addAction(self.act[tid])
        m_tools.addSeparator()
        m_tools.addAction(self.act["brush_threshold"])
        m_tools.addAction(self.act["brush_protect"])
        m_tools.addAction(self.act["brush_minus"]); m_tools.addAction(self.act["brush_plus"])
        m_tools.addSeparator()
        m_tools.addAction(self.act["contrast"])

        m_view = mb.addMenu("&View")
        m_layout = m_view.addMenu("Layout")
        for aid in _LAYOUT_OF:
            m_layout.addAction(self.act[aid])
        m_view.addAction(self.act["reset_view"])
        m_view.addAction(self.act["toggle_segmentations"])
        m_view.addSeparator()
        for aid in ("update_3d", "continuous_3d", "axes_3d"):
            m_view.addAction(self.act[aid])

        m_review = mb.addMenu("&Region Review")
        for aid in ("region_toggle", "region_next", "region_prev", "region_reviewed",
                    "region_unreviewed", "region_delete", "region_isolate"):
            m_review.addAction(self.act[aid])

        m_help = mb.addMenu("&Help")
        self.act_shortcuts = QAction("Keyboard shortcuts\u2026", self)
        self.act_about = QAction("About", self)
        m_help.addAction(self.act_shortcuts); m_help.addAction(self.act_about)

    def _build_tool_rail(self):
        rail = QToolBar("Tools"); rail.setOrientation(Qt.Orientation.Vertical)
        rail.setMovable(False); rail.setIconSize(QSize(24, 24)); rail.setFixedWidth(96)
        rail.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        for tid, _l, _i, _k in TOOLS:
            rail.addAction(self.act[tid])
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, rail)

    def _build_main_bar(self):
        top = QToolBar("Main"); top.setMovable(False); top.setIconSize(QSize(18, 18))
        top.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for aid in ("open_image", "load_seg", "save"):
            top.addAction(self.act[aid])
        top.addSeparator()
        top.addAction(self.act["undo"]); top.addAction(self.act["redo"])
        top.addSeparator()

        top.addWidget(QLabel(" Brush "))
        self.brush_mode = QComboBox()
        self.brush_mode.addItems(["Normal", "Threshold"])
        self.brush_mode.setToolTip("Threshold restricts painting to the contrast window (T)")
        top.addWidget(self.brush_mode)
        top.addAction(self.act["brush_protect"])
        self.brush_spin = QSpinBox()
        self.brush_spin.setRange(config.MIN_BRUSH_RADIUS, config.MAX_BRUSH_RADIUS)
        self.brush_spin.setValue(config.DEFAULT_BRUSH_RADIUS)
        self.brush_spin.setSuffix(" px"); self.brush_spin.setFixedWidth(78)
        top.addWidget(self.brush_spin)
        top.addSeparator()

        self.btn_cleanup = QToolButton()
        self.btn_cleanup.setText("Cleanup")
        self.btn_cleanup.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.btn_cleanup.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_cleanup)
        for oid, _l, _i, _k in OPERATIONS:
            menu.addAction(self.act[oid])
        menu.addSeparator(); menu.addAction(self.act["remove_unused"])
        self.btn_cleanup.setMenu(menu)
        top.addWidget(self.btn_cleanup)
        top.addAction(self.act["contrast"])
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, top)

    def _build_view_bar(self):
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        vb = QToolBar("View"); vb.setMovable(False); vb.setIconSize(QSize(18, 18))
        vb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        vb.addWidget(QLabel(" View "))
        for aid in _LAYOUT_OF:
            b = QToolButton(); b.setDefaultAction(self.act[aid])
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            vb.addWidget(b)
        vb.addAction(self.act["reset_view"])
        vb.addSeparator()
        vb.addAction(self.act["update_3d"])
        b3 = QToolButton(); b3.setDefaultAction(self.act["continuous_3d"])
        b3.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        vb.addWidget(b3)
        ba = QToolButton(); ba.setDefaultAction(self.act["axes_3d"])
        ba.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        vb.addWidget(ba)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, vb)

    def _build_right_panel(self):
        self.panel = LabelPanel()
        dock = QDockWidget(""); dock.setTitleBarWidget(QWidget())
        dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        dock.setWidget(self.panel); dock.setFixedWidth(324)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

        self.region_panel = RegionReviewPanel()
        rdock = QDockWidget("Region Review")
        rdock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        rdock.setWidget(self.region_panel); rdock.setFixedWidth(324)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, rdock)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.lbl_coord = QLabel(""); self.lbl_tool = QLabel(""); self.lbl_hint = QLabel("")
        self.lbl_document = QLabel(""); self.lbl_saved = QLabel("")
        for w in (self.lbl_coord, self.lbl_tool, self.lbl_hint):
            sb.addWidget(w)
        sb.addPermanentWidget(self.lbl_document)
        sb.addPermanentWidget(self.lbl_saved)

    # ================================================================ wiring
    def _connect(self):
        for tid, _l, _i, _k in TOOLS:
            self.act[tid].triggered.connect(lambda _=False, t=tid: self._set_tool(t))
        self.act["grow"].triggered.connect(self._grow)
        self.act["shrink"].triggered.connect(self._shrink)
        self.act["islands"].triggered.connect(self._islands)
        self.act["holes"].triggered.connect(self._holes)
        self.act["interpolate"].triggered.connect(self._interpolate)
        self.act["undo"].triggered.connect(self._undo)
        self.act["redo"].triggered.connect(self._redo)
        self.act["open_image"].triggered.connect(self._open_image)
        self.act["load_seg"].triggered.connect(self._load_seg)
        self.act["save"].triggered.connect(self._save)
        self.act["save_as"].triggered.connect(self._save_as)
        self.act["new_seg"].triggered.connect(self._new_seg)
        self.act["next_edited"].triggered.connect(lambda: self._jump_edited(+1))
        self.act["prev_edited"].triggered.connect(lambda: self._jump_edited(-1))
        self.act["brush_minus"].triggered.connect(lambda: self._nudge_brush(-1))
        self.act["brush_plus"].triggered.connect(lambda: self._nudge_brush(+1))
        self.act["brush_threshold"].toggled.connect(self._on_threshold_toggled)
        self.act["brush_protect"].toggled.connect(self.controller.set_protect_existing)
        self.act["reset_view"].triggered.connect(self._reset_view)
        self.act["update_3d"].triggered.connect(self._update_3d)
        self.act["contrast"].triggered.connect(self._open_contrast)
        self.act["remove_unused"].triggered.connect(self._remove_unused)
        self.act["toggle_segmentations"].triggered.connect(self._toggle_segmentations)
        self.act["continuous_3d"].toggled.connect(self._toggle_continuous_3d)
        self.act["region_toggle"].triggered.connect(self._toggle_region_review)
        self.act["region_next"].triggered.connect(self._region_next)
        self.act["region_prev"].triggered.connect(self._region_previous)
        self.act["region_reviewed"].triggered.connect(self._region_reviewed)
        self.act["region_unreviewed"].triggered.connect(self._region_unreviewed)
        self.act["region_delete"].triggered.connect(self._region_delete_current)
        self.act["region_isolate"].triggered.connect(self._region_toggle_isolation)
        self.act["axes_3d"].toggled.connect(self._toggle_axes)
        for aid in _LAYOUT_OF:
            self.act[aid].triggered.connect(lambda _=False, a=aid: self.ortho.set_layout(_LAYOUT_OF[a]))
        self.act_shortcuts.triggered.connect(self._edit_shortcuts)
        self.act_about.triggered.connect(self._about)

        self.ortho.cursorChanged.connect(self._on_cursor_changed)
        self.ortho.hovered.connect(self._on_hover)
        self.ortho.labelPicked.connect(self._on_label_picked)
        self.ortho.layoutChanged.connect(self._on_layout_changed)
        self.slice_slider.valueChanged.connect(self.ortho.set_axial_slice)
        self.brush_spin.valueChanged.connect(self._on_spin_brush)
        self.brush_mode.currentTextChanged.connect(self._on_brush_mode)
        self.panel.activeLabelChanged.connect(self._on_active_label_changed)
        self.panel.overlayChanged.connect(self._on_overlay_changed)
        self.panel.deleteLabelRequested.connect(self._delete_label)
        self.region_panel.toggled.connect(self._toggle_region_review)
        self.region_panel.rebuildRequested.connect(self._submit_region_index)
        self.region_panel.nextRequested.connect(self._region_next)
        self.region_panel.previousRequested.connect(self._region_previous)
        self.region_panel.reviewedRequested.connect(self._region_reviewed)
        self.region_panel.unreviewedRequested.connect(self._region_unreviewed)
        self.region_panel.deleteRegionRequested.connect(self._region_delete_current)
        self.region_panel.deleteLabelRequested.connect(self._region_delete_label)
        self.region_panel.isolateRequested.connect(self._region_toggle_isolation)
        self.region_panel.clearProgressRequested.connect(self._region_clear_progress)
        self.region_panel.groupingChanged.connect(self._region_set_grouping)
        self.region_panel.connectivityChanged.connect(self._region_set_connectivity)
        self.region_panel.includedLabelsChanged.connect(self._region_set_included_labels)
        self.region_panel.sortChanged.connect(self._region_set_sort)
        self.region_panel.filterChanged.connect(self._region_set_filter)

    def _apply_shortcuts(self):
        self._shortcut_assignments = migrate_shortcuts(self.settings.value(config.SK_SHORTCUTS, {}) or {}, COMMANDS)
        for aid, key in self._shortcut_assignments.items():
            if aid in self.act:
                self.act[aid].setShortcut(QKeySequence(key))
                self.act[aid].setShortcutContext(Qt.ShortcutContext.WindowShortcut)
                self._refresh_action_text(aid)

    def _refresh_action_text(self, aid):
        spec = COMMANDS[aid]
        key = self.act[aid].shortcut().toString()
        self.act[aid].setToolTip(spec.label + (f"  ({key})" if key else ""))

    def _retire_session(self, remove=True):
        self._autosave_timer.stop(); self._idle_timer.stop()
        self.background.cancel_task_type("autosave")
        session = self.session
        if session is not None:
            self._retired_sessions.add(session.id)
            session.mark_clean(remove=remove)


    # ================================================================ tools
    def _update_tool_feedback(self, name):
        spec = COMMANDS[name]
        self.lbl_tool.setText(f"  Tool: {spec.label}")
        self.lbl_hint.setText(f"  {TOOL_HINTS.get(name, '')}")

    @gui_guard
    def _set_tool(self, name):
        self.controller.set_tool(name)
        self.act[name].setChecked(True)
        self._update_tool_feedback(name)
        is_brush = name == "brush"
        self.brush_spin.setEnabled(is_brush)
        self.brush_mode.setEnabled(is_brush)
        self.act["brush_protect"].setEnabled(is_brush)

    @gui_guard

    def _on_brush_mode(self, text):
        self.controller.set_brush_mode("threshold" if text == "Threshold" else "normal")
        self.act["brush_threshold"].blockSignals(True)
        self.act["brush_threshold"].setChecked(text == "Threshold")
        self.act["brush_threshold"].blockSignals(False)

    def _on_threshold_toggled(self, on):
        self.brush_mode.setCurrentText("Threshold" if on else "Normal")

    @gui_guard
    def _grow(self): self.controller.apply_grow()
    @gui_guard
    def _shrink(self): self.controller.apply_shrink()
    @gui_guard
    def _islands(self): self.controller.apply_remove_islands()
    @gui_guard
    def _holes(self): self.controller.apply_fill_holes()
    @gui_guard
    def _interpolate(self): self.controller.apply_interpolate()

    @gui_guard
    def _undo(self):
        if self.history:
            self._after_history(self.history.undo())
    @gui_guard
    def _redo(self):
        if self.history:
            self._after_history(self.history.redo())

    def _after_history(self, cmd):
        if cmd is not None and cmd.slices:
            self.ortho.set_axial_slice(cmd.slices[0])
        self.ortho.redraw_overlay()
        self.ortho.notify_edit()
        self._mark_dirty()

    # ================================================================ brush
    def _on_brush_changed(self, r):
        self.brush_spin.blockSignals(True); self.brush_spin.setValue(r)
        self.brush_spin.blockSignals(False)
    def _on_spin_brush(self, r): self.controller.set_brush_radius(r)
    def _nudge_brush(self, d): self.controller.set_brush_radius(self.controller.brush_radius + d)

    # ================================================================ cursor / slices
    def _on_cursor_changed(self, i, j, k):
        self.slice_slider.blockSignals(True); self.slice_slider.setValue(k)
        self.slice_slider.blockSignals(False)
        n = self.image.n_slices if self.image else 0
        edited = "  \u00b7  edited" if (self.seg and k in self.seg.edited_slices) else ""
        self.slice_label.setText(f"Axial {k + 1} / {n}{edited}")

    def _jump_edited(self, direction):
        if not self.seg or not self.seg.edited_slices:
            return
        z = self.ortho.z
        cand = sorted(self.seg.edited_slices)
        nxt = [s for s in cand if s > z] if direction > 0 else [s for s in cand if s < z][::-1]
        if nxt:
            self.ortho.set_axial_slice(nxt[0])

    def _on_hover(self, i, j, k):
        if self.image is None:
            self.lbl_coord.setText(""); return
        val = self.image.data[i, j, k]
        seg_id = int(self.seg.data[i, j, k]) if self.seg is not None else 0
        name = self.panel.label_name(seg_id) if seg_id else "\u2014"
        self.lbl_coord.setText(f"  ({i}, {j}, {k})   I={val:.0f}   object: {name}")

    @gui_guard
    def _on_label_picked(self, lid):
        self.panel.select_label(lid)
        self.ortho.set_selected_label(lid)
        summary = self.panel.selection_summary(lid)
        self.statusBar().showMessage(f"Selected {self.panel.label_name(lid)} (#{lid})", 3000)
        QToolTip.showText(QCursor.pos(), summary, self, self.rect(), 3500)

    def _on_active_label_changed(self, lid):
        self.ortho.set_selected_label(lid)
        self.ortho.redraw_overlay()

    # ================================================================ layout / view
    def _on_layout_changed(self, mode):
        aid = {v: k for k, v in _LAYOUT_OF.items()}.get(mode)
        if aid and not self.act[aid].isChecked():
            self.act[aid].setChecked(True)

    @gui_guard
    def _reset_view(self): self.ortho.fit_all()

    @gui_guard
    def _update_3d(self):
        self.statusBar().showMessage("Rebuilding 3D surface\u2026", 1500)
        self.ortho.refresh_3d()

    def _toggle_continuous_3d(self, on):
        self.ortho.continuous_3d = bool(on)
        if on:
            self.ortho.refresh_3d()

    def _toggle_axes(self, on):
        self.ortho.set_3d_axes_visible(bool(on))

    def _toggle_segmentations(self, checked=False):
        # QAction shortcuts must not steal ordinary typing.
        from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QComboBox, QLineEdit, QTextEdit
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QComboBox, QAbstractSpinBox)):
            self.act["toggle_segmentations"].setChecked(self.layers.global_overlay_visible)
            return
        self.layers.global_overlay_visible = bool(checked)
        self.ortho.rendering_layers = self.layers.rendering_layers()
        self.ortho.redraw_overlay()

    @gui_guard
    def _open_contrast(self):
        if self.image is None:
            return
        self._contrast_dlg = ContrastDialog(self.ortho, self)
        self._contrast_dlg.show(); self._contrast_dlg.raise_()

    @gui_guard
    def _remove_unused(self):
        if self.seg is None:
            return
        n = self.panel.remove_unused_labels()
        self.ortho.redraw_overlay()
        self.statusBar().showMessage(
            f"Removed {n} unused object{'s' if n != 1 else ''}." if n else "No unused objects.", 3000)

    # ================================================================ files
    @gui_guard
    def _open_image(self):
        path = self._pick_open("Open image", "Images (*.nii *.nii.gz *.dcm);;All files (*)")
        if not path:
            return
        image = io.load_image(path, dicom_selector=self._select_dicom_series)
        if not self._guard_unsaved():
            return
        self._set_case(image, Segmentation.empty_like(image.shape), None)
        self.statusBar().showMessage(
            f"Loaded {os.path.basename(path)}  ·  shape {image.shape}  ·  "
            f"spacing {tuple(round(s, 2) for s in image.spacing)} mm", 8000)

    @gui_guard
    def _load_seg(self):
        if self.image is None:
            QMessageBox.information(self, "Load an image first",
                                    "Open the image before loading its segmentation.")
            return
        path = self._pick_open("Load segmentation", "Segmentations (*.nii *.nii.gz);;All files (*)")
        if not path:
            return
        seg = io.load_segmentation(path, self.image.shape, self.image.affine)
        if not self._guard_unsaved():
            return
        self._set_case(self.image, seg, path)
        self.statusBar().showMessage(f"Overlaid {os.path.basename(path)}", 4000)

    @gui_guard
    def _new_seg(self):
        if self.image is not None and self._guard_unsaved():
            self._set_case(self.image, Segmentation.empty_like(self.image.shape), None)

    @gui_guard
    def _save(self):
        return self._save_impl(False)

    @gui_guard
    def _save_as(self):
        return self._save_impl(True)

    def _save_impl(self, as_new_path=False):
        if not self.document.has_segmentation:
            return False
        self.background.cancel_task_type("autosave")
        if as_new_path:
            ok = self.document.save_as(io.save_segmentation, self._choose_save_path,
                                       self._confirm_overwrite)
        else:
            ok = self.document.save(io.save_segmentation, self._choose_save_path,
                                    self._confirm_overwrite)
        if ok:
            if self.session is not None:
                self.session.seg_path = self.document.segmentation_path
                # A successful user export leaves no unsaved work to recover.
                self._retire_session(remove=True)
            self._sync_document_state()
            name = os.path.basename(self.document.segmentation_path or "segmentation")
            self._set_saved_state("saved", extra=f"to {name}")
            if getattr(self, "region_state", None) is not None:
                self._save_region_progress()
            self.statusBar().showMessage(f"Saved {name}", 4000)
        return ok

    def _choose_save_path(self):
        default_dir = self.settings.value(config.SK_LAST_DIR, "")
        current = self.document.segmentation_path
        suggested = current or os.path.join(default_dir, "segmentation.nii.gz")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save segmentation as", suggested, "NIfTI (*.nii.gz *.nii)",
            options=QFileDialog.Option.DontConfirmOverwrite)
        if path:
            self.settings.setValue(config.SK_LAST_DIR, os.path.dirname(path))
        return path or None

    def _confirm_overwrite(self, path):
        answer = QMessageBox.question(
            self, "Replace existing segmentation?",
            f"“{os.path.basename(path)}” already exists. Replace it?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Save

    def _guard_unsaved(self):
        def decide():
            box = QMessageBox(self)
            box.setWindowTitle("Unsaved segmentation changes")
            box.setText("Save changes to the current segmentation before continuing?")
            save = box.addButton(QMessageBox.StandardButton.Save)
            discard = box.addButton(QMessageBox.StandardButton.Discard)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is save:
                return Disposition.SAVE
            if box.clickedButton() is discard:
                return Disposition.DISCARD
            return Disposition.CANCEL
        return self.document.guard(decide, lambda: self._save_impl(False),
                                   self._discard_checkpoint)

    def _discard_checkpoint(self):
        self.background.cancel_all()
        self._retire_session(remove=True)


    def _select_dicom_series(self, candidates):
        dlg = DicomSeriesDialog(candidates, self)
        if dlg.exec() == DicomSeriesDialog.DialogCode.Accepted:
            return dlg.chosen
        return None

    def _pick_open(self, title, filt):
        start = self.settings.value(config.SK_LAST_DIR, "")
        path, _ = QFileDialog.getOpenFileName(self, title, start, filt)
        if path:
            self.settings.setValue(config.SK_LAST_DIR, os.path.dirname(path))
        return path

    # ================================================================ case
    def _set_case(self, image, seg, seg_path):
        self.background.cancel_all()
        self._retire_session(remove=True)
        self.image = image
        self.seg = seg
        self.layers = SegmentationLayers(image)
        layer = self.layers.add(os.path.basename(seg_path) if seg_path else "Untitled segmentation",
                                seg, path=seg_path, make_active=True)
        self._case_id = uuid.uuid4().hex
        self.background.set_document(self._case_id, seg.revision)
        self.document = (SegmentationDocument.loaded(image, seg, seg_path)
                         if seg_path else SegmentationDocument(
                             image, seg, None, seg.revision, True))
        self.history = History(seg)
        self.history.on_change = self._refresh_undo
        self.controller.set_context(image, seg, self.history)
        self.ortho.set_layers(image, self.layers.rendering_layers(), layer.layer_id)
        self.panel.set_context(image, seg)
        self._reset_region_review()
        self.slice_slider.setRange(0, image.n_slices - 1)
        self.slice_slider.setValue(self.ortho.z)
        self.session = Session(image, seg_path)
        self.session.begin()
        self._edits_since_save = 0
        self._contrast_dlg = None
        self._refresh_undo()
        self._update_enabled()
        self.panel.recompute()
        self._set_saved_state("saved")
        self._sync_document_state()
        QTimer.singleShot(200, self.ortho.refresh_3d)  # one-time build; not on every edit

    def load_recovered(self, image, seg, recovery):
        self._set_case(image, seg, seg_path=recovery.seg_path)
        self.document.saved_revision = recovery.saved_revision
        self.document.never_saved = recovery.seg_path is None
        self.seg.dirty = recovery.dirty
        self._sync_document_state()
        self._set_saved_state("unsaved", extra="recovered")

    # ================================================================ labels
    @gui_guard
    def _delete_label(self, lid):
        if self.seg is None or self.history is None:
            return
        if len(self.seg.labels) <= 1:
            QMessageBox.information(self, "Cannot remove", "At least one object must remain.")
            return
        new = self.seg.data.copy()
        new[new == np.uint16(lid)] = 0
        cmd = commands.apply_volume(self.seg, new, "delete object")
        if cmd is not None:
            self.history.push(cmd)
        self.seg.labels.remove(lid)
        if self.seg.active_id == lid:
            self.seg.active_id = next(iter(self.seg.labels)).id
        self.panel.rebuild()
        self.ortho.redraw_overlay()
        self.ortho.notify_edit()
        self._mark_dirty()

    # ================================================================ edits / autosave
    def _on_edited(self): self._mark_dirty()

    def _mark_dirty(self):
        self._edits_since_save += 1
        self._sync_document_state()
        if self.seg is not None:
            self.background.update_revision(self.seg.revision)
        self._set_saved_state("unsaved" if self.document.dirty else "saved")
        self._idle_timer.start(config.AUTOSAVE_IDLE_MS)
        self._schedule_volumes()
        if getattr(self, "_region_active", False):
            self._region_stale = True
            invalidate_after_edit(self.region_index) if self.region_index is not None else None
            self._submit_region_index()
        if self._edits_since_save >= config.AUTOSAVE_EVERY_N_EDITS:
            self._autosave()

    def _on_overlay_changed(self):
        self.ortho.redraw_overlay()
        self._schedule_volumes()
        if getattr(self, "_region_active", False):
            self._region_stale = True
            invalidate_after_edit(self.region_index) if self.region_index is not None else None
            self._submit_region_index()

    def _schedule_volumes(self): self._vol_timer.start(350)

    def _tag(self, task_type, params=None):
        rev = self.seg.revision if self.seg is not None else -1
        return TaskTag.make(self._case_id, rev, task_type, params)

    def _snapshot(self):
        return ArraySnapshot.capture(self._case_id, self.seg.revision, self.seg.data)

    def _submit_volumetry(self):
        if self.image is None or self.seg is None:
            return
        tag = self._tag("volumetry")
        snap = self._snapshot()
        image = self.image
        labels = copy.deepcopy(self.seg.labels)
        self.panel.btn_compute.setText("Updating…")
        def work(token):
            token.raise_if_cancelled()
            seg = Segmentation(snap.data.copy(), labels)
            return compute_volumes(seg, image)
        def apply(volumes):
            self.panel.set_volumes(volumes)
            self.panel.btn_compute.setText("Compute volumes")
        def error(exc):
            log.warning("Background volumetry failed: %s", exc.__class__.__name__)
            self.panel.btn_compute.setText("Compute volumes")
        self.background.submit_latest(tag, work, apply, error)

    def _submit_cleanup(self, op_name, label_id, in_3d, z, island_min):
        if self.seg is None or self.history is None:
            return
        tag = self._tag("cleanup", {"op": op_name, "label": label_id, "in_3d": in_3d, "z": z})
        snap = self._snapshot()
        labels = copy.deepcopy(self.seg.labels)
        protect = bool(self.controller.protect_existing)
        self.statusBar().showMessage(f"Running {op_name}…", 2000)
        def work(token):
            token.raise_if_cancelled()
            seg = Segmentation(snap.data.copy(), labels)
            seg.active_id = label_id
            policy = None
            if op_name in ("grow", "remove islands"):
                from ..core.label_policy import policy_for
                policy = policy_for(seg, protect_existing=protect)
            if op_name == "grow":
                cmd = segops.grow(seg, label_id, 1, in_3d, z, policy=policy)
            elif op_name == "shrink":
                cmd = segops.shrink(seg, label_id, 1, in_3d, z)
            elif op_name == "remove islands":
                cmd = segops.remove_islands(seg, label_id, island_min, in_3d, z, policy=policy)
            elif op_name == "fill holes":
                cmd = segops.fill_holes(seg, label_id, in_3d, z)
            else:
                cmd = None
            token.raise_if_cancelled()
            return None if cmd is None else seg.data.copy()
        def apply(new_data):
            if new_data is None:
                self.statusBar().showMessage(f"{op_name} made no changes", 2500)
                return
            cmd = commands.apply_volume(self.seg, new_data, op_name)
            if cmd is not None:
                self.history.push(cmd)
                self.ortho.redraw_overlay(); self.ortho.notify_edit(); self._mark_dirty()
                self.statusBar().showMessage(f"Finished {op_name}", 2500)
        def error(exc):
            log.warning("Background cleanup failed: %s", exc.__class__.__name__)
            self.statusBar().showMessage(f"{op_name} failed", 4000)
        self.background.submit_destructive(tag, work, apply, error)

    def _autosave(self):
        if self.session is None or self.seg is None:
            return
        tag = self._tag("autosave")
        snap = self._snapshot()
        saved_revision = self.document.saved_revision
        dirty = self.document.dirty
        session = self.session
        self._set_saved_state("autosaving", extra=f"rev {snap.revision}")
        def work(token):
            seg = Segmentation(snap.data.copy())
            seg.revision = snap.revision
            seg.dirty = dirty
            if session.id in self._retired_sessions or token.cancelled:
                return snap.revision, False
            ok = session.save(seg, saved_revision=saved_revision, dirty=dirty)
            if session.id in self._retired_sessions or token.cancelled:
                session.mark_clean(remove=True)
                return snap.revision, False
            return snap.revision, ok
        def apply(result):
            revision, ok = result
            if ok:
                self._edits_since_save = 0
                self._set_saved_state("autosaved", extra=f"rev {revision}")
        def error(exc):
            log.warning("Background autosave failed: %s", exc.__class__.__name__)
            self._set_saved_state("autosave error")
        self.background.submit_latest(tag, work, apply, error)

    # ============================================================ region review
    def _reset_region_review(self):
        identity = self._review_identity()
        try:
            stored = load_review_progress(identity) if identity else None
        except ValueError:
            log.warning("Ignored Region Review progress with mismatched or unsupported identity")
            stored = None
        self.region_state = stored or RegionReviewState(connectivity=DEFAULT_CONNECTIVITY)
        self.region_index = None
        self._region_active = False
        self._region_stale = False
        self.region_panel.set_available(self.seg is not None)
        self.region_panel.set_index(None, self.region_state)

    def _review_identity(self):
        if self.image is None or self.seg is None:
            return None
        labels = [int(v) for v in np.unique(self.seg.data) if int(v) != 0]
        return progress_identity(
            segmentation_path=self.document.segmentation_path,
            shape=self.seg.data.shape,
            affine=self.image.affine,
            dtype=str(self.seg.data.dtype),
            labels=labels,
        )

    @gui_guard
    def _toggle_region_review(self):
        if self.seg is None:
            return
        self._region_active = not self._region_active
        if self._region_active and self.region_index is None:
            self._submit_region_index()
        self.region_panel.active = self._region_active
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
        self._update_enabled()

    def _submit_region_index(self):
        if self.image is None or self.seg is None:
            return
        tag = self._tag("region_index", {
            "connectivity": self.region_state.connectivity,
            "grouping": self.region_state.grouping_mode,
            "included": tuple(sorted(self.region_state.included_labels)),
        })
        snap = self._snapshot()
        labels = copy.deepcopy(self.seg.labels)
        geometry = self.image.geometry
        review = dict(self.region_state.review_by_fingerprint)
        included = set(self.region_state.included_labels) or None
        self.region_panel.set_index(self.region_index, self.region_state, indexing=True, stale=self._region_stale)
        self.statusBar().showMessage("Indexing regions…", 2000)
        def work(token):
            token.raise_if_cancelled()
            return build_region_index(
                snap.data, labels, geometry, document_id=snap.document_id,
                revision=snap.revision, connectivity=tag.params[0][1],
                included_labels=included, review_state=review,
            )
        def apply(index):
            if not self.region_state.included_labels:
                self.region_state.included_labels = set(index.labels)
            self.region_index = index
            self._region_stale = False
            self.region_panel.active = self._region_active
            self.region_panel.set_index(index, self.region_state)
            self.statusBar().showMessage(f"Indexed {len(index.records):,} regions", 3000)
        def error(exc):
            log.warning("Region indexing failed: %s", exc.__class__.__name__)
            self.statusBar().showMessage("Region indexing failed", 4000)
            self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
        self.background.submit_latest(tag, work, apply, error)

    def _region_focus(self):
        if self.region_index is None:
            return
        rec = self.region_state.current(self.region_index)
        if rec is None:
            return
        i, j, k = rec.representative_voxel
        self.ortho.set_cursor(i, j, k)
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)

    @gui_guard
    def _region_next(self):
        if self.region_index is not None:
            self.region_state.next(self.region_index)
            self._region_focus()

    @gui_guard
    def _region_previous(self):
        if self.region_index is not None:
            self.region_state.previous(self.region_index)
            self._region_focus()

    @gui_guard
    def _region_reviewed(self):
        if self.region_index is not None:
            self.region_state.mark_reviewed_and_advance(self.region_index)
            self._save_region_progress()
            self._region_focus()

    @gui_guard
    def _region_unreviewed(self):
        if self.region_index is not None:
            self.region_state.mark_unreviewed(self.region_index)
            self._save_region_progress()
            self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)

    @gui_guard
    def _region_delete_current(self):
        if self.seg is None or self.history is None or self.region_index is None:
            return
        rec = self.region_state.current(self.region_index)
        if rec is None:
            return
        if rec.voxel_count > 5000:
            answer = QMessageBox.question(
                self, "Delete connected region?",
                f"Delete this connected region ({rec.voxel_count:,} voxels, {rec.volume_ml:.3f} mL)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
        cmd = delete_region_checked(self.seg, self.region_index, rec)
        self.history.push(cmd)
        self.ortho.redraw_overlay(); self.ortho.notify_edit(); self._mark_dirty()
        self._region_stale = True
        self.statusBar().showMessage("Deleted connected region", 2500)

    @gui_guard
    def _region_delete_label(self):
        if self.seg is None or self.history is None or self.region_index is None:
            return
        rec = self.region_state.current(self.region_index)
        if rec is None:
            return
        summary = self.region_index.labels.get(rec.label_id)
        answer = QMessageBox.question(
            self, "Delete entire label?",
            f"Delete entire label {rec.label_id} ({summary.component_count if summary else 0} components, "
            f"{summary.voxel_count if summary else 0:,} voxels)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.history.push(delete_label_checked(self.seg, rec.label_id))
        self.ortho.redraw_overlay(); self.ortho.notify_edit(); self._mark_dirty()
        self._region_stale = True
        self.statusBar().showMessage("Deleted entire label", 2500)

    @gui_guard
    def _region_toggle_isolation(self):
        if self.region_index is not None:
            self.region_state.toggle_isolation(self.region_index)
            self.ortho.redraw_overlay()
            self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
            self.statusBar().showMessage("Region isolation toggled (rendering only)", 2500)

    def _region_set_grouping(self, mode):
        self.region_state.grouping_mode = str(mode)
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
        self._save_region_progress()

    def _region_set_connectivity(self, connectivity):
        self.region_state.connectivity = int(connectivity)
        self.region_index = None
        if self._region_active:
            self._submit_region_index()
        self._save_region_progress()

    def _region_set_included_labels(self, text):
        if self.seg is None or self.image is None:
            return
        try:
            labels = self._parse_label_list(text)
        except ValueError:
            self.statusBar().showMessage("Included labels must be numbers or ranges such as 1,2,7-9.", 5000)
            return
        self.region_state.included_labels = labels
        if self.region_index is not None:
            self.region_index = self.region_index.with_included_labels(labels or self.region_index.labels)
            self.region_state.included_labels = set(self.region_index.included_labels)
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
        self._save_region_progress()

    def _region_set_sort(self, sort):
        self.region_state.sort_mode = str(sort)
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
        self._save_region_progress()

    def _region_set_filter(self, filter_mode):
        self.region_state.filter_mode = str(filter_mode)
        self.region_state.current_position = 0
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)
        self._save_region_progress()

    def _parse_label_list(self, text):
        labels = set()
        for part in str(text or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                labels.update(range(int(a), int(b) + 1))
            else:
                labels.add(int(part))
        return labels

    def _region_clear_progress(self):
        identity = self._review_identity()
        if identity:
            clear_review_progress(identity)
        self.region_state.review_by_fingerprint.clear()
        self.region_state.current_position = 0
        self.region_panel.set_index(self.region_index, self.region_state, stale=self._region_stale)

    def _save_region_progress(self):
        identity = self._review_identity()
        if identity:
            save_review_progress(identity, self.region_state)

    def _drain_background(self):
        for outcome in self.background.drain_completed():
            if outcome.status == "stale" and outcome.tag.task_type == "cleanup":
                self.statusBar().showMessage("Cleanup result was stale; run it again if still needed.", 4000)
            elif outcome.status == "stale" and outcome.tag.task_type == "region_index":
                self.statusBar().showMessage("Region index result was stale; rebuilding for the current revision.", 4000)
            elif outcome.status == "cancelled":
                self.statusBar().showMessage(f"Cancelled {outcome.tag.task_type}", 2000)
        if getattr(self.panel, "btn_compute", None) is not None and self.background.queue_size == 0:
            self.panel.btn_compute.setText("Compute volumes")

    def _set_saved_state(self, state, extra=""):
        colors = {"saved": theme.SUCCESS, "autosaved": theme.SUCCESS, "autosaving": theme.TEXT_MUTED, "unsaved": theme.WARNING,
                  "autosave error": theme.DANGER, "no data": theme.TEXT_FAINT}
        text = {"saved": "All changes saved", "autosaved": "Autosaved", "autosaving": "Autosaving",
                "unsaved": "Unsaved changes", "autosave error": "Autosave failed",
                "no data": "No segmentation loaded"}.get(state, state)
        stamp = time.strftime("%H:%M:%S") if state in ("saved", "autosaved") else ""
        suffix = f" · {extra}" if extra else (f" · {stamp}" if stamp else "")
        self.lbl_saved.setText(f"\u25cf  {text}{suffix}  ")
        self.lbl_saved.setStyleSheet(f"color: {colors.get(state, theme.TEXT_MUTED)};")

    def _sync_document_state(self):
        dirty = self.document.dirty
        if self.seg is not None:
            self.seg.dirty = dirty
        path = self.document.segmentation_path
        name = os.path.basename(path) if path else ("Untitled segmentation" if self.seg else "")
        self.lbl_document.setText((name + (" *" if dirty else "")) if name else "")
        tip = path or "Segmentation has not been saved"
        if self.image is not None and getattr(self.image, "geometry", None) is not None:
            g = self.image.geometry
            status = "valid" if g.validation.ok else "invalid"
            tip += (f"\nImage geometry: shape {g.shape}, spacing "
                    f"{tuple(round(v, 4) for v in g.spacing)} mm, orientation {g.orientation}, "
                    f"voxel volume {g.voxel_volume_mm3:.6g} mm³, status {status}, "
                    "display convention radiological/RAS+")
        self.lbl_document.setToolTip(tip)
        self.setWindowTitle(f"{'*' if dirty else ''}{config.APP_NAME}")

    # ================================================================ misc
    def _refresh_undo(self):
        self.act["undo"].setEnabled(bool(self.history and self.history.can_undo))
        self.act["redo"].setEnabled(bool(self.history and self.history.can_redo))

    def _update_enabled(self):
        has_img = self.image is not None
        for aid in list(_LAYOUT_OF) + [t[0] for t in TOOLS] + [o[0] for o in OPERATIONS] + [
                "new_seg", "next_edited", "prev_edited", "reset_view", "contrast",
                "remove_unused", "update_3d", "load_seg", "brush_threshold", "brush_protect",
                "region_toggle", "region_next", "region_prev", "region_reviewed",
                "region_unreviewed", "region_delete", "region_isolate"]:
            self.act[aid].setEnabled(has_img)
        has_seg = self.seg is not None
        self.act["save"].setEnabled(has_seg)
        self.act["save_as"].setEnabled(has_seg)
        self.act["region_toggle"].setEnabled(has_seg)
        for aid in ("region_next", "region_prev", "region_reviewed",
                    "region_unreviewed", "region_delete", "region_isolate"):
            self.act[aid].setEnabled(has_seg and getattr(self, "_region_active", False))
        self.btn_cleanup.setEnabled(has_img)
        self.brush_spin.setEnabled(has_img and self.controller.tool == "brush"
                                   if hasattr(self, "controller") else False)
        self._refresh_undo()

    @gui_guard
    def _edit_shortcuts(self):
        dlg = ShortcutsDialog(COMMANDS, self.act, self.settings, self)
        if dlg.exec():
            self._apply_shortcuts()

    @gui_guard
    def _about(self):
        QMessageBox.about(self, "About", about_html())

    # -- drag & drop -----------------------------------------------------
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    @gui_guard
    def dropEvent(self, ev):
        urls = ev.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if self.image is None:
            image = io.load_image(path)
            self._set_case(image, Segmentation.empty_like(image.shape), None)
            return
        box = QMessageBox(self)
        box.setWindowTitle("Load file as")
        box.setText(f"Load \u201c{os.path.basename(path)}\u201d as:")
        img_btn = box.addButton("Image", QMessageBox.ButtonRole.AcceptRole)
        seg_btn = box.addButton("Segmentation", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is img_btn:
            image = io.load_image(path)
            if self._guard_unsaved():
                self._set_case(image, Segmentation.empty_like(image.shape), None)
        elif clicked is seg_btn:
            seg = io.load_segmentation(path, self.image.shape, self.image.affine)
            if self._guard_unsaved():
                self._set_case(self.image, seg, path)

    # -- window state ----------------------------------------------------
    def _restore_window_state(self):
        geo = self.settings.value(config.SK_GEOMETRY)
        if geo is not None:
            self.restoreGeometry(geo)

    def closeEvent(self, ev):
        if not self._guard_unsaved():
            ev.ignore()
            return
        try:
            self.settings.setValue(config.SK_GEOMETRY, self.saveGeometry())
            self._autosave_timer.stop()
            self._idle_timer.stop()
            self._bg_timer.stop()
            self._vol_timer.stop()
            self._retire_session(remove=True)
            self.background.shutdown()
        except Exception:
            log.exception("Error during close")
        ev.accept()


def _btn(action):
    b = QToolButton(); b.setDefaultAction(action); b.setAutoRaise(True)
    return b
