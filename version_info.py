"""Version and dependency reporting for wav2chat."""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys

from wav2chat import __version__
from wav2chat.funasr_backend import (
    DEFAULT_ASR_MODEL,
    DEFAULT_PUNC_MODEL,
    DEFAULT_SPK_MODEL,
    DEFAULT_VAD_MODEL,
)


def _package_version(distribution_name: str) -> str:
    try:
        return importlib.metadata.version(distribution_name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _ffmpeg_version() -> str:
    if shutil.which("ffmpeg") is None:
        return "not found"
    try:
        completed = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        line = (completed.stdout or completed.stderr).splitlines()[0]
        if line.startswith("ffmpeg version "):
            return line.removeprefix("ffmpeg version ").split()[0]
        return line or "unknown"
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "unknown"


def _wx_version() -> str:
    try:
        import wx
    except ImportError:
        return "not installed"
    return wx.version()


def format_version_info() -> str:
    python_bits = platform.architecture()[0]
    lines = [
        f"wav2chat {__version__}",
        f"Python {sys.version.split()[0]} ({platform.system()} {platform.machine()}, {python_bits})",
        f"funasr {_package_version('funasr')}",
        f"modelscope {_package_version('modelscope')}",
        f"torch {_package_version('torch')}",
        f"torchaudio {_package_version('torchaudio')}",
        f"ffmpeg {_ffmpeg_version()}",
        f"wxPython {_wx_version()}",
        "FunASR models:",
        f"  ASR: {DEFAULT_ASR_MODEL}",
        f"  VAD: {DEFAULT_VAD_MODEL}",
        f"  PUNC: {DEFAULT_PUNC_MODEL}",
        f"  SPK: {DEFAULT_SPK_MODEL}",
    ]
    return "\n".join(lines)
