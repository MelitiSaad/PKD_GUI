"""Loading and saving volumes.

NIfTI is the primary format (both the image and the AI's label volume). Images
and segmentations are canonicalised to the same closest-canonical (RAS+)
orientation so they overlay correctly regardless of how each was stored. A
best-effort DICOM-series loader is included; AVW can be added behind the same
interface.
"""
from __future__ import annotations

import os
from typing import Tuple

import numpy as np

from .labels import LabelTable
from .segmentation import Segmentation
from .volume import ImageVolume
from .validation import SegmentationValidationError, validated_labels

NIFTI_EXT = (".nii", ".nii.gz")


class LoadError(Exception):
    pass


def _is_nifti(path: str) -> bool:
    p = path.lower()
    return p.endswith(".nii") or p.endswith(".nii.gz")


# --------------------------------------------------------------------- NIfTI
def _load_nifti(path: str, as_int: bool):
    import nibabel as nib

    img = nib.load(path)
    img = nib.as_closest_canonical(img)          # RAS+ orientation
    zooms = img.header.get_zooms()[:3]
    spacing = tuple(float(z) if z and np.isfinite(z) else 1.0 for z in zooms)
    if len(spacing) < 3:
        spacing = tuple(list(spacing) + [1.0] * (3 - len(spacing)))
    if as_int:
        data = validated_labels(np.asanyarray(img.dataobj))
    else:
        data = np.asanyarray(img.dataobj).astype(np.float32)
    data = np.ascontiguousarray(data)
    return data, spacing, img.affine


# --------------------------------------------------------------------- DICOM
def _pixel_spacing(ds):
    ps = getattr(ds, "PixelSpacing", None)
    if ps is not None and len(ps) >= 2:
        try:
            return float(ps[0]), float(ps[1])
        except Exception:
            pass
    return 1.0, 1.0


def _apply_rescale(ds, arr):
    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    if slope != 1.0 or intercept != 0.0:
        arr = arr * slope + intercept
    return arr


def _slice_z(ds):
    ipp = getattr(ds, "ImagePositionPatient", None)
    if ipp is not None:
        try:
            return float(ipp[2])
        except Exception:
            pass
    return float(getattr(ds, "InstanceNumber", 0) or 0)


def _load_dicom_series(path: str):
    import pydicom

    paths = []
    if os.path.isdir(path):
        for root, _dirs, names in os.walk(path):
            for n in names:
                paths.append(os.path.join(root, n))
    else:
        paths = [path]

    datasets = []
    for f in paths:
        if os.path.basename(f).lower() in ("dicomdir",):
            continue
        try:
            ds = pydicom.dcmread(f, force=True)
            if "PixelData" not in ds:
                continue
            _ = ds.pixel_array  # force decode; skip unreadable/compressed-without-handler
            datasets.append(ds)
        except Exception:
            continue
    if not datasets:
        raise LoadError(
            "No readable DICOM image files were found in that selection. "
            "Point to the folder that contains the slice files."
        )

    # Multi-frame: a single file whose pixels decode to 3D (frames, rows, cols).
    if len(datasets) == 1 and datasets[0].pixel_array.ndim == 3:
        ds = datasets[0]
        arr = _apply_rescale(ds, ds.pixel_array.astype(np.float32))   # (frames, rows, cols)
        arr = np.ascontiguousarray(np.transpose(arr, (1, 2, 0)))      # (rows, cols, frames)
        ps = _pixel_spacing(ds)
        st = float(getattr(ds, "SpacingBetweenSlices", 0) or getattr(ds, "SliceThickness", 1.0) or 1.0)
        return arr, (ps[0], ps[1], st), np.eye(4)

    # Multi-slice series: keep 2D frames of a consistent shape, sorted by position.
    datasets = [d for d in datasets if d.pixel_array.ndim == 2]
    if not datasets:
        raise LoadError("DICOM pixel data was not 2D per slice; unsupported layout.")
    datasets.sort(key=_slice_z)
    shape0 = datasets[0].pixel_array.shape
    frames = [d for d in datasets if d.pixel_array.shape == shape0]
    vol = np.stack([_apply_rescale(d, d.pixel_array.astype(np.float32)) for d in frames], axis=-1)
    ps = _pixel_spacing(frames[0])
    st = float(getattr(frames[0], "SliceThickness", 1.0) or 1.0)
    if len(frames) > 1:
        dz = abs(_slice_z(frames[1]) - _slice_z(frames[0]))
        if dz > 0:
            st = dz
    return np.ascontiguousarray(vol), (ps[0], ps[1], st), np.eye(4)


