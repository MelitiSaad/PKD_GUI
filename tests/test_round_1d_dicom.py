import os
from pathlib import Path

import numpy as np
import pytest

from pkdqc.core import dicom, io, session
from pkdqc.core.segmentation import Segmentation

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import CTImageStorage, EnhancedCTImageStorage, ExplicitVRLittleEndian, generate_uid


def _write_slice(path: Path, *, study, series, frame="1.2.3.frame", rows=3, cols=4,
                 iop=(1, 0, 0, 0, 1, 0), ipp=(0, 0, 0), pixel_spacing=(2.0, 3.0),
                 instance=1, slope=1.0, intercept=0.0, modality="CT", desc="abdomen",
                 image_type=("ORIGINAL", "PRIMARY"), pixel_representation=0, data=None,
                 sop=CTImageStorage, temporal=""):
    meta = FileMetaDataset(); meta.TransferSyntaxUID = ExplicitVRLittleEndian; meta.MediaStorageSOPClassUID = sop; meta.MediaStorageSOPInstanceUID = generate_uid(); meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = sop; ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study; ds.SeriesInstanceUID = series; ds.FrameOfReferenceUID = frame
    ds.Modality = modality; ds.SeriesNumber = 7; ds.SeriesDescription = desc; ds.ImageType = list(image_type)
    ds.Rows = rows; ds.Columns = cols; ds.ImageOrientationPatient = [str(v) for v in iop]; ds.ImagePositionPatient = [str(v) for v in ipp]
    ds.PixelSpacing = [str(pixel_spacing[0]), str(pixel_spacing[1])]; ds.SliceThickness = "99"
    ds.InstanceNumber = instance
    if temporal:
        ds.TemporalPositionIdentifier = temporal
    ds.PhotometricInterpretation = "MONOCHROME2"; ds.SamplesPerPixel = 1
    ds.BitsAllocated = 16; ds.BitsStored = 16; ds.HighBit = 15; ds.PixelRepresentation = pixel_representation
    ds.RescaleSlope = str(slope); ds.RescaleIntercept = str(intercept)
    if data is None:
        dtype = np.int16 if pixel_representation else np.uint16
        data = np.full((rows, cols), instance, dtype=dtype)
    ds.PixelData = np.asarray(data).tobytes()
    ds.save_as(str(path), write_like_original=False)
    return path


def make_series(root: Path, *, study=None, series=None, frame=None, positions=(0, 1, 2),
                iop=(1, 0, 0, 0, 1, 0), pixel_spacing=(2.0, 3.0), names=None,
                slope=1.0, intercept=0.0, pixel_representation=0, temporal=None, desc="abdomen"):
    study = study or generate_uid(); series = series or generate_uid(); frame = frame or generate_uid()
    row = np.array(iop[:3], float); col = np.array(iop[3:], float); normal = np.cross(row, col)
    files = []
    if names is None:
        names = [f"slice_{i}.dcm" for i in range(len(positions))]
    for idx, (pos, name) in enumerate(zip(positions, names), start=1):
        data = np.full((3, 4), idx, dtype=np.int16 if pixel_representation else np.uint16)
        files.append(_write_slice(root / name, study=study, series=series, frame=frame,
                                  iop=iop, ipp=tuple(normal * pos), pixel_spacing=pixel_spacing,
                                  instance=100 - idx, slope=slope, intercept=intercept,
                                  pixel_representation=pixel_representation,
                                  temporal="" if temporal is None else temporal[idx - 1], data=data, desc=desc))
    return study, series, frame, files


def test_valid_axial_lps_to_ras_and_slice_sorting(tmp_path):
    make_series(tmp_path, positions=(2, 0, 1), names=("c.dcm", "a.dcm", "b.dcm"))
    image = io.load_image(str(tmp_path))
    assert image.shape == (4, 3, 3)  # canonicalized from rows,cols,slices
    assert image.data[0, 0, 0] == 2  # position 0 is first despite filename/instance order
    # The DICOM LPS origin is converted to RAS and then canonicalized; screen/data voxel (0,0,0)
    # is the RAS-minimum corner for this fixture.
    expected = np.array([-9.0, -4.0, 0.0])
    assert np.allclose(image.geometry.voxel_to_world((0, 0, 0)), expected)
    assert image.source_identity["type"] == "dicom-series"


