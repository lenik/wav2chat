# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for wav2chat.

Environment:
  PACKAGER_GUI=0|1        include wx GUI (default 1)
  PACKAGER_ONEFILE=0|1    0 = onedir (default, fast startup)
  PACKAGER_TORCH=cpu      cpu (default) | system | cuda
  PACKAGER_PROTECT=...    cython (default) | pyarmor | none
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
INCLUDE_GUI = os.environ.get("PACKAGER_GUI", "1") != "0"
ONEFILE = os.environ.get("PACKAGER_ONEFILE", "0") == "1"


def _skip_tests(name: str) -> bool:
    lowered = name.lower()
    return not any(
        part in lowered
        for part in (".tests.", ".test.", "tests.", "test.", "unittest", "pytest")
    )


def _wav2chat_dest_dir(mod_name: str, origin: Path, pkg_root: Path) -> str:
    """Map a staged file to wav2chat/ tree using its path under the package root."""
    del mod_name  # layout comes from the file path, not import name
    rel = origin.relative_to(pkg_root)
    parent = rel.parent
    if str(parent) in (".", ""):
        return "wav2chat"
    return "wav2chat/" + str(parent).replace("\\", "/")


def _collect_wav2chat_files() -> tuple[list[tuple[str, str]], list[tuple[str, str]], list[str]]:
    """Collect flat/Cython wav2chat modules (package-dir maps wav2chat -> '.')."""
    spec = importlib.util.find_spec("wav2chat")
    if spec is None or not spec.submodule_search_locations:
        print("warning: wav2chat is not importable; bundle will miss application code")
        return [], [], []

    pkg_root = Path(spec.submodule_search_locations[0]).resolve()
    binaries: list[tuple[str, str]] = []
    datas: list[tuple[str, str]] = []
    seen: set[str] = set()
    modules = collect_submodules("wav2chat", filter=_skip_tests)

    for mod_name in modules:
        mod_spec = importlib.util.find_spec(mod_name)
        if mod_spec is None or not mod_spec.origin:
            continue
        origin = Path(mod_spec.origin).resolve()
        if not origin.is_file():
            continue
        key = str(origin)
        if key in seen:
            continue
        seen.add(key)

        dest_dir = _wav2chat_dest_dir(mod_name, origin, pkg_root)
        if origin.suffix in {".so", ".pyd"}:
            binaries.append((key, dest_dir))
        elif origin.suffix == ".py":
            datas.append((key, dest_dir))

    return binaries, datas, [str(pkg_root)]


def _collect_stdlib_xml() -> list[tuple[str, str]]:
    """Bundle stdlib xml/ (avoid wx/xml.py shadowing import xml)."""
    import sys

    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    xml_root = Path(sys.base_prefix) / "lib" / f"python{ver}" / "xml"
    if not xml_root.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for path in xml_root.rglob("*"):
        if not path.is_file() or path.suffix in {".pyc", ".pyo"}:
            continue
        rel = path.relative_to(xml_root)
        dest = "xml" if len(rel.parts) == 1 else "xml/" + "/".join(rel.parts[:-1])
        out.append((str(path), dest))
    return out


def _collect_wx_package() -> tuple[list[tuple[str, str]], list[str]]:
    """Bundle the full wx tree (apt symlink on Linux; pip wheel elsewhere)."""
    try:
        import wx  # noqa: F401
    except ImportError:
        print("warning: wx is not importable; GUI bundle will be incomplete")
        return [], []

    wx_root = Path(wx.__file__).resolve().parent
    datas: list[tuple[str, str]] = []
    for path in wx_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix in {".pyc", ".pyo"} or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(wx_root)
        dest_dir = "wx" if len(rel.parts) == 1 else "wx/" + "/".join(rel.parts[:-1])
        datas.append((str(path), dest_dir))

    wx_hidden = collect_submodules("wx", filter=_skip_tests)
    return datas, wx_hidden


hiddenimports: list[str] = [
    "wav2chat",
    "wav2chat.cli",
    "wav2chat.gui",
    "wav2chat.gui.widgets",
    "wav2chat.funasr_backend",
    "wav2chat.jieba_cache",
    "jieba",
    "funasr",
    "modelscope",
    "torch",
    "torchaudio",
    # pyi_rth_pkgres -> pkg_resources -> plistlib -> xml.parsers.expat
    "pyexpat",
]
hiddenimports += collect_submodules("wav2chat", filter=_skip_tests)
hiddenimports += collect_submodules("funasr", filter=_skip_tests)
hiddenimports += collect_submodules("modelscope", filter=_skip_tests)

_w_bin, _w_dat, _w_paths = _collect_wav2chat_files()
binaries: list[tuple[str, str]] = list(_w_bin)
datas: list[tuple[str, str]] = list(_w_dat) + _collect_stdlib_xml()
pathex = [str(ROOT), *_w_paths]

for package in ("jieba", "funasr", "modelscope"):
    try:
        datas += collect_data_files(package)
    except Exception:
        pass

if INCLUDE_GUI:
    hiddenimports += ["wx", "wx.adv", "wx.lib", "gi", "gi.repository.GLib"]
    try:
        _wx_dat, _wx_hidden = _collect_wx_package()
        datas += _wx_dat
        hiddenimports += _wx_hidden
    except Exception as exc:
        print(f"warning: failed to collect wx: {exc}")

# PyArmor runtime (when PACKAGER_PROTECT=pyarmor)
for runtime in ROOT.glob("build/packager_stage/pyarmor_runtime_*"):
    if runtime.is_dir():
        datas.append((str(runtime), runtime.name))

excludes = [
    "tkinter",
    "matplotlib",
    "notebook",
    "IPython",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "torchvision",
    "torch.distributed",
    "torch.testing",
    "torch.utils.tensorboard",
    "tensorboard",
    "tensorboardX",
    "cv2",
    "PIL",
    "pandas",
    "nltk",
    "spacy",
    "onnx",
    "onnxruntime",
    "triton",
    "numba.tests",
    "librosa.tests",
]

if not INCLUDE_GUI:
    excludes.append("wx")

if os.environ.get("PACKAGER_TORCH", "cpu") == "cpu":
    excludes += [
        "torch.cuda",
        "torch.backends.cuda",
        "torch.backends.cudnn",
        "torch._inductor",
    ]

a = Analysis(
    [str(ROOT / "packager" / "_entry.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="wav2chat",
        debug=False,
        bootloader_ignore_signals=False,
        strip=True,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="wav2chat",
        debug=False,
        bootloader_ignore_signals=False,
        strip=True,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=True,
        upx=False,
        name="wav2chat",
    )
