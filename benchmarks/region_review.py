"""Deterministic Region Review benchmark.

By default this avoids allocating a 512 x 512 x 256 volume. Pass ``--large`` to
measure a full-size snapshot copy in an environment with enough memory.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from pkdqc.core.background import ArraySnapshot
from pkdqc.core.geometry import ImageGeometry
from pkdqc.core.history import History
from pkdqc.core.labels import LabelTable
from pkdqc.core.regions import (
    RegionReviewState, build_region_index, delete_region_checked, load_review_progress,
    progress_identity, save_review_progress,
)
from pkdqc.core.segmentation import Segmentation


def geometry(shape):
    return ImageGeometry.from_affine(shape, np.diag([1.0, 1.0, 2.0, 1.0]))


def scattered(shape=(128, 128, 64), n=300, individual=False, sparse=False):
    data = np.zeros(shape, dtype=np.uint16)
    lids = []
    for r in range(n):
        i = 2 + (r * 7) % (shape[0] - 4)
        j = 2 + (r * 13) % (shape[1] - 4)
        k = 1 + (r * 5) % (shape[2] - 2)
        lid = (r + 1) if individual else 1
        if sparse and individual:
            lid = 50000 + r
        data[i, j, k] = np.uint16(lid)
        lids.append(lid)
    return data, sorted(set(lids))


def measure(name, fn):
    start = time.perf_counter()
    value = fn()
    ms = (time.perf_counter() - start) * 1000
    print(f"{name}: {ms:.2f} ms")
    return value, ms


def main(argv=None):
    args = argparse.ArgumentParser()
    args.add_argument("--large", action="store_true", help="allocate and snapshot a 512x512x256 uint16 array")
    ns = args.parse_args(argv)

    data, labels = scattered(n=300)
    idx, _ = measure("one-color 300-region index", lambda: build_region_index(data, LabelTable.from_ids(labels), geometry(data.shape)))
    state = RegionReviewState(included_labels=set(labels))
    _, _ = measure("navigation next", lambda: state.next(idx))
    _, _ = measure("review + advance", lambda: state.mark_reviewed_and_advance(idx))
    seg = Segmentation(data.copy(), LabelTable.from_ids(labels)); hist = History(seg)
    _, _ = measure("component delete", lambda: hist.push(delete_region_checked(seg, idx, idx.records[0])))
    _, _ = measure("undo delete", lambda: hist.undo())

    small_edit = data.copy(); small_edit[2, 2, 2] = 1
    measure("small-edit full rebuild fallback", lambda: build_region_index(small_edit, LabelTable.from_ids(labels), geometry(data.shape)))
    large_edit = np.zeros_like(data); large_edit[8:96, 8:96, 8:48] = 1
    measure("large-edit full rebuild", lambda: build_region_index(large_edit, LabelTable.from_ids(labels), geometry(data.shape)))

    dense = np.zeros((96, 96, 48), dtype=np.uint16); dense[8:88, 8:88, 8:40] = 1
    didx, _ = measure("dense foreground index", lambda: build_region_index(dense, LabelTable.from_ids([1]), geometry(dense.shape)))
    dense_bytes = sum(r.flat_indices.nbytes for r in didx.records)

    indiv, ilabels = scattered(n=300, individual=True)
    measure("individual-label 300-region index", lambda: build_region_index(indiv, LabelTable.from_ids(ilabels), geometry(indiv.shape)))
    mixed, mlabels = scattered(n=1000, individual=True, sparse=True)
    mixed[mixed > 50050] = 1
    mlabels = sorted(int(v) for v in np.unique(mixed) if int(v) != 0)
    midx, _ = measure("mixed/sparse 1000-region index", lambda: build_region_index(mixed, LabelTable.from_ids(mlabels), geometry(mixed.shape)))
    snap, _ = measure("snapshot capture", lambda: ArraySnapshot.capture("bench", 0, mixed))
    component_bytes = sum(r.flat_indices.nbytes for r in midx.records)

    identity = progress_identity(segmentation_path="/not/stored/seg.nii.gz", shape=mixed.shape, affine=geometry(mixed.shape).affine, dtype="uint16", labels=mlabels)
    tmp = Path("/tmp/pkdqc_region_review_bench_progress.json")
    measure("progress write", lambda: save_review_progress(identity, state, path=tmp))
    measure("progress load", lambda: load_review_progress(identity, path=tmp))
    tmp.unlink(missing_ok=True)

    print(f"snapshot memory: {snap.nbytes / 1024 / 1024:.2f} MiB")
    print(f"sparse component flat-index memory: {component_bytes / 1024 / 1024:.2f} MiB")
    print(f"dense component flat-index memory: {dense_bytes / 1024 / 1024:.2f} MiB")
    large_bytes = 512 * 512 * 256 * np.dtype(np.uint16).itemsize
    print(f"512x512x256 uint16 snapshot estimate: {large_bytes / 1024 / 1024:.2f} MiB")
    if ns.large:
        large = np.zeros((512, 512, 256), dtype=np.uint16)
        large[128:384, 128:384, 96:160] = 1
        lsnap, _ = measure("large snapshot capture", lambda: ArraySnapshot.capture("large", 0, large))
        print(f"large snapshot memory: {lsnap.nbytes / 1024 / 1024:.2f} MiB")
    else:
        print("large snapshot capture: skipped (pass --large to allocate)")


if __name__ == "__main__":
    main()
