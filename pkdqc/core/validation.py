"""Strict validation at the boundary of the editable label-volume model."""
from __future__ import annotations

import numpy as np

LABEL_DTYPE = np.dtype(np.uint16)
MAX_LABEL = int(np.iinfo(LABEL_DTYPE).max)


class SegmentationValidationError(ValueError):
    """A label array cannot be represented losslessly by the editor."""


def validated_labels(data) -> np.ndarray:
    """Return a contiguous uint16 array, rejecting every lossy conversion.

    Validation deliberately happens on the source values before conversion.
    """
    if not isinstance(data, np.ndarray):
        raise SegmentationValidationError("Segmentation data must be a NumPy array.")
    if data.ndim != 3 or data.size == 0 or any(n <= 0 for n in data.shape):
        raise SegmentationValidationError(
            f"Segmentation must be a non-empty 3D array; received shape {data.shape}."
        )
    if data.dtype.kind not in "iu f":
        raise SegmentationValidationError(
            f"Unsupported segmentation dtype {data.dtype}; labels must be numeric integers."
        )
    if data.dtype.kind == "f":
        finite = np.isfinite(data)
        if not finite.all():
            bad = "NaN" if np.isnan(data).any() else "infinite"
            raise SegmentationValidationError(f"Segmentation contains {bad} label values.")
        if not np.equal(data, np.trunc(data)).all():
            raise SegmentationValidationError(
                "Segmentation contains fractional label values; labels must be whole numbers."
            )
    minimum = data.min()
    maximum = data.max()
    if minimum < 0:
        raise SegmentationValidationError(
            f"Segmentation contains a negative label value ({minimum})."
        )
    if maximum > MAX_LABEL:
        raise SegmentationValidationError(
            f"Segmentation label {maximum} exceeds the supported maximum {MAX_LABEL}."
        )
    return np.ascontiguousarray(data, dtype=LABEL_DTYPE)
