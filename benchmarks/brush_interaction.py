"""Developer-only brush interaction benchmark.

Exercises the same plane mapping, batched ``StrokeRecorder`` stamping, command
commit, and label-overlay materialisation used by a live brush.  It reports a
"before" presentation model (full overlay on every pointer event) beside the
current coalesced model (one overlay per event-loop frame).  Qt upload timing is
reported separately when a desktop Qt/OpenGL stack is available; this CI image
does not provide ``libGL.so.1``.

Run: ``python benchmarks/brush_interaction.py --json benchmarks/results.json``
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# Permit direct execution from the repository root without installing a wheel.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pkdqc.core.commands import StrokeRecorder
from pkdqc.core.planes import PLANES, AXIAL
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.segops import disk_offsets


def percentile(samples, q):
    return float(np.percentile(np.asarray(samples, dtype=float), q)) if samples else 0.0


def run_case(size: int, radius: int, steps: int, erase: bool, full_per_event: bool):
    data = np.zeros((size, size, 8), dtype=np.uint16)
    if erase:
        data[:, :, 4] = 1
    seg, plane, cursor = Segmentation(data), PLANES[AXIAL], [size // 2, size // 2, 4]
    lut = seg.labels.lut()
    rec = StrokeRecorder(seg, "erase" if erase else "paint")
    frames, stamp_ms, overlay_ms, changed = [], [], [], 0
    dv, dh = disk_offsets(radius)
    centres = np.linspace(radius + 2, size - radius - 3, steps).astype(np.intp)
    for index, h in enumerate(centres):
        start = time.perf_counter()
        vv = np.full(dv.size, size // 2, dtype=np.intp) + dv
        hh = h + dh
        ii, jj, kk = plane.disp_to_vox_arrays(vv, hh, cursor, seg.data.shape)
        t0 = time.perf_counter()
        before = rec._orig.__len__()
        rec.stamp_voxels(ii, jj, kk, 0 if erase else 1)
        changed += len(rec._orig) - before
        stamp_ms.append((time.perf_counter() - t0) * 1e3)
        # This is the NumPy/LUT materialisation performed before graphics upload.
        if full_per_event or index == len(centres) - 1:
            t0 = time.perf_counter()
            labels = plane.slice2d(seg.data, cursor)
            _rgba = lut[np.minimum(labels, len(lut) - 1)]
            overlay_ms.append((time.perf_counter() - t0) * 1e3)
        frames.append((time.perf_counter() - start) * 1e3)
    t0 = time.perf_counter(); cmd = rec.commit(); commit_ms = (time.perf_counter() - t0) * 1e3
    return {
        "slice": size, "brush_radius": radius, "operation": "erase" if erase else "paint",
        "pointer_events": steps, "presentation": "full_each_event" if full_per_event else "coalesced",
        "changed_voxels": changed, "frame_ms_median": percentile(frames, 50),
        "frame_ms_p95": percentile(frames, 95), "stamp_ms_median": percentile(stamp_ms, 50),
        "overlay_numpy_lut_ms_median": percentile(overlay_ms, 50), "undo_commit_ms": commit_ms,
        "command_bytes": cmd.nbytes if cmd else 0,
    }


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--json")
    args = parser.parse_args()
    rows = []
    for size in (512, 1024):
        for radius in (4, 16, 40):
            for erase in (False, True):
                for steps in (12, 96):  # short and long strokes
                    rows.extend(run_case(size, radius, steps, erase, full) for full in (True, False))
    print(json.dumps(rows, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(rows, out, indent=2)


if __name__ == "__main__":
    main()
