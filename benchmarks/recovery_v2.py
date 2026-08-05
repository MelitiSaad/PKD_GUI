"""Small deterministic Recovery v2 write/validate/load benchmark."""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pkdqc.core.segmentation import Segmentation
from pkdqc.core.session import Session, find_recoverable, load_recovered_segmentation
from pkdqc.core.volume import ImageVolume

with tempfile.TemporaryDirectory() as root:
    os.environ["XDG_DATA_HOME"] = root
    source = Path(root) / "synthetic.nii.gz"; source.write_bytes(b"synthetic-source")
    image = ImageVolume(np.zeros((128, 128, 32), np.float32), (1, 1, 2), np.diag([1, 1, 2, 1]), str(source))
    seg = Segmentation(np.zeros(image.shape, np.uint16)); seg.data[20:80, 20:80, 5:25] = 1
    seg.revision = 1; seg.dirty = True
    session = Session(image)
    start = time.perf_counter(); session.save(seg, saved_revision=0, dirty=True)
    write_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter(); records = find_recoverable()
    validate_ms = (time.perf_counter() - start) * 1000
    start = time.perf_counter(); load_recovered_segmentation(records[0])
    load_ms = (time.perf_counter() - start) * 1000
    storage = sum(p.stat().st_size for p in session.dir.rglob("*") if p.is_file())
    print(json.dumps({"shape": image.shape, "write_ms": write_ms,
                      "validate_ms": validate_ms, "load_ms": load_ms,
                      "generation_bytes": storage}, indent=2))
