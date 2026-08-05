"""Generate synthetic non-patient NIfTI Region Review QA fixtures.

Usage:
    python scripts/generate_region_review_qa.py /tmp/pkdqc-region-qa

The outputs are intentionally small enough to share inside a development team
but are generated artifacts and should not be committed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import nibabel as nib
import numpy as np


def _affine():
    return np.diag([1.0, 1.0, 2.0, 1.0])


def _save(path: Path, data: np.ndarray) -> None:
    img = nib.Nifti1Image(data, _affine())
    img.header.set_xyzt_units("mm")
    img.set_qform(_affine(), code=1)
    img.set_sform(_affine(), code=1)
    nib.save(img, str(path))


def _centres(n: int, shape=(128, 128, 64)):
    for r in range(n):
        yield 3 + (r * 7) % (shape[0] - 6), 3 + (r * 13) % (shape[1] - 6), 2 + (r * 5) % (shape[2] - 4)


def _paint_cube(data, centre, label, radius=1):
    i, j, k = centre
    data[i-radius:i+radius+1, j-radius:j+radius+1, k] = np.uint16(label)


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path("region_review_qa")
    out.mkdir(parents=True, exist_ok=True)
    shape = (128, 128, 64)
    image = np.zeros(shape, dtype=np.float32)
    for k in range(shape[2]):
        image[:, :, k] = k
    _save(out / "synthetic_image.nii.gz", image)

    one = np.zeros(shape, dtype=np.uint16)
    for centre in _centres(300, shape):
        _paint_cube(one, centre, 1)
    _save(out / "one_color_300_regions.nii.gz", one)

    individual = np.zeros(shape, dtype=np.uint16)
    for label, centre in enumerate(_centres(300, shape), start=1):
        _paint_cube(individual, centre, label)
    _save(out / "individual_300_labels.nii.gz", individual)

    mixed = one.copy()
    for label, centre in enumerate(_centres(80, shape), start=1000):
        _paint_cube(mixed, centre, label)
    _save(out / "mixed_shared_and_individual.nii.gz", mixed)

    touching = np.zeros(shape, dtype=np.uint16)
    touching[20:24, 20:24, 20] = 1
    touching[24:28, 20:24, 20] = 1
    _save(out / "touching_same_label_one_component.nii.gz", touching)

    sparse = np.zeros(shape, dtype=np.uint16)
    sparse[10, 10, 10] = 1
    sparse[90, 90, 30] = 65535
    _save(out / "sparse_high_label_values.nii.gz", sparse)

    print(f"Wrote Region Review QA fixtures to {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
