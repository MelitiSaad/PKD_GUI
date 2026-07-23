"""Application-wide constants, paths, and settings keys.

Kept deliberately small and dependency-free so every other module can import it
without pulling in Qt.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "PKD Segmentation QC"
APP_ORG = "MayoClinic"
APP_ID = "pkdqc"
VERSION = "2.0.0"

# ---- filesystem ---------------------------------------------------------
def app_data_dir() -> Path:
    """Per-user writable directory for sessions, logs, and settings."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    d = base / APP_ID
    d.mkdir(parents=True, exist_ok=True)
    return d


def sessions_dir() -> Path:
    d = app_data_dir() / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = app_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- autosave / data safety --------------------------------------------
AUTOSAVE_INTERVAL_MS = 20_000       # periodic checkpoint cadence
AUTOSAVE_IDLE_MS = 2_500            # save this long after the last edit
AUTOSAVE_EVERY_N_EDITS = 25         # also save after this many edits
MAX_UNDO_BYTES = 512 * 1024 * 1024  # cap the in-memory undo history

# ---- editing defaults ---------------------------------------------------
DEFAULT_BRUSH_RADIUS = 4
MIN_BRUSH_RADIUS = 1
MAX_BRUSH_RADIUS = 80

# ---- volumetry ----------------------------------------------------------
MM3_PER_ML = 1000.0                 # 1 mL == 1000 mm^3

# ---- settings keys ------------------------------------------------------
SK_GEOMETRY = "window/geometry"
SK_STATE = "window/state"
SK_SHORTCUTS = "shortcuts/map"
SK_LAST_DIR = "io/last_dir"
SK_SHOW_3D = "view/show_3d"
SK_AUTOSAVE = "safety/autosave_enabled"
