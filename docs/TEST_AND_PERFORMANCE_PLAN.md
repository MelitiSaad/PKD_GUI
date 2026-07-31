# Test, QA, and performance plan

## Risk-based test pyramid

**Core/property tests:** randomized plane round trips and affine world coordinates; strict label
validation; exact command/compound-command undo; draw-over policy for every operation; volume
from affine determinant; component fingerprint/remap. **Format fixtures:** NIfTI qform/sform,
units, scaling, endian/dtypes, sparse/noncontiguous IDs, empty/NaN/Inf/fractional; DICOM axial,
oblique, reversed, multi-series, localizer, gap, duplicate, enhanced multiframe, compressed and
malformed. Segmentation resampling tests assert nearest-neighbor only.

**Document/fault tests:** kill/fail before/after each temp write, fsync and replace; corrupt JSON,
truncated label array, changed same-shaped source, low disk, read-only directory; dirty close and
case switch Save/Discard/Cancel; original baseline hash; autosave concurrency and stale revision.

**GUI tests:** Qt Test mouse/key gestures in all planes at zoom/pan/DPI; crosshair and brush screen-
voxel correctness; W/L, opacity/visibility/lock/isolate; dialog focus and keyboard-only region
review; 3D missing/backend failure; clean close. Pixel screenshots supplement but never replace
state assertions. Run a known asymmetric RAS/LPS phantom with visible orientation markers.

**Clinical workflow verification:** de-identified CT/MR cases spanning orientation, anisotropy,
field strength/contrast and 1–1000+ components. Independent reference reader checks overlay and
volumes. Save/reload labels and world coordinates must be identical. Record task completion,
errors, near misses and recovery from interruption.

## What current tests prove

`tests/test_core.py` proves small-array LUT/volume arithmetic, elementary diff undo/redo,
morphology, plane bijections, anisotropic aspect ratio, protected brush/lasso behavior, affine
mismatch rejection and one recovery happy path. It does not cover real Qt interaction, DICOM,
malformed labels, metadata, lifecycle, fault atomicity, threading, 3D, accessibility, packaging,
or clinical data. `make_preview.py` proves synthetic offscreen construction/rendering only.

## Benchmark matrix and acceptance instrumentation

Use 256×256×128, 512×512×600 and representative 1024/in-plane or 1,000-component cases on a
declared reference workstation. Record median/p95/p99 wall time, peak/resident memory, allocations,
UI main-thread blocked interval and revision correctness.

| Benchmark | Required measurement / initial target |
|---|---|
| cold/warm startup | event loop and usable empty window; <2 s warm |
| image/seg load | decode, canonicalize, validate, initial slice; progress/cancel; <5 s typical CT |
| brush | event-to-model and input-to-present, radii 1/4/16/40, 3 planes; p95 <50 ms visible |
| slice change | extraction/LUT/upload under active jobs; p95 <100 ms |
| undo/redo | small stroke, million-voxel region, stack cap; typical p95 <250 ms |
| manual save/autosave | snapshot, serialize, fsync/replace, blocked UI time; UI block <50 ms |
| volume | dense/sparse IDs, finite filtering; result <1 s typical after edit coalescing |
| components | 10/100/1000/10000 components; full and local invalidation; local p95 <500 ms |
| morphology/interpolation | changed bbox/full case, cancel/stale result, peak copies |
| 3D | per label, downsampling, cancel/stale result; zero brush latency regression |
| memory | baseline plus image/seg/baseline/history/jobs; enforce documented budget and no growth |

`benchmarks/brush_interaction.py` is retained as a microbenchmark, but add Qt frame timestamps and
dirty-rectangle profiling before drawing end-to-end conclusions. CI runs correctness and small
performance smoke thresholds; nightly dedicated hardware records trends without flaky hard gates.

## Release gates

* P0 suite passes on Windows target and Linux CI; no critical/high unresolved data-integrity bug.
* Static analysis, dependency/license/SBOM and malware/signature checks pass.
* Clean-machine installer/uninstaller and upgrade/migration tests pass.
* DICOM remains feature-flagged off until geometry fixture and phantom gates pass.
* Performance targets are met without stale background results or memory-budget violations.
* A human factors session verifies the organ and 300-region cyst walkthrough and interruption
  recovery; deviations are documented, not hidden by averages.
