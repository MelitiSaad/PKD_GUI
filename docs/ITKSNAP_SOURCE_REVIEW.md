# Bundled ITK-SNAP source review

## Identification and handling

The archive is **`/workspace/PKD_GUI/itksnap-master.zip`**. Its ZIP comment identifies commit
`679ba76a639df6c4594015161a324c51cc8dfd86`; entries are dated 2026-07-08. Root
`CMakeLists.txt` declares **4.6.0-alpha.1**, release date 2026-06-11. It was listed and
extracted without modifying/deleting the original to
`/tmp/pkdqc-itksnap-audit/itksnap-master`. The extracted tree was treated as read-only.

## License assessment

ITK-SNAP's root `COPYING` is **GNU GPL version 3**. This repository has **no LICENSE or
COPYING file**, so no permission grant is stated and compatibility cannot be established.
Copying/transplanting GPL-covered implementation into a distributed derivative would normally
require the combined work to meet GPLv3 source and notice obligations. Dependency licenses
(PySide6 LGPL, pyqtgraph/numpy/scipy/nibabel/pydicom and optional VTK/PyVista) also require a
release notice/SBOM review. Therefore: study public behavior and architecture, independently
implement from requirements/tests, preserve an audit trail, and do **not** reuse ITK-SNAP code
until the repository owner selects a license and counsel/authorized licensing review approves.
This is an engineering assessment, not legal advice.

## Architecture observed

ITK-SNAP separates Qt views, UI models, framework/application state, image wrappers, renderers,
algorithms, and mesh pipelines. Representative inspected locations include:

* `Logic/Framework/IRISApplication.*`, `GlobalState.*`, `GenericImageData.*` — application and
  layered image state.
* `Logic/Common/ImageCoordinateGeometry.*` and `Logic/ImageWrapper/*` — explicit patient/image/
  display coordinate transforms, metadata, timepoints and component wrappers.
* `GUI/Model/*`, `GUI/Qt/Components/SliceViewPanel.*`, `GUI/Renderer/GenericSliceRenderer.*` —
  model/view/render split with event-driven updates.
* `GUI/Qt/View/PaintbrushInteractionMode.*`, `PolygonDrawingInteractionMode.*` and renderer peers
  — interaction-mode state and visual feedback.
* `Logic/Framework/UndoDataManager.*`, `SegmentationUpdateIterator.*` — delta-based label changes.
* `Logic/Common/SegmentationStatistics.*`, `Logic/Mesh/MeshManager.*`,
  `Logic/Mesh/VTKMeshPipeline.*` — statistics and cached mesh processing.
* `Logic/ImageWrapper/GuidedNativeImageIO.*`, `Common/MultiFrameDicomSeriesSorter.*` — guided I/O,
  DICOM grouping/sorting and geometry rather than naive directory stacking.
* Snake/ROI, registration, annotation, distributed segmentation, preferences, workspace and CLI
  sources demonstrate its wider general-purpose workstation scope.

## Behavioral lessons and gaps

ITK-SNAP makes geometry and layer roles explicit, offers drawing-over/label-lock policies,
maintains multiple image/segmentation layers, and uses specialized UI models and renderers.
Editing includes brush shapes/adaptive modes, polygon, interpolation, region competition/snakes,
cutting and 3D interactions. Sessions/workspaces, image information, metadata, registration,
statistics, mesh controls and extensive shortcuts reduce mode ambiguity for trained users.

PKD QC should adopt explicit geometry validation, immutable AI baseline, label protection,
demand-driven cached work, compound undo, stateful review navigation, and clear interaction
feedback. It should not clone ITK-SNAP's global state, broad snake workflow, remote systems, or
every modality/tool. Cyst-region review is a PKD-specific layer over an ordinary mask and is
more valuable here than generic feature parity.

## Independent implementation rule

For each borrowed behavior: write a product requirement without source expressions, define UI
and geometry examples, implement against PKD QC abstractions, and add black-box tests. Record
only the ITK-SNAP file(s) used to understand behavior. Do not paste algorithms, comments,
constants, UI text, or code structure.
