"""Central command and shortcut policy for PKD-QC."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

RECOMMENDED_DEFAULTS = {
    "open_image": "Ctrl+O",
    "load_seg": "Ctrl+L",
    "save": "Ctrl+S",
    "save_as": "Ctrl+Shift+S",
    "new_seg": "Ctrl+N",
    "undo": "Ctrl+Z",
    "redo": "Ctrl+Y",
    "quit": "Ctrl+Q",
    "toggle_segmentations": "S",
}

@dataclass(frozen=True)
class CommandSpec:
    action_id: str
    label: str
    category: str
    default: str = ""
    context: str = "application"


def build_command_registry(tools, operations) -> dict[str, CommandSpec]:
    specs: dict[str, CommandSpec] = {}
    def add(aid: str, label: str, category: str, context: str = "application") -> None:
        specs[aid] = CommandSpec(aid, label, category, RECOMMENDED_DEFAULTS.get(aid, ""), context)
    for tid, label, _icon, _old in tools:
        add(tid, label, "Mouse tools")
    for oid, label, _icon, _old in operations:
        add(oid, label, "Cleanup")
    for aid, label, cat in [
        ("undo", "Undo", "Editing"), ("redo", "Redo", "Editing"),
        ("open_image", "Open image", "File"), ("load_seg", "Load segmentation", "File"),
        ("save", "Save segmentation", "File"), ("save_as", "Save segmentation as…", "File"),
        ("new_seg", "New segmentation", "File"), ("quit", "Quit", "File"),
        ("next_edited", "Next edited slice", "Navigation"), ("prev_edited", "Previous edited slice", "Navigation"),
        ("brush_minus", "Smaller brush", "Brush"), ("brush_plus", "Larger brush", "Brush"),
        ("brush_threshold", "Threshold brush", "Brush"), ("brush_protect", "Protect labels", "Brush"),
        ("reset_view", "Reset zoom", "View"), ("update_3d", "Update 3D", "3D"),
        ("continuous_3d", "Continuous 3D update", "3D"), ("axes_3d", "Show 3D axes", "3D"),
        ("contrast", "Contrast…", "View"), ("remove_unused", "Remove unused objects", "Cleanup"),
        ("toggle_segmentations", "Show/Hide All Segmentations", "View"),
        ("layout_grid", "2×2", "Layout"), ("layout_axial", "Axial", "Layout"),
        ("layout_coronal", "Coronal", "Layout"), ("layout_sagittal", "Sagittal", "Layout"),
        ("layout_3d", "3D", "Layout"),
        ("region_toggle", "Region Review", "Region Review"), ("region_next", "Next region", "Region Review"),
        ("region_prev", "Previous region", "Region Review"), ("region_reviewed", "Mark reviewed and advance", "Region Review"),
        ("region_unreviewed", "Mark unreviewed", "Region Review"), ("region_delete", "Delete current connected region", "Region Review"),
        ("region_isolate", "Isolate current region", "Region Review"),
    ]:
        add(aid, label, cat, "region-review" if aid.startswith("region_") else "application")
    return specs


def migrate_shortcuts(stored: object, registry: Mapping[str, CommandSpec]) -> dict[str, str]:
    out = {aid: spec.default for aid, spec in registry.items()}
    if isinstance(stored, Mapping):
        for aid, key in stored.items():
            if aid in out:
                out[str(aid)] = str(key or "")
        # A newly introduced recommendation must yield to an existing user
        # assignment instead of silently creating an ambiguous QAction pair.
        if "toggle_segmentations" not in stored:
            used = {str(key or "").strip().lower() for aid, key in stored.items()
                    if aid != "toggle_segmentations"}
            if out.get("toggle_segmentations", "").lower() in used:
                out["toggle_segmentations"] = ""
    return out


def shortcut_conflicts(assignments: Mapping[str, str], registry: Mapping[str, CommandSpec]) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}
    for aid, key in assignments.items():
        norm = str(key or "").strip()
        if not norm or aid not in registry:
            continue
        seen.setdefault(norm.lower(), []).append(aid)
    return {key: aids for key, aids in seen.items() if len(aids) > 1}
