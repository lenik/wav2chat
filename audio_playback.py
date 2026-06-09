"""Play audio file segments for GUI preview."""

from __future__ import annotations

import shutil
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from wav2chat.errors import FFmpegNotFoundError
from wav2chat.models import Segment


def segment_play_range(
    segment: Segment,
    file_duration: float | None = None,
    *,
    fallback_seconds: float = 3.0,
) -> tuple[float, float]:
    """Return (start, end) seconds to play for a transcript segment."""
    start = max(0.0, float(segment.start))
    end = float(segment.end)
    if end <= start:
        end = start + fallback_seconds
    if file_duration is not None and file_duration > 0:
        end = min(end, file_duration)
    if end <= start:
        end = start + fallback_seconds
    return start, end


class SegmentPlayer:
    """Play one audio segment at a time via ffplay."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()

    def play(
        self,
        path: Path,
        start: float,
        end: float,
        *,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.stop()

        ffplay = shutil.which("ffplay")
        if ffplay is None:
            raise FFmpegNotFoundError(
                "ffplay is not installed or not on PATH. "
                "On Debian/Ubuntu run: sudo apt install -y ffmpeg"
            )

        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Audio file not found: {path}")

        duration = max(0.05, end - start)
        command = [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            str(path),
        ]

        def worker() -> None:
            process = subprocess.Popen(command)
            with self._lock:
                self._process = process
            process.wait()
            with self._lock:
                if self._process is process:
                    self._process = None
            if on_done is not None:
                on_done()

        threading.Thread(target=worker, daemon=True).start()
