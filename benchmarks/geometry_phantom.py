from __future__ import annotations

import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import nibabel as nib

from pkdqc.core import io
from pkdqc.core.geometry import markers_for_plane
from pkdqc.core.planes import PLANES
from pkdqc.core.segmentation import Segmentation


def main():
    shape = (64, 80, 48)
    affine = np.diag([1.2, 0.8, 3.0, 1.0])
    data = np.zeros(shape, np.float32)
    data[-2, 2, 2] = 10; data[2, -2, 2] = 20; data[2, 2, -2] = 30
    with tempfile.TemporaryDirectory() as d:
        imgp = f"{d}/phantom.nii.gz"; segp = f"{d}/phantom_seg.nii.gz"
        nib.save(nib.Nifti1Image(data, affine), imgp)
        t0 = time.perf_counter(); image = io.load_image(imgp); t1 = time.perf_counter()
        seg = Segmentation.empty_like(image.shape); seg.data[32, 40, 24] = 7
        io.save_segmentation(seg, image, segp); t2 = time.perf_counter()
        reloaded = io.load_segmentation(segp, image.shape, image.affine); t3 = time.perf_counter()
        print({
            "load_ms": (t1 - t0) * 1000,
            "save_ms": (t2 - t1) * 1000,
            "reload_ms": (t3 - t2) * 1000,
            "voxel_volume_mm3": image.voxel_volume_mm3,
            "markers": {name: markers_for_plane(image.geometry, plane) for name, plane in PLANES.items()},
            "labels_preserved": bool(np.array_equal(reloaded.data, seg.data)),
        })


if __name__ == "__main__":
    main()