# --------------------------------------------------------------------- API
def load_image(path: str) -> ImageVolume:
    try:
        if _is_nifti(path):
            data, spacing, affine = _load_nifti(path, as_int=False)
        else:
            data, spacing, affine = _load_dicom_series(path)
        if data.ndim != 3:
            raise LoadError(
                f"Image has shape {data.shape}; a single 3D volume is required. "
                "If this is a 4D/time series, export one volume first."
            )
        if min(data.shape) < 2:
            raise LoadError(
                f"Image shape {data.shape} is degenerate (an axis has <2 voxels), "
                "so it can't be shown as a 3D scan. This usually means only a single "
                "2D slice was loaded."
            )
    except LoadError:
        raise
    except Exception as exc:  # surface a clean message to the UI
        raise LoadError(f"Could not read image '{os.path.basename(path)}': {exc}") from exc
    return ImageVolume(data=data, spacing=spacing, affine=affine, path=path)


def load_segmentation(path: str, ref_shape: Tuple[int, int, int],
                      ref_affine: np.ndarray | None = None) -> Segmentation:
    try:
        if _is_nifti(path):
            data, _spacing, affine = _load_nifti(path, as_int=True)
        else:
            arr, _spacing, affine = _load_dicom_series(path)
            data = validated_labels(arr)
    except LoadError:
        raise
    except SegmentationValidationError as exc:
        raise LoadError(f"Invalid segmentation '{os.path.basename(path)}': {exc}") from exc
    except Exception as exc:
        raise LoadError(f"Could not read segmentation '{os.path.basename(path)}': {exc}") from exc

    if data.shape != tuple(ref_shape):
        raise LoadError(
            f"Segmentation shape {data.shape} does not match image {tuple(ref_shape)}. "
            "They must be in the same voxel grid."
        )
    # Matching shapes alone are unsafe: a translated or differently oriented
    # NIfTI can have the same dimensions while its labels map to other anatomy.
    # Both inputs have already been canonicalised, so their voxel-to-world
    # transforms must agree before we permit an editable overlay.
    if ref_affine is not None and _is_nifti(path) and not np.allclose(
            affine, ref_affine, rtol=1e-5, atol=1e-3):
        raise LoadError(
            "Segmentation geometry does not match the image (affine transform differs). "
            "Resample it into the image voxel grid before loading."
        )
    ids = np.unique(data)
    return Segmentation(data, LabelTable.from_ids(ids))


def save_segmentation(seg: Segmentation, image: ImageVolume, path: str) -> None:
    """Write the label volume as NIfTI using the image's affine (atomic)."""
    import nibabel as nib

    if not path or not _is_nifti(path):
        raise ValueError("Unsupported segmentation format. Choose a .nii or .nii.gz file.")
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise OSError(f"Destination folder does not exist: {parent}")
    if path.lower().endswith(".nii.gz"):
        tmp = path[:-7] + ".saving.nii.gz"      # keep a valid extension for nibabel
    else:
        tmp = path[:-4] + ".saving.nii"
    try:
        out = nib.Nifti1Image(seg.data.astype(np.uint16, copy=False), image.affine)
        out.header.set_zooms(tuple(float(v) for v in image.spacing))
        nib.save(out, tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
