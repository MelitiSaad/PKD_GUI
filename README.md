# PKD Segmentation QC

A general-purpose desktop medical-image segmentation editor with streamlined **AI quality-control and volumetry workflows**.
A separate AI produces the segmentation; this app is where you overlay that label
volume on the image, correct it slice by slice, and read off the corrected volume
in mm³ and mL. Users can edit an existing/AI segmentation or create a blank segmentation manually. There is no AI inside this app.

This is a ground-up rewrite of the original PyQt5 + matplotlib tool, rebuilt around
a fast viewer, a real data model, and always-on crash safety.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Python 3.10+ recommended.

The 3D view **updates on demand** (Update 3D / `F5`), not on every edit, so brush
strokes stay fast; enable **View → Continuous 3D update** if you want it live.
A toggleable XYZ **axes reference** (View → Show 3D axes) shows orientation.
The 3D view needs a working OpenGL stack (a normal desktop GPU is fine). If VTK
can't start, the app runs normally and the 3D pane shows a placeholder — nothing
else is affected.

## Run

```bash
python -m pkdqc
```

## Workflow

1. **Open image** (`Ctrl+O`) — NIfTI (`.nii`/`.nii.gz`) or a DICOM series.
2. **Load segmentation** (`Ctrl+L`) — the AI's label volume, in the same voxel grid.
   You can also **drag a file onto the window**; it asks whether to load it as the
   image or the segmentation.
   You can also drag a file onto the window.
3. **Review and correct** slice by slice with the tools below. Scroll the mouse
   wheel to move through slices; right-drag to window/level.
4. **Compute volumes** — per-object and total, in voxels, mm³, and mL. **Copy mL**
   puts a tab-separated block on the clipboard for your spreadsheet.
5. **Save** (`Ctrl+S`) — writes the corrected label volume as NIfTI using the
   image's affine.

## Views

The window is a 2×2 orthogonal layout, like ITK-SNAP: **axial**, **coronal**,
and **sagittal** panes reconstructed from the one loaded volume, plus a **3D**
pane. All three slice panes share a crosshair cursor — click or scroll in any
pane and the others follow. Scroll changes that pane's slice; Ctrl+wheel zooms.
You can paint in any of the three planes.

**Single-pane mode:** double-click any pane to maximise it (double-click again to
return to 2×2), or use the Layout buttons / keys `1`–`5` (2×2, Axial, Coronal, Sagittal, 3D).

## Tools & shortcuts

| Tool / action | Key | Notes |
|---|---|---|
| Threshold paint | `T` | Brush that only paints within an intensity band |
| Grow / Shrink | `G` / `Shift+G` | Dilate / erode the active object (3D) |
| Remove islands | `K` | Drops disconnected specks of the active object |
| Fill holes | `J` | Fills enclosed gaps in the active object |
| Interpolate slices | `I` | Fills gaps **between** slices you've drawn on |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Y` | Unlimited within memory budget |
| Prev / next edited slice | `,` / `.` | Jump between axial slices you changed |
| Smaller / larger brush | `[` / `]` | Also Alt+wheel in any pane |
| Reset zoom | `Ctrl+0` | Re-fit all panes to the image |
| Contrast editor | `C` | Histogram + draggable window/level |
| Layout 2×2 / single | `1`–`5` | 2×2, Axial, Coronal, Sagittal, 3D |
| Update 3D | `F5` | Rebuild the 3D surface on demand |
| Remove unused objects | `Ctrl+Shift+R` | Drop labels not present in the volume |

**Tools** (left rail) are the four things the mouse can do:

| Tool | Key | Left button | Right button |
|---|---|---|---|
| Crosshair | `V` | Drag moves the crosshair; click selects the object under it | Zoom |
| Pan | `H` | Drag moves the image | Zoom |
| Brush | `B` | Paint the active object | **Erase** |
| Fill | `F` | Fill the connected region | Clear it |

There is no separate eraser tool — the right button erases while the Brush is
active. Threshold painting is a *brush mode* (Normal / Threshold in the toolbar,
or `T`), not a fifth tool.

Middle-drag always pans and right-drag always zooms, whichever tool is active.
Zoom is anchored to the point you started the drag on, so the image does not
drift while you scale it. Contrast/window-level lives in the **Contrast** editor
(Tools menu or toolbar) — a histogram with a draggable window and numeric
fields.

One-shot operations (grow, shrink, remove islands, fill holes, interpolate) are
actions rather than modes, so they live under **Clean up** in the toolbar and in
the **Segmentation** menu — not in the tool rail.

All shortcuts are editable under
**Shortcuts** (top-right).

## Data safety

* **Autosave is always on.** The label volume is checkpointed to per-user
  app-data every ~20 s, ~2.5 s after you stop editing, and every 25 edits, using
  atomic writes (temp file + rename), so a checkpoint can never be half-written.
* **Crash recovery.** If the app is killed mid-session, the next launch offers to
  recover the unsaved work. A clean exit clears the checkpoint.
* Autosave is separate from **Save** — autosave is a fast internal checkpoint;
  Save writes the NIfTI you keep.

## Stability

Every UI action runs inside an error boundary: if something fails, you get a
dialog and the app keeps running with your segmentation untouched, instead of
crashing. A global handler is the final backstop, and everything is logged to the
app-data `logs/` folder.

## What's implemented vs. limitations

Implemented and tested: NIfTI load/save, overlay with per-object colours and
opacity, all editing tools above, diff-based undo/redo, volumetry in mm³/mL,
always-on autosave + crash recovery, customizable shortcuts, optional 3D surface
view.

Honest limitations:

* **DICOM** loading is best-effort (single series, sorted by position). Complex or
  multi-series studies may need conversion to NIfTI first.
* **AVW** (the original's format) is not yet wired in — the loader is structured so
  it can be added behind the same interface.
* Orientation is canonicalised to closest-canonical (RAS+) so image and
  segmentation always overlay; the editable view is axial.
* The 3D view is a visual aid (marching-cubes surface); it downsamples very large
  volumes for responsiveness.

## Layout

```
pkdqc/
  core/        data model, I/O, commands/undo, volumetry, autosave — no Qt
  ui/          viewer, tools, panels, 3D view, main window
  theme.py     dark palette + stylesheet
  icons.py     self-contained SVG icons
tests/         core unit tests (pytest)
make_preview.py  headless integration run that renders preview PNGs
```

## Product roadmap

The source-level ITK-SNAP review and staged implementation roadmap are recorded
in [`docs/ITKSNAP_REVIEW_AND_ROADMAP.md`](docs/ITKSNAP_REVIEW_AND_ROADMAP.md).
It documents which ideas are appropriate for a general-purpose segmentation workstation with a streamlined AI-QC
workflow and which general-purpose workstation features are intentionally out of
scope.

## Tests

```bash
python -m pytest tests/            # core logic
QT_QPA_PLATFORM=offscreen python make_preview.py   # headless integration + previews
```

### Round 1G stabilization notes
PKD-QC keeps only familiar recommended shortcut defaults: Ctrl+O, Ctrl+L, Ctrl+S, Ctrl+Shift+S, Ctrl+N, Ctrl+Z, Ctrl+Y, and Ctrl+Q. Specialized commands remain available through menus, toolbars, and Region Review controls but start unassigned and can be configured in Keyboard Shortcuts. Region Review is optional and organizes existing segmentation regions; it does not detect cysts. NIfTI alone does not preserve custom label names and colours.
