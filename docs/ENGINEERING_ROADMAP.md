# Incremental engineering roadmap

Effort: S (days), M (1–3 weeks), L (1–2 months), XL (multi-quarter), subject to team/data.

| Priority / item | Benefit and approach | Dependencies / risks / effort | Acceptance criteria and tests | Likely subsystems |
|---|---|---|---|---|
| **P0 Geometry contract — completed Round 1C** | Prevent wrong NIfTI anatomy/orientation; `ImageGeometry`, affine-derived markers, determinant volumes, qform/sform+units policy | DICOM remains separate; **M** | RAS/flipped/oblique/shear/unit/qform tests, asymmetric phantom, save/reload and recovery compatibility | `core/geometry`, `io`, `volume`, `planes`, UI markers |
| **P0 DICOM series selector + geometry — completed Round 1D** | Preserve patient/world coordinates for DICOM, group by UID/frame, IOP/IPP affine, enhanced multiframe | De-identified fixtures, pydicom handlers; vendor variance; **L** | Oblique/reversed/mixed/gapped series match reference world coordinates and selector prevents series mixing | `core/dicom`, `io`, selector UI, recovery identity, DICOM tests |
| **P0 Strict label validation/dtype policy — completed Round 1A** | Block silent corruption; validate finite integral range before conversion | Decide uint16 vs uint32; interoperability; **S** | malformed inputs rejected with counts; max label roundtrip exact | `io`, `segmentation`, `labels`, tests |
| **P0 Safe case lifecycle and standard segmentation save — completed Round 1B** | Prevent accidental data loss; document state, normal Save/current path, Save As/user path, and Save/Discard/Cancel | Product filename/sidecar policy; **M** | every dirty close/switch and overwrite-confirmation branch tested; explicit overwrite permitted; recovery retained until disposition | `document`, `main_window`, `session`, `io` |
| **P0 Recovery v2 + transactional edits — completed** | Trustworthy rollback/restart; checksummed manifest and rollback-capable edit transaction | schema migration, storage; **M** | fault injection at write/mutation phases; source affine/hash verification; no false “unchanged” claim | `session`, commands/history/errors` |
| **P0 Multi-label safe operations — completed Round 1A** | Prevent organ overwrite; one draw-over policy used by brush/fill/morph/interpolation | Product defaults; **M** | conflict preview; other labels byte-identical under protect mode | `segops`, tools, command model |
| **P1 Baseline/layer wiring and label locks/isolation** | Direct AI-vs-corrected comparison and safe switching | P0 document model; **M** | hold-to-compare, lock enforcement for every operation, independent undo/session | `layers`, renderer, label panel |
| **P1 Organ QC navigator** | Finds gaps/islands quickly; per-label slice/flag index | background service; thresholds; **M** | <250 ms navigation, correct synthetic flag fixtures, keyboard-only path | new review core/dock |
| **P1 Cyst region review** | Makes hundreds of regions tractable; revisioned CC index, queue, focus/delete/review state | baseline/layers, worker framework; identity remap; **L** | workflow/latency targets, exact delete undo, persisted progress | review/component service, UI, session |
| **P1 Background work framework** | No UI freezes; cancellable revision-tagged volumetry, autosave snapshot, morphology, mesh | safe snapshots/memory budget; **L** | stale results rejected; input latency maintained under jobs; cancellation tests | task service, session, volumetry, 3D |
| **P1 Safe cleanup/interpolation UX** | Fast corrections without hidden bulk edits; preview + physical parameters + compound undo | transaction and policy services; **M** | one undo per action; explicit endpoints; changed/conflict counts exact | segops/tools/dialogs |
| **P1 Professional deployment baseline** | Repeatable hospital evaluation | license decision, supported OS, certificates; **L** | pinned lock/SBOM, CI artifact, signed installer verification, clean-machine test | dependencies/spec/CI/installer |
| **P2 Statistics/CSV/review report** | Reproducible measurement output | provenance schema; **M** | determinant volume, finite stats, locale-stable CSV golden tests | volumetry/report UI/CLI |
| **P2 Image/seg metadata and recent workspaces** | Context and resume efficiency | PHI/privacy policy; **M** | metadata allowlist, encrypted/disabled recents option, migration tests | document/session/UI |
| **P2 Advanced manual parity** | Polygon vertices, annotations, 3D picking/export, physical brush | P1 stable editing; **L** | geometry and undo golden tests; usability evidence | tools/renderers/mesh |
| **P2 CLI validation/batch report** | Automatable QC gate | stable core/document APIs; **M** | deterministic exit codes/JSON, never overwrite by default | new CLI/core |
| **P2 Accessibility/preferences** | Keyboard and institutional usability | stabilized UI; **M** | focus traversal, contrast, screen-reader names, shortcut conflicts | all UI/settings |
| **P3 Registration/resampling** | Align secondary images/masks | geometry contract, ITK/SimpleITK license review; **XL** | physical landmark/error bounds; NN-only labels; transform provenance | registration service/UI |
| **P3 Semi-automatic local correction** | Accelerate difficult boundaries | clinical evaluation datasets; algorithm/license validation; **XL** | preview/cancel/undo, accuracy and latency protocol | algorithm workers/UI |
| **Later** time series, color/vector, internationalization, plugin/remote systems | General workstation breadth only when demanded | product strategy; **XL** | separate approved requirements | architecture-wide |

## Recommended first implementation milestone

**Milestone 0: Trustworthy I/O and document lifecycle** comprises the first five P0 items but
delivers in small pull requests: validation/dtype tests; geometry model and NIfTI contract;
DICOM grouping/affine/selector; safe document close/save/provenance; recovery v2; then shared
multi-label edit policy. Exit gate: known-world phantom proves L/R and all three edits, malformed
labels are rejected, Save and Save As preserve user choice and require normal confirmation for an existing destination,
save/reload is byte-equivalent in voxel labels and world geometry, and crash fault injection
recovers the last committed revision. Do not begin cyst UX before this gate.

## Decisions required from product/clinical owner

1. Repository distribution license and whether GPLv3 reuse is categorically prohibited.
2. Supported input/export formats, modalities, uint16 versus uint32 maximum label contract.
3. Radiological/neurological display convention and required on-screen orientation markers.
4. Whether DICOM is production-required now or must be disabled until validated.
5. Supported Save/Save As formats and platform overwrite-confirmation behavior (no forced suffix or mandatory sidecar).
6. Whether organs and cysts are separate files/layers by default and their authoritative IDs.
7. Connectivity (6/18/26), tiny-region thresholds, and whether per-cyst identity is ever clinical.
8. Autosave encryption/retention/location and PHI-safe logging requirements.
9. Target workstation/case sizes and representative de-identified validation corpus access.
10. Regulatory intended use, deployment owner, code-signing/SBOM/security requirements.


## Round 1A completion

Round 1A completes strict pre-conversion `uint16` validation, rollback-capable command/history transactions, exact live-stroke rollback, and a shared label-protection policy used by brush, threshold brush, erase, fill, lasso, morphology, cleanup, and interpolation. Focused regression tests prove malformed input rejection, history preservation under injected failures, exact three-plane undo/redo, and protected-label behavior. DICOM, recovery v2, Save/Save As lifecycle, navigation, background processing, and advanced parity remain deliberately untouched.

## Round 1B completion

Round 1B adds a Qt-independent segmentation document lifecycle, revision-aware dirty
tracking, standard Save and Save As actions, blank manual segmentations, explicit overwrite
confirmation, and a shared Save/Discard/Cancel guard for close and every existing case
replacement route. NIfTI output remains atomic and rejects unsupported extensions rather
than silently changing a filename. Explicit discard retires the old recovery checkpoint;
cancelled or failed saves leave the document and pending transition intact. Recovery v2,
DICOM redesign, background work, and advanced navigation remain later milestones.

## Recovery v2 completion

Recovery v2 replaces paired mutable checkpoint files with immutable, checksummed generation
directories and a versioned manifest. It validates source identity and geometry, falls back to
a prior valid generation, marks corrupt and legacy data without silently deleting it, restores
document revision/path/dirty state, and retires sessions only after explicit lifecycle outcomes.
Fault injection covers every write, commit, and cleanup boundary. Background checkpointing and
DICOM identity remain deliberately outside this milestone.

### Round 1C completion

Round 1C introduces the NIfTI `ImageGeometry` contract, determinant-based physical volumes, affine-derived patient-orientation markers, qform/sform and spatial-unit validation, an asymmetric synthetic phantom test, and save/reload geometry preservation tests. DICOM geometry remains deliberately scoped to the next milestone.

### Round 1D completion

Round 1D replaces unsafe DICOM directory stacking with PHI-safe discovery candidates, explicit series selection when multiple valid volumes exist, LPS-to-RAS geometry construction from IOP/IPP/PixelSpacing, projected-position slice ordering, strict inconsistency rejection, limited regular Enhanced CT/MR multiframe support, DICOM-source Recovery v2 identity, and NIfTI-only segmentation import. DICOM SEG, gantry-tilt correction, registration/resampling, and arbitrary multidimensional DICOM remain out of scope.
