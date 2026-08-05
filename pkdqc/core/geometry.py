"""Qt-independent medical-image geometry contract.

Internal convention: voxel arrays are canonical RAS+ and world coordinates are
millimetres in RAS patient space: ``world = affine @ [i, j, k, 1]``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

import numpy as np

AFFINE_ATOL = 1e-3
AFFINE_RTOL = 1e-5
ORTHO_TOL = 1e-4
SINGULAR_TOL = 1e-8
SUPPORTED_UNITS = {"mm", "unknown"}

_POS = ("R", "A", "S")
_NEG = ("L", "P", "I")


@dataclass(frozen=True)
class GeometryValidation:
    ok: bool
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ImageGeometry:
    shape: Tuple[int, int, int]
    affine: np.ndarray
    spacing: Tuple[float, float, float]
    axis_codes: Tuple[str, str, str]
    handedness: str
    voxel_volume_mm3: float
    validation: GeometryValidation
    spatial_units: str = "mm"
    qform_code: int = 0
    sform_code: int = 0

    @classmethod
    def from_affine(cls, shape, affine, *, spacing=None, spatial_units="mm", qform_code=0, sform_code=0):
        shape = tuple(int(v) for v in shape)
        aff = np.asarray(affine, dtype=float)
        errors = []
        warnings = []
        if len(shape) != 3 or any(v <= 0 for v in shape):
            errors.append(f"image shape must be three positive axes, got {shape}")
        if aff.shape != (4, 4):
            errors.append("affine must be 4x4")
            aff = np.eye(4)
        if not np.all(np.isfinite(aff)):
            errors.append("affine contains NaN or infinite values")
        mat = aff[:3, :3]
        det = float(np.linalg.det(mat)) if np.all(np.isfinite(mat)) else float("nan")
        if not np.isfinite(det) or abs(det) <= SINGULAR_TOL:
            errors.append("affine is singular or nearly singular")
        norms = np.linalg.norm(mat, axis=0)
        if spacing is None:
            spacing = tuple(float(v) for v in norms)
        else:
            spacing = tuple(float(v) for v in spacing)
        if len(spacing) != 3 or any((not np.isfinite(v)) or v <= 0 for v in spacing):
            errors.append(f"voxel spacing must be finite positive millimetres, got {spacing}")
        unit = (spatial_units or "unknown").lower()
        if unit not in SUPPORTED_UNITS:
            errors.append(f"unsupported spatial units '{spatial_units}'; millimetres are required")
        elif unit == "unknown":
            warnings.append("spatial units are missing/ambiguous; treating affine units as millimetres")
        if np.all(np.isfinite(norms)) and np.all(norms > 0):
            dirs = mat / norms
            gram = dirs.T @ dirs
            off = gram - np.eye(3)
            if np.max(np.abs(off)) > ORTHO_TOL:
                errors.append("unsupported shear or non-orthogonal geometry; reslice externally before editing")
            axis_codes = tuple(_axis_code(dirs[:, a]) for a in range(3))
        else:
            axis_codes = ("?", "?", "?")
        handedness = "right" if np.isfinite(det) and det > 0 else "left"
        volume = abs(det) if np.isfinite(det) else float("nan")
        return cls(shape, aff.copy(), spacing, axis_codes, handedness, float(volume),
                   GeometryValidation(not errors, tuple(errors), tuple(warnings)), unit,
                   int(qform_code or 0), int(sform_code or 0))

    @property
    def orientation(self) -> str:
        return "".join(self.axis_codes)

    def voxel_to_world(self, ijk) -> np.ndarray:
        v = np.array([float(ijk[0]), float(ijk[1]), float(ijk[2]), 1.0])
        return (self.affine @ v)[:3]

    def world_to_voxel(self, ras) -> np.ndarray:
        w = np.array([float(ras[0]), float(ras[1]), float(ras[2]), 1.0])
        return (np.linalg.inv(self.affine) @ w)[:3]

    def assert_segmentation_compatible(self, shape, affine):
        if tuple(shape) != self.shape:
            raise ValueError(f"Segmentation shape {tuple(shape)} does not match image {self.shape}")
        if not np.allclose(np.asarray(affine, dtype=float), self.affine, rtol=AFFINE_RTOL, atol=AFFINE_ATOL):
            raise ValueError("Segmentation affine does not match image affine")


def _axis_code(direction: np.ndarray) -> str:
    idx = int(np.argmax(np.abs(direction)))
    return _POS[idx] if direction[idx] >= 0 else _NEG[idx]


def markers_for_plane(geometry: ImageGeometry, plane) -> Dict[str, str]:
    """Return patient markers at display edges for the existing Plane transform.

    Keys are ``top``, ``bottom``, ``left`` and ``right``.  Plane display flips
    the vertical and horizontal in-plane axes, so top/left are the maximum voxel
    direction and bottom/right are the minimum direction for those axes.
    """
    return {
        "top": _axis_code(geometry.affine[:3, plane.hi]),
        "bottom": _opposite(_axis_code(geometry.affine[:3, plane.hi])),
        "left": _axis_code(geometry.affine[:3, plane.lo]),
        "right": _opposite(_axis_code(geometry.affine[:3, plane.lo])),
    }


def _opposite(code: str) -> str:
    return {"L": "R", "R": "L", "A": "P", "P": "A", "S": "I", "I": "S"}.get(code, "?")


def validate_nifti_header(img) -> Tuple[str, Tuple[str, ...], Tuple[str, ...]]:
    """Select spatial units and validate qform/sform consistency before canonicalization."""
    errors = []
    warnings = []
    hdr = img.header
    xyz_unit = hdr.get_xyzt_units()[0] or "unknown"
    if xyz_unit not in SUPPORTED_UNITS:
        errors.append(f"unsupported spatial units '{xyz_unit}'; millimetres are required")
    if xyz_unit == "unknown":
        warnings.append("spatial units are missing/ambiguous; treating affine units as millimetres")
    qaff, qcode = img.get_qform(coded=True)
    saff, scode = img.get_sform(coded=True)
    if int(qcode or 0) > 0 and int(scode or 0) > 0 and not np.allclose(qaff, saff, rtol=AFFINE_RTOL, atol=AFFINE_ATOL):
        errors.append("conflicting qform and sform affines; choose a single validated spatial transform before loading")
    return xyz_unit or "unknown", tuple(errors), tuple(warnings)
