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

import logging
import os
import time
from typing import Optional

import numpy as np
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import (
    QComboBox, QDockWidget, QFileDialog, QHBoxLayout, QLabel, QMainWindow,
    QMenu, QMessageBox, QSlider, QSpinBox, QToolBar, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import config, icons, theme
from ..core import io
from ..core.history import History
from ..core.segmentation import Segmentation
from ..core.session import Session
from ..errors import gui_guard
from .contrast import ContrastDialog
from .dialogs import ShortcutsDialog, about_html
from .label_panel import LabelPanel
from .ortho import OrthoView
from .tools import ToolController
from . import volume_view

log = logging.getLogger(__name__)

# modal tools only
TOOLS = [
    ("crosshair", "Crosshair", "crosshair", "V"),
    ("pan", "Pan", "navigate", "H"),
    ("brush", "Brush", "brush", "B"),
    ("fill", "Fill", "fill", "F"),
]

TOOL_HINTS = {
    "crosshair": "Left-drag moves the crosshair · click selects the object under it "
                 "· right-drag zooms · middle-drag pans",
    "pan": "Left-drag moves the image · right-drag zooms · wheel changes slice",
    "brush": "Left paints the active object · right erases · Alt+wheel or [ ] resizes",
    "fill": "Left fills the connected region · right clears it",
}

# one-shot operations (never in the tool rail)
OPERATIONS = [
    ("grow", "Grow", "grow", "G"),
    ("shrink", "Shrink", "shrink", "Shift+G"),
    ("islands", "Remove islands", "islands", "K"),
    ("holes", "Fill holes", "holes", "J"),
    ("interpolate", "Interpolate slices", "interpolate", "I"),
]

_SHORTCUTS = {
    **{tid: (label, key) for tid, label, _ic, key in TOOLS},
    **{oid: (label, key) for oid, label, _ic, key in OPERATIONS},
    "undo": ("Undo", "Ctrl+Z"),
    "redo": ("Redo", "Ctrl+Y"),
    "open_image": ("Open image", "Ctrl+O"),
    "load_seg": ("Load segmentation", "Ctrl+L"),
    "save": ("Save segmentation", "Ctrl+S"),
    "new_seg": ("New segmentation", "Ctrl+N"),
    "next_edited": ("Next edited slice", "."),
    "prev_edited": ("Previous edited slice", ","),
    "brush_minus": ("Smaller brush", "["),
    "brush_plus": ("Larger brush", "]"),
    "brush_threshold": ("Threshold brush", "T"),
    "brush_protect": ("Protect labels", ""),
    "reset_view": ("Reset zoom", "Ctrl+0"),
    "update_3d": ("Update 3D", "F5"),
    "contrast": ("Contrast\u2026", "C"),
    "remove_unused": ("Remove unused objects", "Ctrl+Shift+R"),
    "continuous_3d": ("Continuous 3D update", ""),
    "axes_3d": ("Show 3D axes", ""),
    "layout_grid": ("2\u00d72", "1"),
    "layout_axial": ("Axial", "2"),
    "layout_coronal": ("Coronal", "3"),
    "layout_sagittal": ("Sagittal", "4"),
    "layout_3d": ("3D", "5"),
}

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
        self._edits_since_save = 0
        self._contrast_dlg: Optional[ContrastDialog] = None
        self._enable_3d = enable_3d and volume_view.available()

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
        self._vol_timer = QTimer(self); self._vol_timer.setSingleShot(True)
        self._vol_timer.timeout.connect(self.panel.recompute)

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
        self._mk("new_seg")
        self._mk("next_edited", "next_edit"); self._mk("prev_edited", "prev_edit")
        self._mk("brush_minus"); self._mk("brush_plus")
        self._mk("reset_view", "reset_view"); self._mk("update_3d", "cube")
        self._mk("contrast", "threshold"); self._mk("remove_unused")
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
        for aid in ("save", "new_seg"):
            m_file.addAction(self.act[aid])
        m_file.addSeparator()
        act_quit = QAction("Quit", self); act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close); m_file.addAction(act_quit)

        m_edit = mb.addMenu("&Edit")
        m_edit.addAction(self.act["undo"]); m_edit.addAction(self.act["redo"])

        m_seg = mb.addMenu("&Segmentation")
        for aid in ("load_seg", "save", "new_seg"):
            m_seg.addAction(self.act[aid])
        m_seg.addSeparator()
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
        m_view.addSeparator()
        for aid in ("update_3d", "continuous_3d", "axes_3d"):
            m_view.addAction(self.act[aid])

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
        self.btn_cleanup.setText("Clean up")
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

    def _build_statusbar(self):
        sb = self.statusBar()
        self.lbl_coord = QLabel(""); self.lbl_tool = QLabel(""); self.lbl_hint = QLabel("")
        self.lbl_saved = QLabel("")
        for w in (self.lbl_coord, self.lbl_tool, self.lbl_hint):
            sb.addWidget(w)
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
        self.act["continuous_3d"].toggled.connect(self._toggle_continuous_3d)
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
        self.panel.activeLabelChanged.connect(lambda _id: self.ortho.redraw_overlay())
        self.panel.overlayChanged.connect(self._on_overlay_changed)
        self.panel.deleteLabelRequested.connect(self._delete_label)

    def _apply_shortcuts(self):
        stored = self.settings.value(config.SK_SHORTCUTS, {}) or {}
        for aid, (_label, default) in _SHORTCUTS.items():
            key = stored.get(aid, default) if isinstance(stored, dict) else default
            if key:
                self.act[aid].setShortcut(QKeySequence(key))

    # ================================================================ tools
    @gui_guard
    def _set_tool(self, name):
        self.controller.set_tool(name)
        self.act[name].setChecked(True)
        self.lbl_tool.setText(f"  {_SHORTCUTS[name][0]}")
        self.lbl_hint.setText("   " + TOOL_HINTS.get(name, ""))
        is_brush = name == "brush"
        self.brush_spin.setEnabled(is_brush)
        self.brush_mode.setEnabled(is_brush)
        self.act["brush_protect"].setEnabled(is_brush)

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
        self.statusBar().showMessage(f"Selected object: {self.panel.label_name(lid)} (#{lid})", 3000)

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
        image = io.load_image(path)
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
        self._set_case(self.image, seg, path)
        self.statusBar().showMessage(f"Overlaid {os.path.basename(path)}", 4000)

    @gui_guard
    def _new_seg(self):
        if self.image is not None:
            self._set_case(self.image, Segmentation.empty_like(self.image.shape), None)

    @gui_guard
    def _save(self):
        if self.image is None or self.seg is None:
            return
        default = self.settings.value(config.SK_LAST_DIR, "")
        path, _ = QFileDialog.getSaveFileName(self, "Save segmentation",
                                              os.path.join(default, "segmentation.nii.gz"),
                                              "NIfTI (*.nii.gz *.nii)")
        if not path:
            return
        io.save_segmentation(self.seg, self.image, path)
        self.seg.clear_dirty()
        self._set_saved_state("saved", extra=f"to {os.path.basename(path)}")
        self.statusBar().showMessage(f"Saved {os.path.basename(path)}", 4000)

    def _pick_open(self, title, filt):
        start = self.settings.value(config.SK_LAST_DIR, "")
        path, _ = QFileDialog.getOpenFileName(self, title, start, filt)
        if path:
            self.settings.setValue(config.SK_LAST_DIR, os.path.dirname(path))
        return path

    # ================================================================ case
    def _set_case(self, image, seg, seg_path):
        self.image = image
        self.seg = seg
        self.history = History(seg)
        self.history.on_change = self._refresh_undo
        self.controller.set_context(image, seg, self.history)
        self.ortho.set_data(image, seg)
        self.panel.set_context(image, seg)
        self.slice_slider.setRange(0, image.n_slices - 1)
        self.slice_slider.setValue(self.ortho.z)
        self.session = Session(image.path, seg_path)
        self.session.begin()
        self._edits_since_save = 0
        self._contrast_dlg = None
        self._refresh_undo()
        self._update_enabled()
        self.panel.recompute()
        self._set_saved_state("saved")
        QTimer.singleShot(200, self.ortho.refresh_3d)  # one-time build; not on every edit

    def load_recovered(self, image, seg, session_id):
        self._set_case(image, seg, seg_path=None)
        self.seg.dirty = True
        self._set_saved_state("unsaved", extra="recovered")

    # ================================================================ labels
    @gui_guard
    def _delete_label(self, lid):
        if self.seg is None or self.history is None:
            return
        if len(self.seg.labels) <= 1:
            QMessageBox.information(self, "Cannot remove", "At least one object must remain.")
            return
        from ..core import commands
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
        self._set_saved_state("unsaved")
        self._idle_timer.start(config.AUTOSAVE_IDLE_MS)
        self._schedule_volumes()
        if self._edits_since_save >= config.AUTOSAVE_EVERY_N_EDITS:
            self._autosave()

    def _on_overlay_changed(self):
        self.ortho.redraw_overlay()
        self._schedule_volumes()

    def _schedule_volumes(self): self._vol_timer.start(350)

    def _autosave(self):
        if self.session is None or self.seg is None:
            return
        try:
            if self.session.save(self.seg):
                self._edits_since_save = 0
                self._set_saved_state("autosaved")
        except Exception:
            log.exception("Autosave failed")
            self._set_saved_state("autosave error")

    def _set_saved_state(self, state, extra=""):
        colors = {"saved": theme.SUCCESS, "autosaved": theme.SUCCESS, "unsaved": theme.WARNING,
                  "autosave error": theme.DANGER, "no data": theme.TEXT_FAINT}
        text = {"saved": "All changes saved", "autosaved": "Autosaved",
                "unsaved": "Unsaved changes", "autosave error": "Autosave failed",
                "no data": "No segmentation loaded"}.get(state, state)
        stamp = time.strftime("%H:%M:%S") if state in ("saved", "autosaved") else ""
        suffix = f" · {extra}" if extra else (f" · {stamp}" if stamp else "")
        self.lbl_saved.setText(f"\u25cf  {text}{suffix}  ")
        self.lbl_saved.setStyleSheet(f"color: {colors.get(state, theme.TEXT_MUTED)};")

    # ================================================================ misc
    def _refresh_undo(self):
        self.act["undo"].setEnabled(bool(self.history and self.history.can_undo))
        self.act["redo"].setEnabled(bool(self.history and self.history.can_redo))

    def _update_enabled(self):
        has_img = self.image is not None
        for aid in list(_LAYOUT_OF) + [t[0] for t in TOOLS] + [o[0] for o in OPERATIONS] + [
                "save", "new_seg", "next_edited", "prev_edited", "reset_view", "contrast",
                "remove_unused", "update_3d", "load_seg", "brush_threshold", "brush_protect"]:
            self.act[aid].setEnabled(has_img)
        self.btn_cleanup.setEnabled(has_img)
        self.brush_spin.setEnabled(has_img and self.controller.tool == "brush"
                                   if hasattr(self, "controller") else False)
        self._refresh_undo()

    @gui_guard
    def _edit_shortcuts(self):
        rows = [(aid, _SHORTCUTS[aid][0], self.act[aid]) for aid in _SHORTCUTS if _SHORTCUTS[aid][1]]
        ShortcutsDialog(rows, self.settings, self).exec()

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
            self._set_case(image, Segmentation.empty_like(image.shape), None)
        elif clicked is seg_btn:
            seg = io.load_segmentation(path, self.image.shape, self.image.affine)
            self._set_case(self.image, seg, path)

    # -- window state ----------------------------------------------------
    def _restore_window_state(self):
        geo = self.settings.value(config.SK_GEOMETRY)
        if geo is not None:
            self.restoreGeometry(geo)

    def closeEvent(self, ev):
        try:
            self.settings.setValue(config.SK_GEOMETRY, self.saveGeometry())
            if self.session is not None:
                self._autosave()
                self.session.mark_clean()
        except Exception:
            log.exception("Error during close")
        super().closeEvent(ev)


def _btn(action):
    b = QToolButton(); b.setDefaultAction(action); b.setAutoRaise(True)
    return b
