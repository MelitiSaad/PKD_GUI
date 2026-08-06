# Round 1H.1 completion audit

| Requirement | Complete before H.1 | Partial before H.1 | Missing before H.1 | Coverage/action in H.1 |
|---|---:|---:|---:|---|
| Layer-local model, IDs, labels, history, save state | Yes | | | Retained `SegmentationLayers`; expanded guard/background tests. |
| Layers UI | | | Yes | Added compact dock with active/dirty/path/visibility rows and add, blank, rename, remove, order, opacity controls. |
| Add/replace/cancel | | Model only | UI workflow | Added recommended Add and guarded Replace dialogs; validation occurs before collection mutation. |
| Active-layer binding | | Aliases existed for first layer | Switching | Central activation now rebinds controller, history, labels, volume scheduling, review state, rendering, save document alias, recovery session, and active-only 3D. |
| Multi-layer 2D rendering | | Items existed | Live controls | Dock mutations immediately refresh independent LUT/data items and remove absent items. |
| Save/Save As/Save All | | Core primitives | UI and lifecycle | Active saves use the layer model; Save All is visible, stops on cancellation/failure, and retires only completed layer recovery. |
| Lifecycle guards | | Single-document guard | Layer/case prompts | Added per-layer Save/Discard/Cancel and named multi-layer Save All/Discard All/Cancel. |
| Recovery/autosave | | Stable IDs only | Live orchestration | Added independent sessions and checkpoints for every dirty layer plus retirement race checks. Workspace layout restoration remains excluded. |
| Background safety | | Case/revision only | Layer identity | `TaskTag` and scheduler now isolate by case, layer, revision; cleanup applies to its source layer and UI-only results require the same active layer. |
| Region Review/volumetry/3D | | Active aliases | Per-layer context | Review state/index is cached by layer; stale UI results cannot populate a newly active layer; 3D is explicitly active-only. |
| Real Qt workflow | | | Local runtime unavailable | Real Qt tests remain in the suite for CI; Windows manual QA is documented. |

## Round 1H.2 acceptance status

| Area | Implemented and verified | Implemented, awaiting real Qt/CI | Incorrectly wired | Out of scope |
|---|---|---|---|---|
| Core layer identity, label isolation, validation, history, saves | Unit-tested | | None found | Cross-layer Boolean operations and merged export |
| Layers dock and active-layer rebinding | Model/signals inspected | Real widget workflow test added | None confirmed locally | Visual redesign |
| Independent 2D rendering and global `S` | Descriptor invariants unit-tested | Real `ImageItem`, QAction and focus tests added | None confirmed locally | Multi-layer 3D |
| Recovery/background isolation | Deterministic case/layer/revision tests pass | UI autosave race coverage added for CI | None found | Workspace persistence |
| Region Review, volumetry and 3D | Layer/revision guards inspected | Active-switch Qt acceptance remains CI-gated | None confirmed locally | Cross-layer statistics |

The acceptance environment could not download `pytest-qt` or Ubuntu Qt runtime
packages because its HTTP proxy returned 403. Consequently the added real Qt
tests are mandatory CI checks, but are not represented here as locally passing.

The audit was based on the diff from `9ad0c72` through `ed0ef67`, the five original
Round 1H tests, and direct inspection of `MainWindow`, `ToolController`,
`PlaneWidget`, `LabelPanel`, background processing, Recovery v2, Region Review,
volumetry, navigation, saving, and close/drop handlers.
