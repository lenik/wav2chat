# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: single-file wav2chat executable."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
INCLUDE_GUI = os.environ.get("PACKAGER_GUI", "1") != "0"

hiddenimports: list[str] = [
    "wav2chat",
    "wav2chat.cli",
    "wav2chat.gui",
    "wav2chat.gui.widgets",
    "wav2chat.funasr_backend",
    "wav2chat.jieba_cache",
    "jieba",
    "torch",
    "torchaudio",
]
hiddenimports += collect_submodules("wav2chat")

datas: list[tuple[str, str]] = []
binaries: list[tuple[str, str]] = []

for package in ("funasr", "modelscope", "torchaudio", "jieba"):
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
        datas += pkg_datas
        binaries += pkg_binaries
        hiddenimports += pkg_hidden
    except Exception:
        pass

try:
    datas += collect_data_files("jieba")
except Exception:
    pass

if INCLUDE_GUI:
    hiddenimports += ["wx", "wx.adv", "wx.html", "wx.lib", "gi", "gi.repository.GLib"]
    try:
        wx_datas, wx_binaries, wx_hidden = collect_all("wx")
        datas += wx_datas
        binaries += wx_binaries
        hiddenimports += wx_hidden
    except Exception:
        pass

excludes = [
    "tkinter",
    "matplotlib",
    "notebook",
    "IPython",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
]

if not INCLUDE_GUI:
    excludes.append("wx")

a = Analysis(
    [str(ROOT / "packager" / "_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="wav2chat",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
