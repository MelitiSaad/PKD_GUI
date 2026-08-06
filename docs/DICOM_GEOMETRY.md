# Round 1D DICOM geometry and series selection

Round 1D replaces directory-wide DICOM stacking with explicit, PHI-safe discovery,
selection, geometry construction, and Recovery v2 identity for scalar source images.
It does not implement DICOM SEG import/export.

## Discovery and grouping

The loader scans only the selected file or the immediate files in the selected
folder, reading headers with pydicom before pixel decoding. Files are grouped by
Study Instance UID, Series Instance UID, Frame of Reference UID, SOP Class UID,
and Modality. Candidates record series number/description, modality, matrix,
frame or instance count, spacing, orientation summary, classic/enhanced kind,
warnings, errors, and localizer/scout status. Direct patient identifiers are not
stored in candidates, manifests, tests, or rejection markers.

If exactly one valid scalar 3D image series is present it may be loaded
automatically. If multiple valid series are present the UI requires an explicit
selection. Cancel leaves the current case unchanged through the existing Round 1B
case guard.

## Pixel-array axis interpretation and LPS-to-RAS

For classic single-frame slices, DICOM `ImageOrientationPatient` gives row and
column direction cosines in patient LPS space, `ImagePositionPatient` gives the
first voxel position, and `PixelSpacing` gives row then column spacing. The app
builds an LPS affine for the decoded NumPy array, converts that affine to RAS,
and canonicalizes the resulting volume to the Round 1C RAS+ `ImageGeometry`
contract.

Slice ordering uses the projection of each `ImagePositionPatient` onto the slice
normal (`row_direction × column_direction`), never filenames, Instance Number, or
patient Z alone. Inter-slice spacing is derived from those projected positions;
`SliceThickness` is not treated as authoritative spacing.

## Validation and rejection rules

The loader rejects or excludes data that cannot be represented as one trustworthy
scalar 3D volume, including mixed studies/series, localizers/scouts, unsupported
SOP classes, DICOM SEG, color/vector/tiled data, missing geometry attributes,
duplicate positions, irregular spacing/gaps, inconsistent orientation, matrix,
pixel spacing, frame of reference, mixed temporal positions, unsupported enhanced
multiframe dimensions, and shear/non-orthogonal orientation such as gantry tilt.
Compressed data without an installed pixel decoder fails clearly during decode.

## Enhanced multiframe scope

Enhanced CT/MR multiframe is supported only when Shared and Per-Frame Functional
Groups describe one regular scalar 3D stack. The implementation resolves Pixel
Measures, Plane Orientation, and Plane Position from functional groups, sorts
frames by geometric position, applies supported rescale transforms, and rejects
irregular or multidimensional layouts instead of flattening them.

## Recovery v2 identity

For DICOM sources, Recovery v2 stores a PHI-safe aggregate identity: technical
series identifiers, ordered source-file size/mtime/content fingerprints, loaded
shape, canonical affine, and spacing. On recovery, the exact selected series is
rediscovered by technical identifiers and the aggregate identity must match. A
changed, missing, or ambiguous series invalidates recovery without deleting the
checkpoint or replacing the current case.

## Known limitations

DICOM SEG, gantry-tilt correction, general resampling, registration,
anatomical-plane reslicing, color/vector images, tiled data, arbitrary enhanced
multiframe dimensions, and compressed data without a configured pydicom pixel
handler remain unsupported.

## Round 1G DICOM note
Current DICOM support is image-series loading with geometry validation and a PHI-safe chooser when multiple valid series are found. DICOM SEG export/import, registration, and resampling remain out of scope.

All segmentation layers share the one canonical reference geometry. Incompatible layers are rejected rather than resampled.
