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
from .label_policy import DrawOver, LabelProtectionPolicy, policy_for


def _label_mask(seg: Segmentation, label_id: int, z: Optional[int]) -> np.ndarray:
    src = seg.data[:, :, z] if z is not None else seg.data
    return src == np.uint16(label_id)


def paintable_mask(current_values: np.ndarray, value: int, protect_existing: bool,
                   erase_label: int | None = None) -> np.ndarray:
    """Compatibility wrapper around the shared label-protection policy."""
    policy = LabelProtectionPolicy(
        DrawOver.BACKGROUND_ONLY if protect_existing else DrawOver.ALL_PERMITTED,
        selected_label=erase_label if erase_label is not None else int(value),
        erase_selected_only=erase_label is not None,
    )
    return policy.writable(current_values, value)


# ---------------------------------------------------------------------- lasso
def rasterize_lasso(shape: tuple[int, int], vertices) -> np.ndarray:
    """Return a pixel-centre mask for a closed freehand contour.

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


def apply_lasso_plane(seg: Segmentation, plane, cursor, vertices, value: int,
                      protect_existing: bool = True, remove_label: int | None = None,
                      policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Apply one lasso add/remove operation to one MPR plane as one command.

    The current plane is rasterised then mapped through ``plane`` rather than
    assuming axial storage.  Therefore coronal and sagittal corrections modify
    the same physical voxels without altering image geometry or affine data.
    """
    current = plane.slice2d(seg.data, cursor)
    mask = rasterize_lasso(current.shape, vertices)
    if not mask.any():
        return None
    updated = current.copy()
    policy = policy or policy_for(seg, protect_existing=protect_existing)
    if value == 0:
        removable = mask & policy.writable(current, 0)
        if remove_label is not None:
            removable &= current == np.uint16(remove_label)
        updated[removable] = 0
        description = "lasso remove"
    else:
        writable = mask & policy.writable(current, value)
        updated[writable] = np.uint16(value)
        description = "lasso add"
    return commands.apply_plane_slice(seg, plane, cursor, updated, description)


# --------------------------------------------------------------------- fill
def flood_fill(seg: Segmentation, z: int, row: int, col: int, value: int,
               connectivity: int = 1, policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Region-grow from (row, col) over connected voxels of equal value on axial slice z."""
    sl = seg.data[:, :, z]
    seed_val = sl[row, col]
    if seed_val == np.uint16(value):
        return None
    structure = ndi.generate_binary_structure(2, connectivity)
    same = sl == seed_val
    labeled, _ = ndi.label(same, structure=structure)
    target = labeled == labeled[row, col]
    target &= (policy or policy_for(seg)).writable(sl, value)
    new_slice = sl.copy()
    new_slice[target] = np.uint16(value)
    return commands.apply_slice(seg, z, new_slice, "flood fill")


def flood_fill_plane(seg: Segmentation, plane, cursor, v: int, h: int, value: int,
                     connectivity: int = 1, policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Flood fill on an arbitrary plane's 2D slice, written back to the volume."""
    sl = plane.slice2d(seg.data, cursor)
    seed_val = sl[v, h]
    if seed_val == np.uint16(value):
        return None
    structure = ndi.generate_binary_structure(2, connectivity)
    labeled, _ = ndi.label(sl == seed_val, structure=structure)
    target = labeled == labeled[v, h]
    target &= (policy or policy_for(seg)).writable(sl, value)
    new_slice = sl.copy()
    new_slice[target] = np.uint16(value)
    return commands.apply_plane_slice(seg, plane, cursor, new_slice, "flood fill")


# ------------------------------------------------------------ grow / shrink
def grow(seg: Segmentation, label_id: int, iterations: int = 1,
         in_3d: bool = True, z: Optional[int] = None,
         policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Dilate a label into surrounding background only (never overwrites others)."""
    policy = policy or policy_for(seg, selected_label=label_id)
    if in_3d:
        mask = seg.data == np.uint16(label_id)
        st = ndi.generate_binary_structure(3, 1)
        grown = ndi.binary_dilation(mask, structure=st, iterations=iterations)
        add = grown & (policy.writable(seg.data, label_id))
        if not add.any():
            return None
        new = seg.data.copy()
        new[add] = np.uint16(label_id)
        return commands.apply_volume(seg, new, "grow")
    sl = seg.data[:, :, z]
    mask = sl == np.uint16(label_id)
    st = ndi.generate_binary_structure(2, 1)
    grown = ndi.binary_dilation(mask, structure=st, iterations=iterations)
    add = grown & (policy.writable(sl, label_id))
    if not add.any():
        return None
    new = sl.copy()
    new[add] = np.uint16(label_id)
    return commands.apply_slice(seg, z, new, "grow")


def shrink(seg: Segmentation, label_id: int, iterations: int = 1,
           in_3d: bool = True, z: Optional[int] = None,
           policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Erode a label; removed voxels become background."""
    policy = policy or policy_for(seg, selected_label=label_id)
    if in_3d:
        mask = seg.data == np.uint16(label_id)
        st = ndi.generate_binary_structure(3, 1)
        eroded = ndi.binary_erosion(mask, structure=st, iterations=iterations)
        remove = mask & ~eroded & policy.writable(seg.data, 0)
        if not remove.any():
            return None
        new = seg.data.copy()
        new[remove] = 0
        return commands.apply_volume(seg, new, "shrink")
    sl = seg.data[:, :, z]
    mask = sl == np.uint16(label_id)
    st = ndi.generate_binary_structure(2, 1)
    eroded = ndi.binary_erosion(mask, structure=st, iterations=iterations)
    remove = mask & ~eroded & policy.writable(sl, 0)
    if not remove.any():
        return None
    new = sl.copy()
    new[remove] = 0
    return commands.apply_slice(seg, z, new, "shrink")


# -------------------------------------------------------------- clean-up ops
def remove_islands(seg: Segmentation, label_id: int, min_size: int = 20,
                   in_3d: bool = True, z: Optional[int] = None,
                   policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Remove connected components of a label smaller than ``min_size`` voxels."""
    policy = policy or policy_for(seg, selected_label=label_id)
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
    source = seg.data if in_3d else seg.data[:, :, z]
    remove &= policy.writable(source, 0)
    if in_3d:
        new = seg.data.copy()
        new[remove] = 0
        return commands.apply_volume(seg, new, "remove islands")
    new = seg.data[:, :, z].copy()
    new[remove] = 0
    return commands.apply_slice(seg, z, new, "remove islands")


def fill_holes(seg: Segmentation, label_id: int, in_3d: bool = True,
               z: Optional[int] = None, policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Fill fully-enclosed background holes inside a label."""
    policy = policy or policy_for(seg, selected_label=label_id)
    mask = _label_mask(seg, label_id, None if in_3d else z)
    filled = ndi.binary_fill_holes(mask)
    source = seg.data if in_3d else seg.data[:, :, z]
    add = filled & ~mask & policy.writable(source, label_id)
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


def interpolate_between(seg: Segmentation, label_id: int, z0: int, z1: int,
                        policy: LabelProtectionPolicy | None = None) -> Optional[EditCommand]:
    """Morphological contour interpolation of a label between two edited slices.

    Uses signed-distance-field blending — the standard 3D-Slicer / ITK-SNAP
    "fill between slices" technique — so a reviewer can annotate every Nth slice
    and let the tool fill the gaps.
    """
    policy = policy or policy_for(seg, selected_label=label_id)
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
        writable = policy.writable(sl, label_id)
        sl[mask_z & writable] = np.uint16(label_id)
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
