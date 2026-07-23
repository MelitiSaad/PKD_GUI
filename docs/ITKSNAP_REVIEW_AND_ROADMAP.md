# ITK-SNAP source review and PKD QC roadmap

**Review date:** 2026-07-23  
**ITK-SNAP source reviewed:** `itksnap-master.zip` at the repository root
(`679ba76a639df6c4594015161a324c51cc8dfd86`).  The archive was unpacked to a
temporary directory for this review; it is not a product dependency and is not
included in the application build.

This is a source-level design review, not a feature comparison based on product
memory.  In particular, the review inspected ITK-SNAP's `IRISApplication`,
`GlobalState`, `IRISSlicer`, `GenericSliceRenderer`, paintbrush/polygon
interaction modes, `UndoDataManager`, `SegmentationStatistics`, and mesh
pipelines.

## Executive decision

PKD QC should borrow ITK-SNAP's *engineering patterns*—explicit image geometry,
shared MPR cursor, diff-based edits, cached/demand-driven work, and contextual
tools—but not its broad, mode-heavy workstation.  The product remains a
single-purpose workflow:

1. Open CT.
2. Load AI labels.
3. Review and correct.
4. Calculate kidney volumes.
5. Save a geometry-preserving result.

Advanced correction and measurement features should be reachable from the
Segmentation or Review menus, shortcuts, and small contextual popovers, rather
than expanding the always-visible tool rail.

## What the ITK-SNAP source does

### Architecture and data model

* `Logic/Framework/IRISApplication.{h,cxx}` is a high-level driver.  It owns
  separate IRIS and SNAP image-data modes, global state, label/color history,
  preprocessing preview wrappers, and mesh management, then rebroadcasts model
  events to the GUI.
* `Logic/Framework/GlobalState.{h,cxx}` centralizes cursor, active layer/label,
  tool settings, mesh options, and segmentation-mode settings through property
  models.  This makes bindings consistent, but couples a very large collection
  of application concerns into one state object.
* `Logic/ImageWrapper` represents main, overlay, segmentation, and mesh layers
  with image geometry/coordinate transforms.  Label colors and per-label
  visibility are held by `Logic/Common/ColorLabelTable` and use history is
  retained by `LabelUseHistory`.

### MPR, rendering, and interaction

* `Logic/Slicing/IRISSlicer` / `NonOrthogonalSlicer` produce slices in display
  coordinates, including non-orthogonal image support.  `GUI/Renderer/
  GenericSliceRenderer` composes image, overlay, and decorations as rendering
  props rather than rebuilding application state per pane.
* Slice windows share a global cursor and use interaction-delegate widgets.
  `PaintbrushInteractionMode` and `PolygonDrawingInteractionMode` own the
  modal gesture details; `PaintbrushRenderer` draws a cached brush outline and
  avoids redundant collinear outline points.
* The source supports polygon drawing, paint/fill-like operations, threshold
  preprocessing previews, watershed/region tools, active-contour (snake),
  random-forest/GMM workflows, and ROI-driven workflows.  This power is exposed
  through many stateful modes and dialogs.

### Editing, undo, interpolation, and statistics

* `UndoDataManager` stages voxel deltas, groups them into named commits, and
  stores run-length-encoded regions under a size limit.  It keeps a single
  position through a commit list for undo/redo.
* The source includes contour/interpolation-related ITK filters and a
  `MorphologicalContourInterpolator`; its automatic segmentation stack is
  centered on threshold/edge/GMM/RF preprocessing followed by level-set snake
  evolution, not a lightweight QC correction operation.
* `SegmentationStatistics` computes label voxel counts, physical volume, and
  per-image-layer count/sum/sum-of-squares/mean/standard deviation.  Mesh
  export/import and measurements are separate workflows.

### 3D and performance strategy

* `MeshManager` associates a mesh pipeline with a label layer/time point and
  uses modification timestamps to determine dirtiness.  `MultiLabelMeshPipeline`
  scans labels, calculates per-label counts/bounding boxes/checksums, then
  generates each label mesh only from a padded region of interest.  Its ITK/VTK
  filters release intermediate data.
