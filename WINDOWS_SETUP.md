# Windows setup — the easy way

You do **not** need to type anything in a terminal. Two double-click scripts:

| I want to… | Double-click | Result |
|---|---|---|
| Just run it now (while we test) | **`run.bat`** | Sets everything up and opens the app |
| Make a standalone `.exe` | **`build_exe.bat`** | Produces `dist\PKD_QC\PKD_QC.exe` |

---

## Run it now (`run.bat`)

Double-click **`run.bat`**. The first time, it builds a small private
environment and downloads the libraries (a few minutes, needs internet). Every
run after that is instant. When it says "Launching," the app window opens; you
can close the black window.

## Make an `.exe` (`build_exe.bat`)

Double-click **`build_exe.bat`**. After a few minutes you get:

```
dist\PKD_QC\PKD_QC.exe
```

That folder is self-contained — **Python is not required to run it.** Copy the
whole `dist\PKD_QC` folder to another Windows PC (or zip it) and run
`PKD_QC.exe`. (It's one .exe plus support files in the same folder; keep them
together.)

---

## Why did `python -m pkdqc` fail earlier?

Windows ships a fake `python` command that opens the Microsoft Store instead of
running Python — that's the "Python was not found…" message you saw. The real
launcher is **`py`** (which is why `py` worked for you). The scripts above use
`py` for you, so you don't have to think about it.

## Python version

The scientific + Qt libraries are safest on **Python 3.12**. You currently have
3.14, which is so new that some libraries don't publish installers for it yet.
If a script reports an install failure, install Python 3.12 from
<https://www.python.org/downloads/> (tick **"Add python.exe to PATH"** during
setup) and re-run the script — it will prefer 3.12 automatically.

## Troubleshooting

* **"Windows protected your PC" (blue SmartScreen box)** when running the .exe —
  this happens for any app that isn't code-signed. Click **More info → Run
  anyway**. (Proper code signing removes this; see the note about hospitals.)
* **Antivirus flags the .exe** — common for freshly built PyInstaller apps
  (false positive). You may need to allow it, or have IT allowlist it.
* **Install fails on Python 3.14** — install Python 3.12 (above).
* **App opens then closes / errors** — a log is written to
  `%LOCALAPPDATA%\pkdqc\logs\pkdqc.log`. Send me that file.
* **Autosaves / recovery files** live in `%LOCALAPPDATA%\pkdqc\sessions`.

---


---

## What you'll see

A **menu bar** (File / Edit / Segmentation / Tools / View / Help) and two
toolbars with **text on every button**, so nothing needs a hover to identify.

The **left rail holds only the four tools** — what your mouse does:

* **Crosshair** — drag to move the crosshair through the volume (all panes
  follow); a click also selects the object under it.
* **Pan** — drag to move the image.
* **Brush** — left paints, **right erases** (no separate eraser tool).
* **Fill** — left fills a region, right clears it.

Right-drag zooms and middle-drag pans no matter which tool is active, and the
zoom stays anchored to the spot you grabbed. Grow / shrink / remove islands /
fill holes / interpolate are under **Clean up** in the toolbar (and the
Segmentation menu), because they are one-shot actions, not modes.

Four panes: **axial**, **coronal**, **sagittal**, **3D**. Double-click a pane to
maximise it, or use the **View** row (keys `1`–`5`) to show one orientation
alone. Contrast is under **Tools → Contrast** (a histogram you can drag).
The **3D rebuilds only when you press Update 3D** (`F5`); turn on **Continuous
3D update** if you want it live, and **Show 3D axes** for an XYZ reference.

Drag a file onto the window and it asks **image** or **segmentation**.
`Ctrl+0` re-fits the views. The app runs **without a terminal window**.

### A note on thick-slice scans

If a scan was acquired in one plane with few, thick slices (e.g. a coronal MRI
with 24 slices at 12 mm), the acquired plane will look sharp and the other two
will look blocky. That is inherent — there simply are only 24 samples across
that direction — and ITK-SNAP shows the same thing. What the viewer *does*
guarantee is that all three panes are drawn at correct physical proportions
(square millimetres), not squashed.

---

## If a scan still won't display right

Run the diagnostic — it prints only the scan's shape, spacing, and intensity
numbers (no image, no patient name/ID/date), so it's safe to share:

1. Drag your scan file (or the DICOM **folder**) onto **`diagnose.bat`**, or run
   `diagnose.bat "C:\path\to\scan"`.
2. Copy the printed block and send it back.

That tells me exactly why it's misbehaving instead of guessing.

## About running on hospital computers

Short version: **the .exe removes the Python requirement and will run on a
normal Windows PC, but hospital machines are usually locked down and will likely
need your IT team's help.** Specifically:

* It runs on **Windows (64-bit)** — Windows 10/11. It will **not** run on Mac or
  Linux, and this test build is not signed.
* Hospital IT commonly uses **application allowlisting** (only approved software
  runs) and security scanning. An unsigned app from an unknown publisher is often
  blocked by policy — not because anything's wrong with it, but because that's how
  managed clinical environments work.
* The clean path for real deployment is: build the `.exe` → wrap it in an
  **installer** → **code-sign** it (your institution issues the certificate) →
  hand it to IT for managed rollout. I can generate the installer script when
  you're ready for that step.
* The 3D view needs a real graphics card. This build leaves 3D out on purpose, so
  it stays lightweight and works even on basic/remote workstations (you'll see a
  "3D unavailable" panel; QC and volumes work fully).

## Round 1G manual QA checklist
On Windows, verify Open image, Load segmentation, Save, Save As, New segmentation, Undo, Redo, and Quit shortcuts; confirm specialized commands are unassigned until configured; confirm Keyboard Shortcuts can assign, clear, reject duplicates, persist, and reset. Verify Region Review enters only when requested, grouping changes navigation, isolation only changes overlay visibility, and Save/Discard/case replacement/clean close do not leave retired recovery sessions.

## Round 1H Windows manual QA
Open one image; add organ and cyst segmentations as separate layers; verify both may contain label 1, switch the active editing target, edit/undo/redo each independently, and vary visibility, order, and opacity. Press `S` with the viewer focused and confirm all overlays hide and the exact per-layer visibility returns; verify typing `S` in an editor does not toggle them. Save each layer, exercise Save All including a pathless layer, and test Save/Discard/Cancel while removing/replacing a dirty layer and Save All/Discard All/Cancel on close. Force-close with two dirty layers and verify each recovery generation is offered independently on restart.
