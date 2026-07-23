"""Segmentation operations used by the editing tools.

All operations are pure with respect to the app: they compute a new slice or
volume and hand it to :func:`commands.apply_slice` / :func:`commands.apply_volume`,
which diff it and return an undoable :class:`EditCommand`. Nothing here touches
the GUI.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

import numpy as np
from scipy import ndimage as ndi

from . import commands
from .commands import EditCommand
from .segmentation import Segmentation


def _label_mask(seg: Segmentation, label_id: int, z: Optional[int]) -> np.ndarray:
    src = seg.data[:, :, z] if z is not None else seg.data
    return src == np.uint16(label_id)


def paintable_mask(current_values: np.ndarray, value: int, protect_existing: bool) -> np.ndarray:
    """Return voxels a brush may modify under the selected paint policy.

    Protected painting adds only to background (and permits repainting the active
    label), while erasing deliberately remains unrestricted.  Keeping the rule
    in the Qt-free core makes it easy to reuse for future lasso/threshold tools.
    """
    if not protect_existing or value == 0:
        return np.ones(np.asarray(current_values).shape, dtype=bool)
    values = np.asarray(current_values)
    return (values == 0) | (values == np.uint16(value))


# ------------------------------------------------------------ polygon / lasso
def rasterize_polygon(shape: tuple[int, int], vertices) -> np.ndarray:
    """Return a pixel-centre mask for a closed polygon in display coordinates.

    ``vertices`` are ``(vertical, horizontal)`` points, matching the plane-view
    convention.  The compact ray-casting implementation deliberately has no UI
    dependency, which makes its medical-image behaviour regression-testable.
    Boundary pixels are included by the scanline rule used for the fill.
    """
    pts = np.asarray(vertices, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[0] < 3 or pts.shape[1] != 2:
        return np.zeros(shape, dtype=bool)
    rows, cols = int(shape[0]), int(shape[1])
    lo_v = max(0, int(np.floor(pts[:, 0].min())))
    hi_v = min(rows, int(np.ceil(pts[:, 0].max())) + 1)
    lo_h = max(0, int(np.floor(pts[:, 1].min())))
    hi_h = min(cols, int(np.ceil(pts[:, 1].max())) + 1)
    out = np.zeros((rows, cols), dtype=bool)
    if lo_v >= hi_v or lo_h >= hi_h:
        return out
    vv, hh = np.mgrid[lo_v:hi_v, lo_h:hi_h]
    y, x = vv + 0.5, hh + 0.5
    inside = np.zeros(y.shape, dtype=bool)
    pv, ph = pts[-1]
    for cv, ch in pts:
        crosses = ((cv > y) != (pv > y))
        x_at_y = (ph - ch) * (y - cv) / ((pv - cv) if pv != cv else 1e-20) + ch
        inside ^= crosses & (x < x_at_y)
        pv, ph = cv, ch
    out[lo_v:hi_v, lo_h:hi_h] = inside
    return out


def apply_polygon_plane(seg: Segmentation, plane, cursor, vertices, value: int,
                        protect_existing: bool = True) -> Optional[EditCommand]:
    """Apply one polygon add/remove operation to one MPR plane as one command.

    The current plane is rasterised then mapped through ``plane`` rather than
    assuming axial storage.  Therefore coronal and sagittal corrections modify
    the same physical voxels without altering image geometry or affine data.
    """
    current = plane.slice2d(seg.data, cursor)
    mask = rasterize_polygon(current.shape, vertices)
    if not mask.any():
        return None
    updated = current.copy()
    if value == 0:
        updated[mask] = 0
        description = "polygon remove"
    else:
        writable = mask & paintable_mask(current, value, protect_existing)
        updated[writable] = np.uint16(value)
        description = "polygon add"
    return commands.apply_plane_slice(seg, plane, cursor, updated, description)


# --------------------------------------------------------------------- fill
def flood_fill(seg: Segmentation, z: int, row: int, col: int, value: int,
               connectivity: int = 1) -> Optional[EditCommand]:
    """Region-grow from (row, col) over connected voxels of equal value on axial slice z."""
    sl = seg.data[:, :, z]
    seed_val = sl[row, col]
    if seed_val == np.uint16(value):
        return None
    structure = ndi.generate_binary_structure(2, connectivity)
    same = sl == seed_val
    labeled, _ = ndi.label(same, structure=structure)
    target = labeled == labeled[row, col]
    new_slice = sl.copy()
    new_slice[target] = np.uint16(value)
    return commands.apply_slice(seg, z, new_slice, "flood fill")


def flood_fill_plane(seg: Segmentation, plane, cursor, v: int, h: int, value: int,
                     connectivity: int = 1) -> Optional[EditCommand]:
    """Flood fill on an arbitrary plane's 2D slice, written back to the volume."""
    sl = plane.slice2d(seg.data, cursor)
    seed_val = sl[v, h]
    if seed_val == np.uint16(value):
        return None
    structure = ndi.generate_binary_structure(2, connectivity)
    labeled, _ = ndi.label(sl == seed_val, structure=structure)
    target = labeled == labeled[v, h]
    new_slice = sl.copy()
    new_slice[target] = np.uint16(value)
    return commands.apply_plane_slice(seg, plane, cursor, new_slice, "flood fill")


