"""Audio preprocessing via ffmpeg."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from wav2chat.errors import FFmpegConversionError, FFmpegNotFoundError, InputNotFoundError


def normalize_audio(input_path: Path, temp_dir: Path) -> Path:
    """Convert arbitrary audio to mono 16 kHz WAV using ffmpeg."""
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise InputNotFoundError(f"Input file not found: {input_path}")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise FFmpegNotFoundError(
            "ffmpeg is not installed or not on PATH. "
            "On Debian/Ubuntu run: sudo apt update && sudo apt install -y ffmpeg"
        )

    output_path = temp_dir / f"{input_path.stem}_normalized.wav"
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(input_path),
        "-ac",
        "1",
        "-ar",
        "16000",
        "-vn",
        str(output_path),
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise FFmpegConversionError(f"Failed to run ffmpeg: {exc}") from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise FFmpegConversionError(
            f"ffmpeg failed to convert {input_path.name} (exit {completed.returncode}):\n{stderr}"
        )

    if not output_path.is_file():
        raise FFmpegConversionError(
            f"ffmpeg reported success but output file was not created: {output_path}"
        )

    return output_path
