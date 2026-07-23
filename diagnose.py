"""Print ONLY geometry + intensity metadata for a scan.

This never prints pixel data, patient name, ID, or dates — just array shape,
spacing, and intensity statistics. It's meant to explain *why* a scan renders
wrong (e.g. as a line), safely, without sharing any patient image.

Usage:
    python diagnose.py <scan-file-or-DICOM-folder>
"""
from __future__ import annotations

import os
import sys

import numpy as np


def probe_raw(path: str):
    info = []
    low = path.lower()
    if low.endswith((".nii", ".nii.gz")):
        try:
            import nibabel as nib
            img = nib.load(path)
            info.append(f"NIfTI raw shape: {img.shape}")
            info.append(f"NIfTI zooms: {tuple(round(float(z), 4) for z in img.header.get_zooms()[:3])}")
            try:
                info.append(f"NIfTI orientation codes: {''.join(nib.aff2axcodes(img.affine))}")
            except Exception:
                pass
        except Exception as e:
            info.append(f"NIfTI raw probe failed: {e}")
    else:
        try:
            import pydicom
            if os.path.isdir(path):
                n = withpix = 0
                example = frames = None
                for root, _dirs, names in os.walk(path):
                    for nm in names:
                        n += 1
                        try:
                            ds = pydicom.dcmread(os.path.join(root, nm), force=True,
                                                 stop_before_pixels=True)
                            if "PixelData" in ds:
                                withpix += 1
                            if example is None and hasattr(ds, "Rows"):
                                example = (int(ds.Rows), int(ds.Columns))
                            nf = getattr(ds, "NumberOfFrames", None)
                            if nf:
                                frames = int(nf)
                        except Exception:
                            pass
                info.append(f"DICOM folder: {n} files, {withpix} with pixel data")
                if example:
                    info.append(f"DICOM per-slice Rows x Cols: {example[0]} x {example[1]}")
                if frames:
                    info.append(f"DICOM NumberOfFrames on a file: {frames}")
            else:
                ds = pydicom.dcmread(path, force=True, stop_before_pixels=True)
                info.append(f"DICOM single file; Rows x Cols: "
                            f"{getattr(ds, 'Rows', '?')} x {getattr(ds, 'Columns', '?')}")
                nf = getattr(ds, "NumberOfFrames", None)
                if nf:
                    info.append(f"DICOM NumberOfFrames: {int(nf)} (multi-frame single file)")
        except Exception as e:
            info.append(f"DICOM raw probe failed: {e}")
    return info


def main():
    if len(sys.argv) < 2:
        print("Usage: python diagnose.py <scan-file-or-DICOM-folder>")
        return
    path = sys.argv[1].strip().strip('"')
    print("=" * 62)
    print("PKD QC scan diagnostic  (metadata only — no image data shown)")
    print("=" * 62)
    print("Path:", path)
    print("Exists:", os.path.exists(path), "| Is folder:", os.path.isdir(path))
    print("-" * 62)
    print("Low-level probe:")
    for line in probe_raw(path):
        print("   ", line)
    print("-" * 62)
    print("As the app loads it:")
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from pkdqc.core.io import load_image
        from pkdqc.core.planes import PLANES, ORDER
        vol = load_image(path)
        d = vol.data
        print(f"    loaded shape (axis0,axis1,axis2): {d.shape}")
        print(f"    dtype: {d.dtype}")
        print(f"    spacing (mm): {tuple(round(float(s), 4) for s in vol.spacing)}")
        finite = d[np.isfinite(d)]
        if finite.size:
            print(f"    intensity min / max: {float(finite.min()):.1f} / {float(finite.max()):.1f}")
            print(f"    intensity 2 / 50 / 98 pct: "
                  f"{np.percentile(finite, 2):.1f} / {np.percentile(finite, 50):.1f} / "
                  f"{np.percentile(finite, 98):.1f}")
        print(f"    default window: {tuple(round(float(x), 1) for x in vol.default_window)}")
        print("    MPR pane slice shapes (V x H) at center:")
        cur = [s // 2 for s in d.shape]
        for name in ORDER:
            sh = PLANES[name].slice2d(d, cur).shape
            flag = "   <-- DEGENERATE (would render as a line!)" if min(sh) < 2 else ""
            print(f"       {name:9s}: {sh[0]} x {sh[1]}{flag}")
        print("\n    => If all three pane shapes are 2D and non-degenerate, the data is")
        print("       fine and any 'line' is a display bug — tell me and I'll dig in.")
    except Exception as e:
        print("    LOAD FAILED:", repr(e))
        print("    => The load itself failed; the low-level probe above shows why.")
    print("=" * 62)
    print("Copy everything above and send it back. It has no pixel data and no")
    print("patient name / ID / date — only array geometry and intensity numbers.")
    print("=" * 62)


if __name__ == "__main__":
    main()