# ------------------------------------------------------------ grow / shrink
def grow(seg: Segmentation, label_id: int, iterations: int = 1,
         in_3d: bool = True, z: Optional[int] = None) -> Optional[EditCommand]:
    """Dilate a label into surrounding background only (never overwrites others)."""
    if in_3d:
        mask = seg.data == np.uint16(label_id)
        st = ndi.generate_binary_structure(3, 1)
        grown = ndi.binary_dilation(mask, structure=st, iterations=iterations)
        add = grown & (seg.data == 0)
        if not add.any():
            return None
        new = seg.data.copy()
        new[add] = np.uint16(label_id)
        return commands.apply_volume(seg, new, "grow")
    sl = seg.data[:, :, z]
    mask = sl == np.uint16(label_id)
    st = ndi.generate_binary_structure(2, 1)
    grown = ndi.binary_dilation(mask, structure=st, iterations=iterations)
    add = grown & (sl == 0)
    if not add.any():
        return None
    new = sl.copy()
    new[add] = np.uint16(label_id)
    return commands.apply_slice(seg, z, new, "grow")


def shrink(seg: Segmentation, label_id: int, iterations: int = 1,
           in_3d: bool = True, z: Optional[int] = None) -> Optional[EditCommand]:
    """Erode a label; removed voxels become background."""
    if in_3d:
        mask = seg.data == np.uint16(label_id)
        st = ndi.generate_binary_structure(3, 1)
        eroded = ndi.binary_erosion(mask, structure=st, iterations=iterations)
        remove = mask & ~eroded
        if not remove.any():
            return None
        new = seg.data.copy()
        new[remove] = 0
        return commands.apply_volume(seg, new, "shrink")
    sl = seg.data[:, :, z]
    mask = sl == np.uint16(label_id)
    st = ndi.generate_binary_structure(2, 1)
    eroded = ndi.binary_erosion(mask, structure=st, iterations=iterations)
    remove = mask & ~eroded
    if not remove.any():
        return None
    new = sl.copy()
    new[remove] = 0
    return commands.apply_slice(seg, z, new, "shrink")


# -------------------------------------------------------------- clean-up ops
def remove_islands(seg: Segmentation, label_id: int, min_size: int = 20,
                   in_3d: bool = True, z: Optional[int] = None) -> Optional[EditCommand]:
    """Remove connected components of a label smaller than ``min_size`` voxels."""
    mask = _label_mask(seg, label_id, None if in_3d else z)
    rank = 3 if in_3d else 2
    st = ndi.generate_binary_structure(rank, 1)
    labeled, n = ndi.label(mask, structure=st)
    if n == 0:
        return None
    sizes = ndi.sum(np.ones_like(labeled), labeled, index=np.arange(1, n + 1))
    small = {i + 1 for i, s in enumerate(sizes) if s < min_size}
    if not small:
        return None
    remove = np.isin(labeled, list(small))
    if in_3d:
        new = seg.data.copy()
        new[remove] = 0
        return commands.apply_volume(seg, new, "remove islands")
    new = seg.data[:, :, z].copy()
    new[remove] = 0
    return commands.apply_slice(seg, z, new, "remove islands")


def fill_holes(seg: Segmentation, label_id: int, in_3d: bool = True,
               z: Optional[int] = None) -> Optional[EditCommand]:
    """Fill fully-enclosed background holes inside a label."""
    mask = _label_mask(seg, label_id, None if in_3d else z)
    filled = ndi.binary_fill_holes(mask)
    add = filled & ~mask
    if not add.any():
        return None
    if in_3d:
        new = seg.data.copy()
        new[add] = np.uint16(label_id)
        return commands.apply_volume(seg, new, "fill holes")
    new = seg.data[:, :, z].copy()
    new[add] = np.uint16(label_id)
    return commands.apply_slice(seg, z, new, "fill holes")


# ------------------------------------------------- interpolate between slices
def _signed_distance(mask: np.ndarray) -> np.ndarray:
    """Positive inside the mask, negative outside (in voxels)."""
    if not mask.any():
        return np.full(mask.shape, -1e6, dtype=np.float32)
    if mask.all():
        return np.full(mask.shape, 1e6, dtype=np.float32)
    inside = ndi.distance_transform_edt(mask)
    outside = ndi.distance_transform_edt(~mask)
    return (inside - outside).astype(np.float32)


def interpolate_between(seg: Segmentation, label_id: int, z0: int, z1: int) -> Optional[EditCommand]:
    """Morphological contour interpolation of a label between two edited slices.

    Uses signed-distance-field blending — the standard 3D-Slicer / ITK-SNAP
    "fill between slices" technique — so a reviewer can annotate every Nth slice
    and let the tool fill the gaps.
    """
    lo, hi = (z0, z1) if z0 < z1 else (z1, z0)
    if hi - lo < 2:
        return None
    m0 = seg.data[:, :, lo] == np.uint16(label_id)
    m1 = seg.data[:, :, hi] == np.uint16(label_id)
    if not m0.any() or not m1.any():
        return None
    sdf0 = _signed_distance(m0)
    sdf1 = _signed_distance(m1)
    new = seg.data.copy()
    for z in range(lo + 1, hi):
        w = (z - lo) / (hi - lo)
        blended = (1.0 - w) * sdf0 + w * sdf1
        mask_z = blended >= 0.0
        sl = new[:, :, z]
        sl[mask_z] = np.uint16(label_id)   # add interpolated region, keep existing edits
    return commands.apply_volume(seg, new, "interpolate slices")


# ------------------------------------------------------------ brush geometry
@lru_cache(maxsize=128)
def disk_offsets(radius: int) -> tuple[np.ndarray, np.ndarray]:
    """Return cached integer offsets covering a filled disk of ``radius``.

    Brush dabs are generated for every pointer event.  Caching avoids allocating
    the same stencil repeatedly while a reviewer paints with one brush size.
    Callers must treat the returned arrays as read-only.
    """
    r = int(max(0, radius))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    inside = (yy * yy + xx * xx) <= (r + 0.5) ** 2
    return yy[inside].ravel(), xx[inside].ravel()
