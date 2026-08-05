# Round 1E background processing

Round 1E adds an incremental task service for expensive read-only and whole-volume
operations.  It is designed to keep UI-owned document state authoritative while
workers operate only on immutable snapshots.

## Ownership and thread boundaries

`BackgroundTaskService` owns task scheduling, cancellation tokens, coalescing,
worker futures, and stale-result rejection. The active document owns live image,
segmentation, history, save state, Recovery v2 session, and Qt widgets. Workers
must never mutate those objects. They receive immutable array snapshots and return
new values. `MainWindow` drains completed futures on a Qt timer and applies valid
results on the UI thread.

## Snapshot strategy and memory cost

A snapshot is a contiguous copy of the exact segmentation revision being queued.
The snapshot array is marked read-only, records its revision and document id, and
has memory cost `segmentation.nbytes`. Capture is a brief UI-thread copy; the
background benchmark reports capture time and estimated memory so future sparse or
chunked snapshots can be justified with measurements.

## Tags, coalescing, and stale rejection

Every task has a `TaskTag`: document id, segmentation revision, task type, and
stable parameters. A result may apply only when the active document id and
revision still match. Volumetry, mesh preparation, and autosave are latest-only:
while one job runs, at most one newer pending request is retained. Superseded
read-only jobs are cooperatively cancelled when practical; if an uninterruptible
operation returns late, its result is marked stale and discarded.

## Destructive operations

Whole-volume cleanup operations run from snapshots and return a proposed new
label volume. Before application, the service revalidates document id and
revision. Valid results are converted to one `EditCommand` on the UI thread and
enter undo history as a single operation. Stale, failed, or cancelled destructive
jobs leave the live segmentation and history unchanged.

## Autosave and Recovery v2

Autosave now snapshots the exact dirty revision and performs Recovery v2 checkpoint
writing in a background task. Commits remain serialized by latest-only autosave
scheduling for the active document. A completion message names the revision that
was actually checkpointed. If a newer revision exists when an older checkpoint
returns, the older result is stale and is not reported as the latest autosave.
Recovery v2's atomic generation, checksum, validation, source identity, fallback,
and retention rules remain unchanged.

## Cancellation and shutdown

Tasks receive a cooperative cancellation token. Cancellation before application
never changes segmentation, history, or checkpoint state. Operations that cannot
interrupt a NumPy/SciPy/pydicom/VTK call are made obsolete and discarded when they
return. Case replacement and shutdown cancel running/pending tasks; late callbacks
are ignored by document/revision validation.

## UI feedback

The UI reports "Updating…" for background volume calculation, revision-specific
"Autosaving/Autosaved" states, and concise cleanup success, stale, cancelled, or
failure messages. Interactive brush, lasso, fill, navigation, pan, zoom, and
crosshair movement remain UI-thread operations.

## Known limitations

Snapshot capture is still a full segmentation copy. Large labels may therefore
cause a measurable but bounded UI pause. 3D mesh computation is coalesced at the
service layer, but VTK/PyVista object creation remains constrained by optional
runtime availability and must stay on the render/UI thread.
