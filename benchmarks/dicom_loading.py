from __future__ import annotations

import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import CTImageStorage, ExplicitVRLittleEndian, generate_uid

from pkdqc.core import dicom, io


def write_slice(path, study, series, z, value):
    meta = FileMetaDataset(); meta.TransferSyntaxUID = ExplicitVRLittleEndian; meta.MediaStorageSOPClassUID = CTImageStorage; meta.MediaStorageSOPInstanceUID = generate_uid(); meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = CTImageStorage; ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study; ds.SeriesInstanceUID = series; ds.FrameOfReferenceUID = "1.2.826.0.1.3680043.8.498.1"
    ds.Modality = "CT"; ds.SeriesNumber = 1; ds.SeriesDescription = "synthetic"
    ds.Rows = 64; ds.Columns = 64; ds.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]
    ds.ImagePositionPatient = ["0", "0", str(z)]; ds.PixelSpacing = ["0.8", "0.8"]; ds.SliceThickness = "2"
    ds.InstanceNumber = value; ds.PhotometricInterpretation = "MONOCHROME2"; ds.SamplesPerPixel = 1
    ds.BitsAllocated = 16; ds.BitsStored = 16; ds.HighBit = 15; ds.PixelRepresentation = 0; ds.RescaleSlope = "1"; ds.RescaleIntercept = "-1024"
    ds.PixelData = np.full((64, 64), value, dtype=np.uint16).tobytes()
    ds.save_as(str(path), write_like_original=False)


def main():
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d); study = generate_uid(); series = generate_uid(); other = generate_uid()
        for z in range(32):
            write_slice(root / f"b_{31-z:03d}.dcm", study, series, z * 2, z)
        for z in range(4):
            write_slice(root / f"other_{z:03d}.dcm", study, other, z * 5, z)
        t0 = time.perf_counter(); candidates = dicom.discover_series(str(root)); t1 = time.perf_counter()
        image = io.load_image(str(root), dicom_selector=lambda cs: next(c for c in cs if c.series_uid == series)); t2 = time.perf_counter()
        print({
            "candidates": len(candidates),
            "valid_candidates": sum(c.valid for c in candidates),
            "shape": image.shape,
            "spacing": image.spacing,
            "voxel_volume_mm3": image.voxel_volume_mm3,
            "discover_ms": (t1 - t0) * 1000,
            "load_ms": (t2 - t1) * 1000,
        })


if __name__ == "__main__":
    main()
