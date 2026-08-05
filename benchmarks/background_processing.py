from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np

from pkdqc.core.background import ArraySnapshot, BackgroundTaskService, TaskTag
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.volume import ImageVolume
from pkdqc.core.volumetry import compute_volumes
from pkdqc.core import segops


def main():
    shape = (128, 128, 64)
    data = np.zeros(shape, np.uint16)
    data[30:80, 30:80, 10:40] = 1
    image = ImageVolume(np.ones(shape, np.float32), (1.2, 1.2, 2.5), np.diag([1.2, 1.2, 2.5, 1.0]))
    seg = Segmentation(data)
    svc = BackgroundTaskService(max_workers=2); svc.set_document("bench", seg.revision)
    t0 = time.perf_counter(); snap = ArraySnapshot.capture("bench", seg.revision, seg.data); t1 = time.perf_counter()
    volumes = compute_volumes(Segmentation(snap.data.copy()), image); t2 = time.perf_counter()
    grown = Segmentation(snap.data.copy()); segops.grow(grown, 1, 1, True, 0); t3 = time.perf_counter()
    for i in range(50):
        svc.submit_latest(TaskTag.make("bench", seg.revision, "volumetry", {"request": i}), lambda token, i=i: i, lambda value: None)
    print({
        "shape": shape,
        "snapshot_ms": (t1 - t0) * 1000,
        "snapshot_bytes": snap.nbytes,
        "volumetry_ms": (t2 - t1) * 1000,
        "morphology_ms": (t3 - t2) * 1000,
        "rapid_request_queue_size": svc.queue_size,
        "label1_mm3": next(v.mm3 for v in volumes if v.id == 1),
    })
    svc.shutdown()


if __name__ == "__main__":
    main()
