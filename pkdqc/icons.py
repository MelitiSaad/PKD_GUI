"""Crisp, dependency-free line icons.

Each icon is an SVG template with a ``{c}`` colour placeholder, rasterised to a
``QIcon`` at request time. No icon-font dependency, no binary assets — the whole
visual language lives here and re-tints cleanly for the dark theme.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_SVG = {
    "navigate": '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
    "crosshair": '<path d="M12 2v6M12 16v6M2 12h6M16 12h6"/><circle cx="12" cy="12" r="3.4"/>',
    "brush": '<path d="M14.5 6.5l3 3"/><path d="M16 5l3 3-8.5 8.5-3-3z"/><path d="M7.5 13.5C5 15 5 18 3.5 20.5 6 20 9 20 10.5 17.5"/>',
    "lasso": '<path d="M6 5c5-4 13 0 11 6-1 4-8 5-10 2-2-3 2-5 5-3 3 2 1 6-2 8"/><path d="M10 18l-2 3"/>',
    "eraser": '<path d="M8 20h11"/><path d="M14 6l4 4-7 7H8l-3-3z"/>',
    "fill": '<path d="M11 4l7 7-6 6a2 2 0 0 1-3 0l-4-4a2 2 0 0 1 0-3z"/><path d="M11 4L9 2"/><path d="M19 15c1 1 2 2 2 3a2 2 0 0 1-4 0c0-1 1-2 2-3z" fill="{c}"/>',
    "grow": '<path d="M9 4H4v5M15 4h5v5M9 20H4v-5M15 20h5v-5"/><path d="M12 8v8M8 12h8"/>',
    "shrink": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><path d="M8 12h8"/>',
    "islands": '<circle cx="9" cy="13" r="5"/><circle cx="18" cy="6" r="1.4" fill="{c}"/><circle cx="19.5" cy="15" r="1" fill="{c}"/><path d="M16 4.5l3.5 3.5"/>',
    "holes": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.2" fill="{c}"/>',
    "interpolate": '<path d="M4 6h16"/><path d="M4 18h16"/><path d="M7 12h2M11 12h2M15 12h2"/>',
    "threshold": '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="{c}" stroke="none"/>',
    "undo": '<path d="M4 12h11a4 4 0 0 1 0 8h-3"/><path d="M8 8l-4 4 4 4"/>',
    "redo": '<path d="M20 12H9a4 4 0 0 0 0 8h3"/><path d="M16 8l4 4-4 4"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    "save": '<path d="M12 3v11"/><path d="M8 11l4 4 4-4"/><path d="M5 20h14"/>',
    "measure": '<path d="M17 5H7l5.5 7L7 19h10"/>',
    "cube": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "bookmark": '<path d="M7 4h10v16l-5-4-5 4z"/>',
    "next_edit": '<path d="M6 5l8 7-8 7z"/><path d="M18 5v14"/>',
    "prev_edit": '<path d="M18 5l-8 7 8 7z"/><path d="M6 5v14"/>',
    "reset_view": '<path d="M4 9a8 8 0 1 1-1 4"/><path d="M4 4v5h5"/>',
    "compare": '<path d="M12 4v16"/><path d="M4 8h4M4 12h4M4 16h4"/><path d="M16 8h4M16 12h4M16 16h4"/>',
    "overlay": '<circle cx="10" cy="12" r="6"/><circle cx="14" cy="12" r="6"/>',
}


def _svg_document(name: str, color: str) -> str:
    inner = _SVG[name].replace("{c}", color)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.9" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )


@lru_cache(maxsize=256)
def pixmap(name: str, color: str = theme.TEXT, size: int = 22, scale: int = 2) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg_document(name, color).encode("utf-8")))
    img = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, size * scale, size * scale))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(scale)
    return pm


@lru_cache(maxsize=256)
def icon(name: str, color: str = theme.TEXT, size: int = 22) -> QIcon:
    return QIcon(pixmap(name, color, size))
