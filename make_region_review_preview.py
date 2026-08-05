"""Headless Region Review smoke preview.

This intentionally imports the Qt application and creates the Region Review
panel; in containers without libGL.so.1 it will fail before drawing, which should
be reported as an environmental limitation.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pkdqc.app import build_application
from pkdqc.ui.main_window import MainWindow


def main() -> int:
    app = build_application([])
    win = MainWindow(enable_3d=False)
    assert hasattr(win, "region_panel")
    win.region_panel.set_available(False)
    print("Region Review panel constructed")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
