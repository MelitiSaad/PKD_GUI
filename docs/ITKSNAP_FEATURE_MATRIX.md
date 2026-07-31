# ITK-SNAP user-facing feature matrix

Status abbreviations: **V** implemented/verified in limited tests; **I** incomplete; **D**
implemented differently; **P0/P1/P2/P3** missing at that priority; **L** lower/later;
**N/A** inappropriate; **LIC** licensing/architectural investigation. “Verified” never means
clinically validated.

| Area / feature | PKD QC status | ITK-SNAP behavior / bundled source locus | Independent PKD QC direction |
|---|---|---|---|
| NIfTI load/save | V/I | Guided native image I/O, wrappers | Retain; validate types/units/qform/sform and provenance (P0) |
| DICOM | **P0** | Guided I/O and `MultiFrameDicomSeriesSorter` preserve series/geometry | UID grouping, selector, IOP/IPP affine, enhanced multiframe fixtures |
| DICOM series selection | **P0** | Guided image I/O wizard | De-identified study/series table, localizer exclusion |
| Other image formats | P2 | ITK/GuidedNativeImageIO supports broad formats | Add only validated clinical formats via ITK/SimpleITK abstraction |
| Orientation/metadata/info | I/P0 | `ImageCoordinateGeometry`, ImageInfo/Reorient models | Affine-derived markers and information panel; never silently guess |
| Multiple image layers/overlays | P2 | GenericImageData/layer associations | Ordered immutable image layers with linked geometry |
| Multimodal/color/multichannel | P2/L | scalar/vector wrappers and display mappings | First add scalar CT/MR overlays; defer RGB/vector |
| 3D+time | L | timepoint-aware wrappers/properties | Explicitly select a 3-D frame; later longitudinal workspace |
| Registration/resampling | P3 | registration models/interactions | Rigid registration; labels nearest-neighbor only, preview transform |
| Recent files/sessions/workspaces | P1/P2 | history/workspace persistence | PHI-conscious recent list and versioned case workspace |
| Segmentation load/save/import/export | I | label image wrappers and guided segmentation I/O | Strict validation, corrected-copy default, sidecar provenance |
| Geometry validation | I/P0 | explicit geometry/wrapper transforms | Shape+affine+units/handedness contract and approved NN resampling |
| Label names/colors/opacity/visibility | I | color-label model and label editor | Persist/undo metadata; per-label opacity/isolate |
| Label locking/draw-over rules | P1/I | GlobalState drawing/overwrite policies | Locked labels and visible paint policy; all tools obey it |
| Multiple segmentation layers | I/P1 | layer associations and segmentation wrappers | Wire existing core layer model: baseline/organs/cysts independently |
| Segmentation statistics/volume export | I/P1 | `SegmentationStatistics`, statistics dialog | finite stats, CSV, determinant volumes, region reports |
| Brush/eraser | V/D | paintbrush modes/renderers | Keep scoped right-erase; add physical radius and GUI tests |
| Brush shape/size | I | round/square/isotropic/adaptive choices | Physical circle/sphere and explicit 2D/3D mode (P1) |
| Polygon/lasso | V/D | polygon interaction/renderer | Existing freehand lasso; add vertices/edit/preview only if studies justify |
| Flood fill | I | paint/fill interactions respect draw-over | Add preview, connectivity and active-label safety (P1) |
| Threshold paint/region growing | I/P2 | preprocessing/threshold and snake tools | Compact connected threshold with modality-aware limits |
| Morphology/hole/island removal | I | label-constrained morphology/smoothing models | Preview, physical threshold, conflict protection (P0/P1) |
| Slice interpolation | I | dedicated interpolation implementations | Explicit corrected endpoints, max gap, compound undo (P1) |
| 3D editing/scalpel/cutting | P2/P3 | Generic3D model/interactions | Defer direct 3D paint; prioritize plane lasso and region split |
| Landmark/annotation | P2 | annotation model/renderer | QC bookmark/issue annotation, not general measurement suite |
| Axial/coronal/sagittal + linked cursor | V | slice panels/renderers | Add patient markers/phantom validation |
| Zoom/pan/window-level | V/I | navigation and intensity-curve models | GUI interaction tests, presets, linked/independent W/L |
| Layout/full pane | V | multi-panel layouts | Retain |
| Overlay opacity/label isolation | I/P1 | label appearance models | One-keystroke active label/baseline isolation |
| 3D rendering | I | mesh manager/pipelines and 3D renderer | Background revisioned mesh, cancel/progress, per-label visibility |
| 3D picking/mesh export | P2 | Generic3D interactions/mesh pipeline | Pick region/label; export only with geometry/provenance warnings |
| Multiple synchronized images | P2 | layered slice renderer | Registered overlays with shared world cursor |
| Threshold/edge preprocessing | P3 | snake preprocessing pipelines | Optional local correction assist, not primary workflow |
| Region competition/active contours/snakes | P3/LIC | LevelSet/Snake mode models/renderers | Only after user research; independent algorithm/library review |
| ROI selection/evolution controls | P3 | Snake ROI interaction and control models | Task-focused local ROI if semi-automatic corrections are added |
| AI/distributed segmentation | D/L | distributed segmentation infrastructure | AI stays external; import immutable baseline and provenance |
| Keyboard shortcuts/customization | V/I | extensive actions/preferences | Conflict detection, searchable command palette, QC-first defaults |
| Preferences | I/P2 | default behavior/appearance settings | Versioned minimal preferences, institutional policy locks |
| CLI/batch | P2 | command-line parser and utilities | Validate/measure/export/review-report commands, never implicit overwrite |
| Error handling | I/P0 | structured application exceptions/progress | Transaction rollback, actionable diagnostics, PHI-safe logs |
| Crash recovery | I/P0 | workspace/history patterns | Durable document manifest/checksum and explicit lifecycle |
| Accessibility | P2 | Qt UI/translations offer a base | keyboard-only audit, focus, contrast, screen-reader labels |
| Internationalization | L | Qt translation catalogs | Externalize strings after workflows stabilize |
| Packaging/installers | I/P1 | mature CMake/CPack platform packaging | pinned lock, signed installer, SBOM, reproducible CI |

## Prioritization principles

P0 items protect geometry/data. P1 items shorten and safeguard organ/cyst review. P2 provides
high-value workstation parity without obscuring the primary task. P3 algorithms require
validation, background execution and possibly license review. Broad time-series, color/vector,
internationalization and remote infrastructure are later unless deployments demonstrate need.
