"""Crash-safe sessions.

A session is bound to a case (image + segmentation). While it's open, the label
volume is checkpointed to per-user app-data as a fast, lossless ``.npy`` written
**atomically** (temp file + ``os.replace``). A ``clean_exit`` flag distinguishes
a normal close from a crash. On startup the app scans for sessions whose
``clean_exit`` is still false and offers to recover them.

This is intentionally decoupled from the export format: autosave is fast and
frequent; the user's explicit "Save" writes a proper NIfTI (see ``io.py``).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from ..config import sessions_dir
from .labels import LabelTable
from .segmentation import Segmentation


def _sid(image_path: str, seg_path: Optional[str]) -> str:
    key = f"{os.path.abspath(image_path)}|{os.path.abspath(seg_path) if seg_path else ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def _atomic_np_save(path: Path, arr: np.ndarray) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        np.save(f, arr, allow_pickle=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Session:
    def __init__(self, image_path: str, seg_path: Optional[str] = None):
        self.image_path = image_path
        self.seg_path = seg_path
        self.id = _sid(image_path, seg_path)
        self.dir = sessions_dir() / self.id
        self.labels_path = self.dir / "labels.npy"
        self.meta_path = self.dir / "meta.json"
        self._last_revision = -1

    def begin(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._write_meta(clean_exit=False, revision=0)

    def save(self, seg: Segmentation, force: bool = False) -> bool:
        """Checkpoint the label volume if it changed since the last checkpoint."""
        if not force and seg.revision == self._last_revision:
            return False
        _atomic_np_save(self.labels_path, seg.data)
        self._write_meta(clean_exit=False, revision=seg.revision)
        self._last_revision = seg.revision
        return True

    def mark_clean(self, remove: bool = True) -> None:
        try:
            self._write_meta(clean_exit=True, revision=self._last_revision)
            if remove and self.dir.exists():
                shutil.rmtree(self.dir, ignore_errors=True)
        except Exception:
            pass

    def _write_meta(self, clean_exit: bool, revision: int) -> None:
        meta = {
            "image_path": self.image_path,
            "seg_path": self.seg_path,
            "clean_exit": clean_exit,
            "revision": revision,
            "updated": time.time(),
        }
        _atomic_write_text(self.meta_path, json.dumps(meta, indent=2))


@dataclass
class Recoverable:
    session_id: str
    image_path: str
    seg_path: Optional[str]
    labels_path: str
    updated: float

    @property
    def age_str(self) -> str:
        secs = max(0, time.time() - self.updated)
        if secs < 90:
            return f"{int(secs)}s ago"
        if secs < 5400:
            return f"{int(secs / 60)} min ago"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.updated))


def find_recoverable() -> List[Recoverable]:
    out: List[Recoverable] = []
    base = sessions_dir()
    if not base.exists():
        return out
    for d in base.iterdir():
        meta_p = d / "meta.json"
        labels_p = d / "labels.npy"
        if not (meta_p.exists() and labels_p.exists()):
            continue
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if meta.get("clean_exit", True):
            continue
        if not os.path.exists(meta.get("image_path", "")):
            continue  # can't recover without the source image
        out.append(
            Recoverable(
                session_id=d.name,
                image_path=meta["image_path"],
                seg_path=meta.get("seg_path"),
                labels_path=str(labels_p),
                updated=float(meta.get("updated", 0.0)),
            )
        )
    out.sort(key=lambda r: r.updated, reverse=True)
    return out


def load_recovered_segmentation(rec: Recoverable) -> Segmentation:
    data = np.load(rec.labels_path, allow_pickle=False)
    return Segmentation(data, LabelTable.from_ids(np.unique(data)))


def discard(rec: Recoverable) -> None:
    shutil.rmtree(sessions_dir() / rec.session_id, ignore_errors=True)