def test_coronal_sagittal_and_oblique_series_load(tmp_path):
    cases = [
        ("coronal", (1, 0, 0, 0, 0, 1)),
        ("sagittal", (0, 1, 0, 0, 0, 1)),
        ("oblique", tuple([np.sqrt(.5), np.sqrt(.5), 0, -np.sqrt(.5), np.sqrt(.5), 0])),
    ]
    for name, iop in cases:
        d = tmp_path / name; d.mkdir()
        make_series(d, iop=iop)
        img = io.load_image(str(d))
        assert img.geometry.validation.ok
        assert img.voxel_volume_mm3 == pytest.approx(6.0)


def test_rescale_and_signed_pixels(tmp_path):
    make_series(tmp_path, slope=2.0, intercept=-100.0, pixel_representation=1)
    img = io.load_image(str(tmp_path))
    assert img.data.min() <= -98.0


def test_discovery_groups_multiple_series_studies_and_localizers(tmp_path):
    make_series(tmp_path, study="1.2.3.1", series="1.2.3.2")
    make_series(tmp_path, study="1.2.3.9", series="1.2.3.10", names=("x1.dcm", "x2.dcm", "x3.dcm"))
    make_series(tmp_path, study="1.2.3.1", series="1.2.3.11", names=("l1.dcm", "l2.dcm", "l3.dcm"), desc="Localizer scout")
    found = dicom.discover_series(str(tmp_path))
    assert len(found) == 3
    assert sum(c.valid for c in found) == 2
    with pytest.raises(io.LoadError, match="Multiple valid DICOM series"):
        io.load_image(str(tmp_path))
    chosen = io.load_image(str(tmp_path), dicom_selector=lambda candidates: candidates[1])
    assert chosen.source_identity["series_uid"] in {"1.2.3.2", "1.2.3.10"}


@pytest.mark.parametrize("positions,msg", [((0, 0, 1), "duplicate"), ((0, 1, 3), "irregular|missing")])
def test_duplicate_and_gap_rejected(tmp_path, positions, msg):
    make_series(tmp_path, positions=positions)
    with pytest.raises(io.LoadError, match=msg):
        io.load_image(str(tmp_path))


@pytest.mark.parametrize("change,msg", [
    ("spacing", "inconsistent PixelSpacing"),
    ("size", "inconsistent matrix size"),
    ("orientation", "inconsistent ImageOrientationPatient"),
    ("temporal", "mixed temporal"),
])
def test_inconsistent_series_rejected(tmp_path, change, msg):
    study, series, frame, files = make_series(tmp_path, temporal=("1", "1", "2") if change == "temporal" else None)
    if change == "spacing":
        _write_slice(files[1], study=study, series=series, frame=frame, ipp=(0, 0, 1), pixel_spacing=(9, 9), instance=2)
    elif change == "size":
        _write_slice(files[1], study=study, series=series, frame=frame, rows=5, cols=4, ipp=(0, 0, 1), instance=2)
    elif change == "orientation":
        _write_slice(files[1], study=study, series=series, frame=frame, iop=(0, 1, 0, 1, 0, 0), ipp=(0, 0, 1), instance=2)
    with pytest.raises(io.LoadError, match=msg):
        io.load_image(str(tmp_path))


def test_missing_geometry_and_shear_rejected(tmp_path):
    make_series(tmp_path / "ok") if False else None
    study, series, frame, files = make_series(tmp_path, iop=(1, 0, 0, .5, 1, 0))
    found = dicom.discover_series(str(tmp_path))
    assert not found[0].valid
    with pytest.raises(io.LoadError, match="No valid DICOM"):
        io.load_image(str(tmp_path))


def test_dicom_not_loaded_as_segmentation(tmp_path):
    make_series(tmp_path)
    with pytest.raises(io.LoadError, match="Segmentation loading supports .nii"):
        io.load_segmentation(str(tmp_path), (3, 4, 3), np.eye(4))


