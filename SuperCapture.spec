# -*- mode: python ; coding: utf-8 -*-
"""Single-file portable build spec."""
from pathlib import Path

project_root = Path(SPECPATH)

datas = []
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
    binaries=extra_binaries,
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
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SuperCapture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
)
