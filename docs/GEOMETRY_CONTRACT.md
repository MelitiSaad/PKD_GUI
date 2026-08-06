# Round 1C geometry contract

PKD&QC keeps NIfTI data in canonical RAS+ voxel order.  For every loaded image,
`ImageGeometry` is the Qt-independent authority for shape, affine, spacing, axis
codes, handedness, voxel volume, validation status, and voxel/world transforms.

## Internal coordinates

The invariant is:

```text
world_ras_mm = affine_ras @ [i, j, k, 1]
segmentation.shape == image.shape
segmentation.affine ~= image.affine within rtol=1e-5, atol=1e-3 mm
voxel_volume_mm3 = abs(det(affine_ras[:3, :3]))
```

Array axes are `(i, j, k)` in canonical RAS+ storage.  Voxel-to-world and
world-to-voxel calculations use the affine directly; the display convention does
not rewrite the affine.

## Display convention and markers

Round 1C uses one explicit radiological/RAS+ display convention.  Existing plane
transforms remain bijective: each displayed pixel maps back to exactly one source
voxel.  Patient markers are derived from the affine columns after the plane's
actual transpose/flip mapping:

- Axial: in-plane i/j axes.
- Coronal: in-plane i/k axes.
- Sagittal: in-plane j/k axes.

The marker code is isolated so neurological display can be added later without
changing voxel/world geometry.

## Oblique and shear policy

Oblique rotations/flips are accepted when the affine columns remain orthogonal:
the current voxel-aligned panes can still map displayed pixels to their correct
RAS world coordinates.  General anatomical-plane reslicing is not implemented in
this milestone.  Shear or non-orthogonal affine columns are blocked because the
current viewer would display a rectangular pixel grid that does not faithfully
represent the source geometry.

## qform, sform, and units

NIfTI load validates qform/sform before canonicalization.  If both qform and
sform are coded and disagree beyond the documented tolerance, loading is blocked
with an actionable error.  Millimetres are the supported clinical unit.  Missing
or ambiguous spatial units are warned and interpreted as millimetres; unsupported
units such as metres are rejected.  Exports write both qform and sform from the
image affine with millimetre units and preserve exact uint16 label values.

## Segmentation compatibility

Segmentation overlays must match the image shape and canonical affine.  Round 1C
does not silently resample labels.  If resampling is needed, users must resample
externally into the image voxel grid before editing.  Any future label resampling
must be nearest-neighbour only.

## Known limitations

DICOM still uses the legacy best-effort loader and remains the next focused P0
milestone.  Round 1C does not add anatomical-plane reslicing, registration,
advanced metadata preservation, or new segmentation export formats.

Round 1H validates every added layer against the single reference shape and affine before mutating the layer collection; it performs no registration or resampling.
