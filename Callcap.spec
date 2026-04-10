# -*- mode: python ; coding: utf-8 -*-
"""Callcap single-dir build spec for PyInstaller."""
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

project_root = Path(SPECPATH)

# Collect numpy completely to avoid C-extension import errors
np_datas, np_binaries, np_hiddenimports = collect_all("numpy")

datas = list(np_datas)
assets_dir = project_root / "assets"
styles_file = project_root / "ui" / "styles.qss"
config_file = project_root / "config.json"
icon_file = project_root / "assets" / "icons" / "app.ico"

if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))
if styles_file.exists():
    datas.append((str(styles_file), "ui"))
if config_file.exists():
    datas.append((str(config_file), "."))

extra_binaries = []
try:
    import imageio_ffmpeg

    _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    extra_binaries.append((_ffmpeg, "imageio_ffmpeg/binaries"))
except Exception:
    pass

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=extra_binaries + np_binaries,
    datas=datas,
    hiddenimports=[
        "PyQt6",
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
        "PyQt6.sip",
        "imageio",
        "imageio.plugins",
        "imageio.core",
        "imageio_ffmpeg",
        "imageio_ffmpeg.binaries",
        "pyaudiowpatch",
        "requests",
        "numpy",
        "numpy.core",
        "numpy.core._methods",
        "numpy.lib",
        "numpy.lib.format",
    ] + np_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "PyQt5", "PySide2", "PySide6"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Callcap",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Callcap",
)
