# Round 1I correction-tool audit

Intelligent Fill is separate from ordinary Fill. It reuses the canonical plane
mapping in `core.planes`, Threshold Brush's current intensity band, the shared
`LabelProtectionPolicy`, immutable background snapshots/tags, and one
`EditCommand` recorded by the active layer's bounded `History`. Existing fill,
brush, lasso, cleanup, Region Review, and save behavior is unchanged.

New code consists of a Qt-free iterative connected-region preview, a compact
modeless parameter dialog, a temporary overlay item, and MainWindow coordination
for seed selection/background preview/apply/cancel. The preview is never placed
in segmentation data. Apply revalidates case, layer, and revision and creates one
exact voxel diff. Full workspace persistence and any organ/cyst detection remain
out of scope.
