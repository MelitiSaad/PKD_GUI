"""Instantiate the app headless, load synthetic data, exercise tools, render PNGs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6 import QtCore

from pkdqc.app import build_application
from pkdqc.ui.main_window import MainWindow
from pkdqc.core.volume import ImageVolume
from pkdqc.core.segmentation import Segmentation
from pkdqc.core.labels import LabelTable


def synth(shape=(256, 256, 40), spacing=(1.367, 1.367, 3.0)):
    R, C, S = shape
    rng = np.random.default_rng(3)
    img = rng.normal(30, 6, shape).astype(np.float32)
    yy, xx = np.mgrid[0:R, 0:C]
    # abdomen ellipse
    body = (((xx - C / 2) / (C * 0.42)) ** 2 + ((yy - R / 2) / (R * 0.34)) ** 2) < 1
    seg = np.zeros(shape, dtype=np.uint16)
    for z in range(S):
        img[:, :, z][body] += 45
    # two kidney blobs, present on central slices
    def kidney(cx, cy, z, lid, sign):
        prof = 1 - abs(z - S / 2) / (S * 0.5)
        if prof <= 0:
            return
        rad_x = 20 * prof
        rad_y = 30 * prof
        ell = (((xx - cx) / rad_x) ** 2 + ((yy - cy) / rad_y) ** 2) < 1
        # bean shape: carve a notch
        notch = (((xx - (cx + sign * 10)) / (rad_x * 0.7)) ** 2 + ((yy - cy) / (rad_y * 0.8)) ** 2) < 1
        blob = ell & ~notch
        img[:, :, z][blob] += 70
        seg[:, :, z][blob] = lid

    for z in range(6, S - 6):
        kidney(C / 2 - 55, R / 2, z, 1, +1)
        kidney(C / 2 + 55, R / 2, z, 2, -1)
    img = np.clip(img, 0, 255)
    vol = ImageVolume(img, spacing, np.diag([spacing[0], spacing[1], spacing[2], 1.0]))
    segmentation = Segmentation(seg, LabelTable.from_ids([0, 1, 2], {1: "Left kidney", 2: "Right kidney"}))
    return vol, segmentation


def main():
    app = build_application([])
    win = MainWindow(enable_3d=False)
    win.resize(1360, 880)
    vol, seg = synth()
    win._set_case(vol, seg, seg_path=None)
    win.controller.set_tool("brush")
    win.controller.set_brush_radius(7)
    win.ortho.set_axial_slice(20)
    seg.active_id = 1

    from pkdqc.core.planes import PLANES, AXIAL, CORONAL, SAGITTAL
    ax_plane = PLANES[AXIAL]

    # --- integration: brush stroke on the AXIAL pane through the real paint path ---
    before = int((seg.data == 1).sum())
    ctrl = win.controller
    ctrl.plane_paint_start(ax_plane, 150, 118)
    for v, h in [(150, 124), (150, 130), (150, 136)]:
        ctrl.plane_paint_move(ax_plane, v, h)
    ctrl.plane_paint_end()
    after = int((seg.data == 1).sum())
    assert after > before, "brush stroke did not add voxels"
    assert win.history.can_undo, "history has no undo after stroke"
    win.history.undo(); assert int((seg.data == 1).sum()) == before, "undo failed"
    win.history.redo(); assert int((seg.data == 1).sum()) == after, "redo failed"
    print("integration OK: axial stroke add/undo/redo through GUI path")

    # --- integration: a cross-plane stroke on the SAGITTAL pane ---
    sag = PLANES[SAGITTAL]
    b2 = int((seg.data == 1).sum())
    ctrl.plane_paint_start(sag, 20, 40)
    ctrl.plane_paint_move(sag, 24, 44)
    ctrl.plane_paint_end()
    assert int((seg.data == 1).sum()) > b2, "sagittal stroke added nothing"
    win.history.undo()
    print("integration OK: sagittal (cross-plane) stroke edits volume")

    # --- integration: fill on the axial pane ---
    ctrl.set_tool("fill")
    ctrl.plane_paint_click(ax_plane, 0, 0)
    print("integration OK: fill click ran, undo depth =", len(win.history._undo))
    win.history.undo()   # revert demo background fill for a clean shot

    ctrl.set_tool("brush")
    win.panel.opacity.setValue(55)
    win.panel.recompute()
    # show a brush ring on the axial pane for the screenshot
    axw = win.ortho.planes[AXIAL]
    axw.set_brush_visible(True)
    axw.brush.setRect(118 - 7, 150 - 7, 15, 15)

    for _ in range(10):
        app.processEvents()
    QtCore.QThread.msleep(150)
    for _ in range(10):
        app.processEvents()

    out = "/tmp/preview_main.png"
    win.grab().save(out)
    print("saved", out, os.path.getsize(out), "bytes; saved-pill:", win.lbl_saved.text().strip())
    win.ortho.grab().save("/tmp/preview_viewer.png")
    print("saved preview_viewer.png")

    from pkdqc.core.volumetry import compute_volumes, total_volume
    vols = compute_volumes(seg, vol)
    for v in vols:
        print(f"  {v.name}: {v.voxels} vox, {v.mm3:.0f} mm3, {v.ml:.2f} mL")
    print("  total:", f"{total_volume(vols).ml:.2f} mL")


if __name__ == "__main__":
    main()
