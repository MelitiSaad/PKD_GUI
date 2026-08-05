"""Application bootstrap.

Sets up logging, the excepthook backstop, the dark theme, offers crash recovery,
then shows the main window.
"""
from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from . import config, theme
from .core import io
from .errors import install_excepthook, setup_logging
from .ui.dialogs import RecoveryDialog
from .ui.main_window import MainWindow

log = logging.getLogger(__name__)


def build_application(argv=None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.APP_ORG)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    app.setFont(QFont("Inter", 10))
    return app


def _offer_recovery(win: MainWindow) -> None:
    from .core import session
    try:
        recs = session.find_recoverable()
    except Exception:
        log.exception("Recovery scan failed")
        return
    if not recs:
        return
    dlg = RecoveryDialog(recs, win)
    dlg.exec()
    rec = dlg.chosen
    if rec is None:
        return
    if dlg.action == "recover":
        try:
            image = io.load_image(rec.image_path, source_identity=session.recovery_source_identity(rec))
            session.validate_recovery_image(rec, image)
            seg = session.load_recovered_segmentation(rec)
            if seg.data.shape == image.shape:
                win.load_recovered(image, seg, rec)
                session.discard(rec)
            else:
                log.warning("Recovered labels don't match image shape; skipping")
        except Exception:
            log.exception("Recovery failed")
    elif dlg.action == "discard":
        session.discard(rec)


def run() -> int:
    setup_logging(config.log_dir())
    app = build_application()
    install_excepthook()
    win = MainWindow(enable_3d=True)
    win.show()
    _offer_recovery(win)
    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
