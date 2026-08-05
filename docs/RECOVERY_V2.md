# Recovery v2 format and lifecycle

Recovery is an emergency checkpoint for unsaved edits after an unexpected exit. It is not a
manual Save, is never described as an exported segmentation, and creates no sidecar beside a
user's segmentation.

## On-disk layout and commit protocol

```text
sessions/<random-session-id>/
  generations/
    <generation-id>/
      labels.npy
      manifest.json
    <older-generation-id>/...
    .tmp-<generation-id>/...       # incomplete; never discoverable
```

A generation uses random session and generation identifiers. The writer creates a uniquely
named temporary directory, writes and `fsync`s `labels.npy`, calculates its SHA-256, writes and
`fsync`s the manifest, and atomically renames the temporary directory to the unique committed
generation name. The generations directory is then flushed where the platform supports it.
No existing directory is replaced, avoiding Windows directory-replacement assumptions. The
previous committed generation remains untouched until commit completes. Temporary directories
are ignored. The newest two committed generations are retained; cleanup occurs only after the
new commit, so at least one prior generation exists throughout replacement.

## Manifest schema (version 2)

All fields are required unless marked optional/null:

| Field | Meaning |
|---|---|
| `schema_version` | Integer `2`. |
| `session_id`, `generation_id` | Random identifiers; must match containing directories. |
| `created_at`, `updated_at` | Unix timestamps for session creation and checkpoint update. |
| `segmentation.file` | Relative data filename (`labels.npy`). |
| `segmentation.shape`, `segmentation.dtype` | Exact array contract; dtype must be `uint16`. |
| `segmentation.sha256` | SHA-256 of the complete serialized array file. |
| `source_image.type` | Extensible locator type (`nifti-file` or generic `file`). |
| `source_image.locator` | Normalized source locator needed to reopen the image. |
| `source_image.size`, `mtime_ns`, `sha256` | File identity captured once when the session starts. |
| `source_image.shape`, `affine`, `spacing` | Loaded canonical geometry. |
| `source_image.identity_sha256` | Digest protecting the coherent identity record. |
| `source_shape`, `source_affine`, `voxel_spacing` | Explicit geometry contract, matching identity. |
| `segmentation_path` | Current user output path; optional/null for never-saved work. |
| `revision` | Current logical document revision. |
| `saved_revision` | Last successfully manually saved revision; optional/null. |
| `dirty` | Must equal whether `revision` differs from `saved_revision`. |
| `application_version` | Application version; optional/null when unavailable. |

No patient name, medical record number, DICOM tags, or other unnecessary patient metadata is
stored. Invalid-generation markers contain categorical reasons only, never source paths.

## Validation and fallback

Discovery checks the schema and required fields, identifiers, data existence, SHA-256, readable
shape and dtype, revision/dirty consistency, geometry consistency, identity-record digest, and
the current source file's size, modification time, and SHA-256. An invalid newest generation is
marked with a PHI-safe `INVALID.txt` and the prior generation is tried. Invalid data is retained
for diagnosis rather than silently deleted. Recovery v1 lacks a trustworthy source fingerprint;
it is retained and marked as legacy/manual-review-required, but never silently trusted as v2.

Successful manual Save/Save As, explicit Discard, and clean close retire the session. Cancel
leaves it intact. A recovered document restores its path, current and saved revisions, and dirty
state, and remains visibly unsaved until the user explicitly saves or discards it.

## Round 1G autosave retirement rule
Manual Save/Save As, Discard, case replacement, new segmentation, and clean close retire the active recovery session before results from an already-running autosave are allowed to apply. Workers still use immutable snapshots and transactional generation directories; stale or cancelled autosave results must not recreate valid recovery data after the session is retired. Cancelled dialogs and failed manual saves preserve dirty recovery data.

## Round 1H layer scope
A case has one reference image and an ordered collection of stable-ID segmentation layers. Arrays and numeric label IDs remain layer-local and are never flattened or offset. Only the active layer supplies editing, history, Region Review, volumetry, edited slices, and 3D context; 2D rendering composites independently generated slices for all effectively visible layers. Background and recovery work must match case ID, layer ID, and source revision before application. Recovery remains per-layer; full workspace layout persistence is not implemented.
