# -*- mode: python ; coding: utf-8 -*-
"""One-folder build spec for creating an Inno Setup installer."""
from pathlib import Path

project_root = Path(SPECPATH)

# ── data files ──────────────────────────────────────────────
datas = []
assets_dir = project_root / "assets"
styles_file = project_root / "ui" / "styles.qss"
icon_file = project_root / "assets" / "icons" / "app.ico"

if assets_dir.exists():
    datas.append((str(assets_dir), "assets"))
if styles_file.exists():
    datas.append((str(styles_file), "ui"))
# NOTE: config.json is NOT shipped — the app creates defaults on first run.

# ── binaries (ffmpeg) ──────────────────────────────────────
extra_binaries = []
try:
    import imageio_ffmpeg

    _ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    extra_binaries.append((_ffmpeg, "imageio_ffmpeg/binaries"))
except Exception:
    pass

# ── analysis ────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=extra_binaries,
    datas=datas,
    hiddenimports=[
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
    [],
    exclude_binaries=True,
    name="SuperCapture",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_file) if icon_file.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SuperCapture",
)
