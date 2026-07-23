# -*- mode: python ; coding: utf-8 -*-
#
# Build a standalone app folder:   pyinstaller --noconfirm pkdqc.spec
# Output:                          dist/PKD_QC/PKD_QC.exe
#
# Notes
# -----
# * The heavy 3D stack (VTK/PyVista) is EXCLUDED here to keep the build small and
#   reliable. The app detects its absence and shows a "3D unavailable" placeholder;
#   everything else (QC + volumes) works fully. To ship 3D, remove 'vtk',
#   'vtkmodules', 'pyvista', 'pyvistaqt' from `excludes` and rebuild (much larger).
# * console=False -> no terminal window (clean app). Flip to True temporarily
#   if you need to see startup tracebacks while debugging, then rebuild.

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = []
for _m in ("pyqtgraph", "nibabel", "pydicom"):
    hiddenimports += collect_submodules(_m)

datas = []
for _m in ("pyqtgraph", "nibabel"):
    datas += collect_data_files(_m)

excludes = [
    "vtk", "vtkmodules", "pyvista", "pyvistaqt",   # 3D — excluded for a lean build
    "matplotlib", "tkinter", "PyQt5", "PyQt6",
    "pytest", "IPython", "notebook", "pandas", "PIL",
]

a = Analysis(
    ["run_pkdqc.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PKD_QC",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # windowed app, no terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PKD_QC",
)
