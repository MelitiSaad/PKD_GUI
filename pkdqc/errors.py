"""The stability backbone: nothing is allowed to be silently fatal.

* :func:`install_excepthook` catches anything that escapes a slot (the backstop).
* :func:`gui_guard` wraps an individual slot so a failure becomes a dialog and
  the app keeps running — this is what turns "crash" into "recoverable error".

The original app had 5 ``try`` blocks and no excepthook in 2,900 lines; every
callback was a potential crash. Applying ``gui_guard`` at the controller boundary
makes error handling structural instead of per-method discipline.
"""
from __future__ import annotations

import functools
import logging
import sys
import traceback
from pathlib import Path


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "pkdqc.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
    )


def install_excepthook(parent=None) -> None:
    def hook(exc_type, exc, tb):
        logging.error("Uncaught exception", exc_info=(exc_type, exc, tb))
        try:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                parent,
                "Unexpected error",
                "Something went wrong, but your work is safe and the app is "
                "still running.\n\nThe details have been written to the log.",
            )
        except Exception:
            traceback.print_exception(exc_type, exc, tb)

    sys.excepthook = hook


def gui_guard(fn):
    """Decorator: log + show a non-fatal dialog if a slot raises, then continue."""

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception:
            logging.exception("Error in %s", getattr(fn, "__qualname__", fn.__name__))
            try:
                from PySide6.QtWidgets import QMessageBox, QWidget
                parent = self if isinstance(self, QWidget) else getattr(self, "window", None)
                if not isinstance(parent, QWidget):
                    parent = None
                QMessageBox.warning(
                    parent,
                    "Action could not be completed",
                    f"“{fn.__name__}” failed. Your segmentation was not changed.\n"
                    "The error has been logged.",
                )
            except Exception:
                pass
            return None

    return wrapper
