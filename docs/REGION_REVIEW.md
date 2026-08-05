# Region Review (Round 1F)

Region Review is a navigation and review layer over an ordinary segmentation. It
never changes the NIfTI label model, never requires one label per cyst, and never
renumbers, recolors, splits, or merges labels automatically.

## Supported labeling workflows

* **One-color masks:** all cysts can share one numeric label, such as label 1.
  Disconnected components inside that label become temporary review items.
* **Individually colored masks:** each cyst can have its own numeric label and
  color. Label-level grouping treats each included nonzero label as one review
  item.
* **Mixed masks:** components are computed independently inside each numeric
  label. Touching voxels with different labels never merge into one component.

Two same-label cysts that physically touch are one connected component. The
application cannot infer two individual measurements until the user explicitly
separates or relabels them.

## Grouping modes

The `Group regions by` control selects the review queue without modifying the
segmentation:

* **Connected regions:** each disconnected component inside each included label
  is one item.
* **Labels/colors:** each included nonzero numeric label is one item, even if it
  has disconnected pieces.
* **Labels with connected regions:** label summaries are shown with their child
  connected components.

Changing modes reuses the current index when possible and does not change total
volume. Included labels control the aggregate total and avoid double counting.

## Measurements

Region volumes use the Round 1C geometry contract:

```text
component_volume_mm3 = component_voxel_count * abs(det(image_affine[:3, :3]))
component_volume_ml = component_volume_mm3 / 1000
```

The index records per-component, per-label, and total included voxel counts,
mm³, and mL. Component records also store voxel and world bounding boxes,
centroids, a representative voxel inside the component, slice range, and largest
axial cross-section.

## Connectivity and flags

Connected components support 6-, 18-, and 26-neighbour connectivity. The initial
default is 26-neighbour connectivity and the setting is explicit in the review
state.

Initial non-diagnostic attention flags are:

* very small physical volume;
* one-slice component;
* touches image boundary;
* changed after review.

Flags are prompts for reviewer attention only. They do not diagnose disease,
reject a cyst, delete voxels, or alter labels.

## Stable fingerprints and review-state remapping

Transient numbers such as `Region 27` are queue positions, not permanent IDs.
Each connected component has a fingerprint containing the numeric label, bounding
box, quantized centroid, voxel count, and a checksum of component voxel indices.
Exact fingerprint matches keep review state. A one-to-one high-overlap match is
marked `changed` and requires re-review. Split or merge ambiguity is left
unreviewed.

## Background indexing and edit invalidation

Component indexing runs through the Round 1E background task service using an
immutable snapshot tagged with document id, segmentation revision, connectivity,
grouping parameters, and included labels. Stale results from old documents or old
revisions are discarded. Current implementation uses correctness-first full
rebuild fallback after edits unless local split/merge safety can be proven.

## Navigation, isolation, and deletion

Navigating to a connected region moves the crosshair to a representative voxel
that is actually inside the component and does not create history entries.
Isolation is rendering/UI state only and leaves the segmentation array unchanged.

Connected-region deletion references the exact indexed voxel set and revision,
refuses stale indexes, removes only that component, and is committed as one
undoable command. Whole-label deletion is a separate action labelled `Delete
entire label` and previews label-level scope before committing one undoable
command.

## Progress persistence and PHI policy

Review progress is metadata and does not alter NIfTI label values. It is stored
atomically under the application data directory in `region_review/`, not next to
the segmentation file. The record stores a schema version, hashed technical
identity, queue settings, included labels, and reviewed fingerprints. It does not
store patient names, medical-record numbers, demographics, or unnecessary DICOM
tags. Identity mismatch blocks automatic reuse.

## Performance expectations and limitations

After indexing, navigation should be fast enough for keyboard-first review of
hundreds of regions. Full rebuilds are coalesced and performed outside the UI
thread. The component index stores exact flat voxel indices for safe deletion,
which costs memory proportional to nonzero voxel count. Same-label touching
regions remain a known limitation until explicit split/relabel tools are added.