* `BrushWatershedPipeline` preprocesses a selected ROI and can recompute a
  watershed level without rebuilding the whole setup.  This is a useful
  cache-boundary pattern, although its algorithm and complexity do not fit the
  first-line kidney QC workflow.

## Comparison

### What ITK-SNAP does better

| Area | Source-level advantage | PKD QC response |
|---|---|---|
| Geometry and layers | Mature wrapper/layer model supports overlays, obliquity, time points, and image-to-anatomy transforms. | Preserve the current affine validation; add only the layer concepts required for AI-original versus corrected labels. |
| Advanced correction | Polygon, region/watershed, threshold, active-contour, and ROI pipelines cover difficult segmentation cases. | Adapt predictable polygon and connected-threshold tools first; do not introduce a snake workflow. |
| Statistics | Label statistics include intensity moments across image layers and export support. | Add focused renal intensity statistics and optional measurements behind an Advanced Measurements entry. |
| 3D | Per-label ROI meshing and dirty checks avoid unnecessary whole-volume work. | Adopt revision/request IDs, cancellation, ROI meshing, and stale-result rejection. |
| Large-image plumbing | Image wrappers, ITK pipelines, RLE iteration, release flags, and timestamp checks are mature. | Continue profiling PKD QC's concrete NumPy/Qt hot paths rather than porting the stack. |

### What PKD QC already does better

| Area | Current advantage |
|---|---|
| Default workflow | The main screen is already constrained to image loading, label review/correction, volumetry, and save. |
| Interaction clarity | Four primary mouse tools, right-click erase, and a compact tool rail are easier to learn than a large family of modes. |
| Safety | Geometry validation, atomic autosave/recovery, explicit dirty state, and bounded diff undo directly address routine AI-QC risks. |
| Editing performance direction | Cached brush stamps, one-command strokes, and avoiding cross-pane redraws during a stroke are purpose-built for quick correction. |
| 3D policy | 3D is explicitly on-demand by default, protecting the central 2D review loop. |

### Features worth adapting

1. **Polygon/lasso correction:** a transient canvas gesture that rasterizes to
   the current plane, with Add/Remove controls and one undo command.
2. **Connected threshold:** a seed-based 2D/3D intensity-connected region with
   conservative tolerance defaults and preview-before-apply.
3. **Focused label guards:** lock, isolate, hide other labels, paint-inside, and
   paint-outside policies.  Each must be visible as a small current-policy chip.
4. **Original AI comparison:** retain an immutable AI baseline in the session;
   offer hold-to-compare or a subtle diff/outline, not duplicate permanent
   overlays by default.
5. **Dirty, cancellable 3D:** run meshing off the UI thread, attach each result
   to a segmentation revision and request ID, and discard stale completions.
6. **Intensity statistics:** per kidney label count, volume, HU mean/median,
   standard deviation, min/max, and optional percentiles, with CSV copy/export.

### Features not to copy

* A separate automatic-segmentation/snake application mode, GMM/RF trainers,
  or a wizard-led multi-stage segmentation pipeline.  This app reviews AI
  output; adding another primary segmentation paradigm impairs clarity and
  validation.
* A general-purpose multi-layer workstation, timeline/4D workflow, remote image
  system, mesh import/export suite, or extensive preferences surface.
* Always-visible toolbars for every operation.  Powerful tools need discoverable
  menus and shortcuts, not permanent visual weight.
* ITK-SNAP's global catch-all state object.  PKD QC should keep Qt-free domain
  state in small core models and keep rendering/UI state in the view/controller.
* Mesh smoothing that changes the apparent anatomy without clearly marking it
  as display-only.  Measurements and saved labels must always derive from the
  original voxel labels and affine.

## Prioritized implementation plan

The order follows correction speed, mistake prevention, QC throughput,
research/measurement value, then polish.  Every stage must preserve affine,
use a single undoable command per user action, update autosave/edit state, and
include focused regression tests.

