"""A modern, flat dark theme.

One palette drives a comprehensive stylesheet so every widget — toolbar, panels,
tables, sliders, scrollbars, dialogs — reads as one cohesive 2026 app rather
than default Qt chrome.
"""
from __future__ import annotations

# ---- palette ------------------------------------------------------------
BASE = "#15171C"          # window background
SURFACE = "#1D2027"       # panels / docks
SURFACE_2 = "#252932"     # raised controls, table
SURFACE_3 = "#2E333E"     # hover
BORDER = "#30353F"
BORDER_SOFT = "#262A33"
TEXT = "#E6E9EF"
TEXT_MUTED = "#98A2B3"
TEXT_FAINT = "#6B7480"
ACCENT = "#5B8DEF"
ACCENT_HOVER = "#6F9CF2"
ACCENT_PRESSED = "#4A7CE0"
ACCENT_SOFT = "#22314E"   # translucent-looking accent fill for checked tools
DANGER = "#EF5B5B"
SUCCESS = "#37C978"
WARNING = "#E7A83A"

FONT_STACK = '"Inter", "Segoe UI", "SF Pro Text", "Helvetica Neue", Arial, sans-serif'


def palette():
    """A dark Fusion palette so even unstyled widgets default to dark."""
    from PySide6.QtGui import QColor, QPalette

    def c(hexstr):
        return QColor(hexstr)

    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, c(BASE))
    p.setColor(QPalette.ColorRole.WindowText, c(TEXT))
    p.setColor(QPalette.ColorRole.Base, c(SURFACE_2))
    p.setColor(QPalette.ColorRole.AlternateBase, c(SURFACE))
    p.setColor(QPalette.ColorRole.ToolTipBase, c(SURFACE_3))
    p.setColor(QPalette.ColorRole.ToolTipText, c(TEXT))
    p.setColor(QPalette.ColorRole.Text, c(TEXT))
    p.setColor(QPalette.ColorRole.Button, c(SURFACE_2))
    p.setColor(QPalette.ColorRole.ButtonText, c(TEXT))
    p.setColor(QPalette.ColorRole.BrightText, c("#FFFFFF"))
    p.setColor(QPalette.ColorRole.Link, c(ACCENT))
    p.setColor(QPalette.ColorRole.Highlight, c(ACCENT))
    p.setColor(QPalette.ColorRole.HighlightedText, c("#FFFFFF"))
    p.setColor(QPalette.ColorRole.PlaceholderText, c(TEXT_MUTED))

    disabled = QPalette.ColorGroup.Disabled
    p.setColor(disabled, QPalette.ColorRole.Text, c(TEXT_FAINT))
    p.setColor(disabled, QPalette.ColorRole.ButtonText, c(TEXT_FAINT))
    p.setColor(disabled, QPalette.ColorRole.WindowText, c(TEXT_FAINT))
    return p


def stylesheet() -> str:
    return f"""
* {{
    font-family: {FONT_STACK};
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}
QMainWindow, QDialog {{ background: {BASE}; }}
QWidget#Panel, QDockWidget > QWidget {{ background: {SURFACE}; }}

/* ---- headings & labels ---- */
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 15px; font-weight: 600; color: {TEXT}; }}
QLabel[role="subtitle"] {{ font-size: 11px; color: {TEXT_MUTED};
    text-transform: uppercase; letter-spacing: 1px; }}
QLabel[role="muted"] {{ color: {TEXT_MUTED}; }}
QLabel[role="metric"] {{ font-size: 22px; font-weight: 700; color: {TEXT}; }}
QLabel[role="metricUnit"] {{ font-size: 12px; color: {TEXT_MUTED}; }}
QLabel[role="activeObject"] {{ background: {ACCENT_SOFT}; border: 1px solid {ACCENT};
    border-radius: 8px; padding: 8px 10px; color: {TEXT}; font-weight: 600; }}
QLabel#EmptyState {{ color: {TEXT_MUTED}; font-size: 15px; line-height: 1.5; }}

/* ---- buttons ---- */
QPushButton {{
    background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 7px 14px; color: {TEXT};
}}
QPushButton:hover {{ background: {SURFACE_3}; border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton:disabled {{ color: {TEXT_FAINT}; border-color: {BORDER_SOFT}; }}
QPushButton[accent="true"] {{
    background: {ACCENT}; border: none; color: white; font-weight: 600; }}
QPushButton[accent="true"]:hover {{ background: {ACCENT_HOVER}; }}
QPushButton[accent="true"]:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton[danger="true"]:hover {{ border-color: {DANGER}; color: {DANGER}; }}

/* ---- tool buttons (left rail) ---- */
QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: 10px; padding: 8px; margin: 1px; }}
QToolButton:hover {{ background: {SURFACE_3}; }}
QToolButton:checked {{ background: {ACCENT_SOFT}; border: 1px solid {ACCENT}; }}
QToolButton:disabled {{ opacity: 0.4; }}

/* ---- toolbars ---- */
QToolBar {{ background: {SURFACE}; border: none; spacing: 4px; padding: 4px; }}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 6px 6px; }}

/* ---- line edits / spin ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 7px; padding: 5px 8px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_2}; border: 1px solid {BORDER};
    selection-background-color: {ACCENT}; border-radius: 6px; }}

/* ---- checkboxes ---- */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {BORDER}; background: {SURFACE_2}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT};
    image: none; }}

/* ---- sliders ---- */
QSlider::groove:horizontal {{ height: 4px; background: {SURFACE_3};
    border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXT}; width: 14px; height: 14px;
    margin: -6px 0; border-radius: 7px; }}
QSlider::handle:horizontal:hover {{ background: white; }}

/* ---- lists ---- */
QListWidget {{
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 4px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; color: {TEXT}; }}
QListWidget::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
QListWidget::item:hover {{ background: {SURFACE_3}; }}

/* ---- tables ---- */
QTableWidget, QTableView {{
    background: {SURFACE_2}; alternate-background-color: {SURFACE};
    border: 1px solid {BORDER}; border-radius: 8px; gridline-color: {BORDER_SOFT};
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QHeaderView::section {{
    background: {SURFACE}; color: {TEXT_MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 6px 8px; font-weight: 600; }}
QTableWidget::item {{ padding: 4px 6px; }}
QTableWidget::item:selected {{ background: {ACCENT_SOFT}; }}

/* ---- scrollbars ---- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE_3}; border-radius: 5px;
    min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_FAINT}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {SURFACE_3}; border-radius: 5px;
    min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---- group boxes / frames ---- */
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 10px;
    margin-top: 14px; padding-top: 10px; background: {SURFACE}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px;
    color: {TEXT_MUTED}; font-weight: 600; }}
QFrame[role="card"] {{ background: {SURFACE}; border: 1px solid {BORDER};
    border-radius: 12px; }}
QFrame[role="divider"] {{ background: {BORDER}; max-height: 1px; }}

/* ---- docks / splitter / status ---- */
QDockWidget {{ titlebar-close-icon: none; color: {TEXT_MUTED}; }}
QDockWidget::title {{ background: {SURFACE}; padding: 8px 12px;
    border-bottom: 1px solid {BORDER}; }}
QSplitter::handle {{ background: {BASE}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER};
    color: {TEXT_MUTED}; }}
QStatusBar QLabel {{ color: {TEXT_MUTED}; }}
QStatusBar::item {{ border: none; }}

/* ---- tooltip / menu ---- */
QToolTip {{ background: {SURFACE_3}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 8px; }}
QMenu {{ background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}
"""
