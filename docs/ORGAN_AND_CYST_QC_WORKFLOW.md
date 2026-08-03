# Organ and high-volume cyst QC workflow

## Shared document model

Each case contains a reference image and one editable ordinary label map, whether loaded from an existing/AI file or created blank. Optional comparison layers and review metadata may be added later. Organ and cyst
files remain separate normal segmentations; no artificial organ–cyst hierarchy is introduced.
Connected components are ephemeral indexes `(component id, label id, bbox, centroid, voxel
count, largest-slice location, flags)` and never replace saved label values.

## Organ correction

1. Open image and organ mask; geometry/provenance checks show a concise pass/fail summary.
2. Number keys or a compact searchable label list activate kidney/liver/spleen; locked labels
   cannot be overwritten by any tool. `Q` isolates the active organ; hold `A` shows AI baseline.
3. `N/P` jump between slices containing the active label; `Shift+N/P` jump to QC findings:
   disappearance/gap, small disconnected island, unexpected component count, boundary contact.
4. Correct locally with protected brush/lasso/fill. Destructive cleanup always previews changed
   voxels and conflicts. “Remove islands” uses mm³ plus component list; hole fill is 2D-previewed.
5. Explicitly mark two corrected slices, preview physical-space interpolation, then commit one
   compound undo action. Never infer endpoints from all label-bearing slices.
6. A dock shows per-organ/total volume and delta from AI. Warnings identify discontinuity or
   implausible change without diagnosing disease.
7. Use standard Save for the current segmentation path or Save As for a user-selected path/format; explicit confirmed overwrite is allowed and no suffix or sidecar is forced.

## Cyst region review

On load/background refresh, component analysis indexes each nonzero mask label using configured
3-D connectivity. Default sorting is descending physical volume; alternatives are superior-to-
inferior, left-to-right and flagged-first. Incremental edits invalidate only components touching
the changed bounding box plus a one-voxel halo; large/ambiguous changes trigger a cancellable
background rebuild. Old results remain labeled stale and are never mixed with new revision data.

### Reviewer walkthrough (minimal mouse)

1. Press `R` to enter Region Review. Header reads **Region 27 of 316 · 1.8 mL · flagged:
   boundary** and centers all planes at the component centroid, selecting its largest
   cross-sectional slice and fitting a padded physical bounding box.
2. Other regions dim (not deleted); hold `A` compares original AI, `Q` toggles isolation.
3. If correct, press `Space` to mark reviewed and advance. Review state changes metadata only.
4. If false positive, press `Delete`; a preview states voxel/mL change, then one command deletes
   the exact component and advances. `Ctrl+Z` restores voxels and review state.
5. Paint a missed boundary with `B`; on stroke end the local component index refreshes. Use `S`
   to split at a drawn cut plane/lasso and `J` to preview joining selected fragments; neither
   changes label IDs unless explicitly requested.
6. `F` opens flagged-only queue (tiny/noise, holes, unusual compactness/elongation, boundary
   touch, merge/split ambiguity). `[`/`]` navigate previous/next without accepting.
7. Interrupt at any point: autosave persists segmentation revision, queue definition, sort,
   reviewed region fingerprints and current position. On recovery, fingerprints remap to current
   components; ambiguous matches are shown as needing review.
8. Finish screen reports reviewed/unreviewed/changed counts, region count and total cyst volume;
   optional CSV exports stable per-region measurements without changing the label map.

Region identity must not rely on transient component number. Persist a fingerprint from source
layer, label, quantized centroid/bbox, voxel count and overlap matching; after edits, preserve
reviewed status only above a documented overlap threshold, otherwise mark “changed—re-review.”

## QC flags (non-diagnostic)

* tiny physical volume; isolated one-slice component; hole; touches image boundary;
* unusually large change versus baseline; narrow bridge likely joining components;
* active organ absent between present slices; unexpected component count;
* invalid geometry/value warnings are blocking, not flags.

Thresholds are configurable and displayed. Flags prioritize attention; they never automatically
delete anatomy or claim clinical abnormality.

## Measurable usability targets for a representative 300-region case

| Measure | Initial target |
|---|---:|
| Median navigation to next region/problem | <250 ms after background index ready |
| Median no-change review | ≤2 s and one key (`Space`) |
| Corrected region | ≤3 shortcut actions plus needed paint gestures |
| Mouse clicks for accept/delete | 0 normally; one confirmation only for policy-defined large deletion |
| Full straightforward 300-region review | ≤15 min; complex cases separately stratified |
| Accidental cross-label edits | 0 in scripted protected-label test; <0.1% observed usability sessions |
| Undo recovery | exact voxels and review state in <250 ms for typical region |
| Crash/interruption recovery | ≤30 s lost work; resume same queue position with explicit ambiguity |
| Component refresh | <500 ms p95 local; <5 s cancellable full rebuild on reference workstation |

Validate targets with at least 10 representative de-identified cases and 5 trained reviewers;
report distributions rather than a single mean.