| Priority / stage | Feature and why | UI / simplicity | Difficulty | Benefit |
|---|---|---|---|---|
| 0 | **Establish reproducible brush benchmarks and dirty-region instrumentation.** This identifies whether NumPy stamping, LUT conversion, or Qt upload is the remaining bottleneck before changing rendering. | Developer-only benchmark command and optional debug timing; no end-user control. | Medium | Critical foundation |
| 1 | **Partial overlay updates for brush strokes.** Update only the receiving plane's changed rectangle, avoid full `setImage`/LUT conversion where the graphics backend permits it, and coalesce repaint requests to one event-loop frame. | Invisible behavior change.  Keep the existing brush controls. | High | Very high |
| 2 | **Polygon/lasso.** Fast large boundary repair reduces hundreds of brush dabs to one action. | Segmentation → Correct with polygon; shortcut; a small contextual Add/Remove chooser appears only while active. | Medium | Very high |
| 3 | **Connected threshold / intelligent fill.** A seeded, tolerance-bounded correction fixes undersegmented kidney regions quickly. | Segmentation → Intelligent fill opens a compact popover.  One-click default uses the active label; advanced tolerance/connectivity/3D options stay collapsed. | Medium–High | High |
| 4 | **Label safety policies.** Lock and isolate prevent accidental cross-label edits; paint-inside/outside makes corrections constrained and repeatable. | A compact protection popover near the active-label control shows the active policy; locks are visible in the label list. | Medium | High |
| 5 | **Review state, bookmarks, and annotations.** Enables triage across hundreds of studies and gives difficult slices a durable audit trail. | A thin slice-state marker and review menu; annotation list remains in an expandable Review dock. | Medium | High |
| 6 | **AI-original comparison.** Makes every correction auditable and speeds confidence checks. | Hold `A` to show baseline, or Review → Compare AI segmentation.  Default remains corrected overlay only. | Medium | High |
| 7 | **Advanced measurements/statistics.** Supports research while preserving volume as the default result. | Measurements opens an on-demand dialog/dock; volume panel remains unchanged. | Medium | Medium–High |
| 8 | **Background 3D meshing.** Makes 3D reliable without taxing 2D correction. | Existing Update 3D reports progress and exposes Cancel only while running; stale results never replace current view. | High | Medium |
| 9 | **Professional polish.** Keyboard shortcut refinement, empty/error states, tooltips, and non-modal status feedback. | No new permanent panels. | Low–Medium | Medium |

## Stage-0 and stage-1 performance acceptance criteria

The existing UI already redraws only the active overlay during a live stroke.
Before a partial-image implementation, record a baseline on representative
512×512 and 1024×1024 slices with radii 4, 16, and 40 using a fixed stroke
path.  Record:

* stamp throughput and changed-voxel count;
* time in mask/stamp, command bookkeeping, slice extraction, LUT/QImage work,
  and graphics upload; and
* end-to-end frame interval (median and p95).

Stage 1 is accepted only when it improves the p95 live-stroke frame interval on
the large case, keeps every painted voxel and undo/redo result identical, and
does not cause cross-plane overlays to lag after stroke completion.  A headless
benchmark may validate core stamping; interactive frame measurements require a
desktop OpenGL/Qt environment.

## Modern workflow design rules

* **One visible primary task at a time.** The default rail stays Crosshair, Pan,
  Brush, Fill.  Lasso and intelligent fill are invoked contextually.
* **Preview before destructive automation.** Threshold/fill previews show the
  selected region and changed-voxel count; Apply produces one named undo step.
* **Make protection legible.** Never silently constrain paint.  State is shown
  beside the active label and in the status text.
* **Keep AI provenance immutable.** The baseline is read-only, stored with
  session metadata where feasible, and never confused with the editable result.
* **Protect editing from background work.** 3D and statistics operate from a
  snapshot/revision and cannot block brush interaction or overwrite newer data.
* **Test at the core boundary.** Rasterization, connected-region rules,
  geometry, history, review metadata, and stale-result rejection are Qt-free
  tests; GUI tests cover discovery and state wiring.