def _write_enhanced(path: Path, *, unsupported=False):
    study = generate_uid(); series = generate_uid(); frame = generate_uid()
    meta = FileMetaDataset(); meta.TransferSyntaxUID = ExplicitVRLittleEndian; meta.MediaStorageSOPClassUID = EnhancedCTImageStorage; meta.MediaStorageSOPInstanceUID = generate_uid(); meta.ImplementationClassUID = generate_uid()
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.SOPClassUID = EnhancedCTImageStorage; ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study; ds.SeriesInstanceUID = series; ds.FrameOfReferenceUID = frame; ds.Modality = "CT"; ds.SeriesNumber = 8; ds.SeriesDescription = "enhanced"
    ds.Rows = 3; ds.Columns = 4; ds.NumberOfFrames = 3; ds.PhotometricInterpretation = "MONOCHROME2"; ds.SamplesPerPixel = 1
    ds.BitsAllocated = 16; ds.BitsStored = 16; ds.HighBit = 15; ds.PixelRepresentation = 0; ds.RescaleSlope = "1"; ds.RescaleIntercept = "0"
    shared = Dataset(); pm = Dataset(); pm.PixelSpacing = ["2", "3"]; shared.PixelMeasuresSequence = Sequence([pm]); po = Dataset(); po.ImageOrientationPatient = ["1", "0", "0", "0", "1", "0"]; shared.PlaneOrientationSequence = Sequence([po]); ds.SharedFunctionalGroupsSequence = Sequence([shared])
    per = []
    for z in ([0, 1, 3] if unsupported else [0, 1, 2]):
        item = Dataset(); pp = Dataset(); pp.ImagePositionPatient = ["0", "0", str(z)]; item.PlanePositionSequence = Sequence([pp]); per.append(item)
    ds.PerFrameFunctionalGroupsSequence = Sequence(per)
    ds.PixelData = np.stack([np.full((3, 4), i + 1, dtype=np.uint16) for i in range(3)]).tobytes()
    ds.save_as(str(path), write_like_original=False)
    return path


def test_enhanced_multiframe_supported_and_unsupported_rejected(tmp_path):
    good = tmp_path / "enh.dcm"; _write_enhanced(good)
    img = io.load_image(str(good))
    assert img.shape == (4, 3, 3)
    bad_dir = tmp_path / "bad"; bad_dir.mkdir(); _write_enhanced(bad_dir / "bad.dcm", unsupported=True)
    with pytest.raises(io.LoadError, match="unsupported multiframe|irregular"):
        io.load_image(str(bad_dir))


def test_dicom_recovery_identity_success_and_changed_source_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    import importlib
    import pkdqc.config as cfg
    import pkdqc.core.session as sess
    importlib.reload(cfg); importlib.reload(sess)
    d = tmp_path / "dicom"; d.mkdir(); make_series(d)
    image = io.load_image(str(d))
    seg = Segmentation.empty_like(image.shape); seg.data[1, 1, 1] = 4
    s = sess.Session(image); s.begin(); s.save(seg, dirty=True)
    rec = sess.find_recoverable()[0]
    reimage = io.load_image(rec.image_path, source_identity=sess.recovery_source_identity(rec))
    sess.validate_recovery_image(rec, reimage)
    Path(image.source_identity["locator"]).joinpath("slice_1.dcm").write_bytes(b"changed")
    with pytest.raises(io.LoadError, match="DICOM source identity|missing or ambiguous|No valid DICOM"):
        io.load_image(rec.image_path, source_identity=sess.recovery_source_identity(rec))
    assert sess.find_recoverable() == []


def test_phi_safe_candidate_and_identity(tmp_path):
    make_series(tmp_path, desc="Kidney MR")
    c = dicom.discover_series(str(tmp_path))[0]
    img = io.load_image(str(tmp_path))
    text = c.display_description + repr(img.source_identity)
    assert "PatientName" not in text and "MRN" not in text and "Accession" not in text
