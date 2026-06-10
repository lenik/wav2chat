"""Shared audio conversion pipeline for CLI and GUI."""

from __future__ import annotations

import logging
import tempfile
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from wav2chat.audio import normalize_audio
from wav2chat.errors import InputNotFoundError, UnsupportedInputError
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.i18n import t
from wav2chat.models import Transcript
from wav2chat.render import render_json, render_txt

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".amr", ".aac", ".flac", ".ogg"}

CHATLOG_EXTENSION = ".chatlog"
LEGACY_JSON_EXTENSION = ".json"
TRANSCRIPT_EXTENSIONS = {CHATLOG_EXTENSION, LEGACY_JSON_EXTENSION}

# phase, file_percent (0-100 within the current file, or None if unknown)
ProgressCallback = Callable[[str, int | None], None]

_HEARTBEAT_INTERVAL_S = 3.0


@contextmanager
def _transcribe_progress_heartbeat(
    progress_callback: ProgressCallback,
    *,
    start_percent: int = 10,
) -> Iterator[list[int]]:
    """Bump transcribing progress while FunASR runs without tqdm updates."""
    current = [start_percent]

    def pulse() -> None:
        current[0] = min(94, current[0] + 1)
        progress_callback("transcribing", current[0])

    stop = threading.Event()

    def run() -> None:
        while not stop.wait(_HEARTBEAT_INTERVAL_S):
            pulse()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield current
    finally:
        stop.set()
        thread.join(timeout=0.2)


def is_supported_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def collect_supported_audio_paths(paths: list[Path]) -> list[Path]:
    """Expand paths into supported audio files; directories are scanned recursively."""
    collected: list[Path] = []
    seen: set[Path] = set()

    def add(path: Path) -> None:
        resolved = path.resolve()
        if is_supported_audio(resolved) and resolved not in seen:
            seen.add(resolved)
            collected.append(resolved)

    def walk_dir(directory: Path) -> None:
        stack = [directory]
        while stack:
            current = stack.pop()
            try:
                children = sorted(current.iterdir(), key=lambda p: p.name.casefold())
            except OSError:
                continue
            for child in children:
                if child.is_dir():
                    stack.append(child)
                else:
                    add(child)

    for raw in paths:
        path = raw.expanduser().resolve()
        if path.is_dir():
            walk_dir(path)
        else:
            add(path)

    collected.sort(key=lambda p: str(p).casefold())
    return collected


def convert_file(
    input_path: Path,
    backend: FunASRBackend,
    roles: dict[str, str],
    keep_temp: bool = False,
    verbose: bool = False,
    disable_progress: bool | None = None,
    progress_callback: ProgressCallback | None = None,
) -> Transcript:
    """Normalize audio and transcribe it into a Transcript."""
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise InputNotFoundError(f"Input file not found: {input_path}")
    if not is_supported_audio(input_path):
        raise UnsupportedInputError(
            f"Unsupported input type: {input_path.suffix or '(no extension)'}. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    temp_ctx = tempfile.TemporaryDirectory(prefix="wav2chat_")
    temp_dir = Path(temp_ctx.name)
    normalized_path: Path | None = None

    try:
        if progress_callback is not None:
            progress_callback("normalizing", 0)

        normalized_path = normalize_audio(input_path, temp_dir)
        if verbose:
            logging.info("Normalized audio: %s", normalized_path)

        if progress_callback is not None:
            progress_callback("normalizing", 10)

        suppress_progress = (
            not verbose if disable_progress is None else disable_progress
        )
        use_progress_hook = progress_callback is not None

        if progress_callback is not None:
            progress_callback("transcribing", 10)

        if use_progress_hook:
            with _transcribe_progress_heartbeat(progress_callback) as heartbeat:
                def on_transcribe_percent_tracked(sub_percent: int) -> None:
                    file_percent = 10 + int(85 * sub_percent / 100)
                    heartbeat[0] = file_percent
                    progress_callback("transcribing", file_percent)

                return backend.transcribe(
                    wav_path=normalized_path,
                    source_name=input_path.name,
                    roles=roles,
                    disable_progress=False,
                    progress_callback=on_transcribe_percent_tracked,
                )

        return backend.transcribe(
            wav_path=normalized_path,
            source_name=input_path.name,
            roles=roles,
            disable_progress=suppress_progress,
            progress_callback=None,
        )
    finally:
        if keep_temp and normalized_path is not None and normalized_path.exists():
            kept_path = input_path.with_name(f"{input_path.stem}_normalized.wav")
            kept_path.write_bytes(normalized_path.read_bytes())
            logging.info(t("cli.kept_wav", path=kept_path))
            temp_ctx.cleanup()
        elif not keep_temp:
            temp_ctx.cleanup()


def is_transcript_path(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TRANSCRIPT_EXTENSIONS


def default_json_path(input_path: Path) -> Path:
    """Return the default sidecar path for structured transcript output."""
    return input_path.with_suffix(CHATLOG_EXTENSION)


def find_transcript_path(input_path: Path) -> Path | None:
    """Return an existing transcript sidecar, preferring .chatlog over legacy .json."""
    chatlog_path = input_path.with_suffix(CHATLOG_EXTENSION)
    if chatlog_path.is_file():
        return chatlog_path
    legacy_path = input_path.with_suffix(LEGACY_JSON_EXTENSION)
    if legacy_path.is_file():
        return legacy_path
    return None


def default_txt_path(input_path: Path) -> Path:
    return input_path.with_suffix(".txt")


def write_transcript_outputs(
    transcript: Transcript,
    *,
    txt_path: Path | None = None,
    json_path: Path | None = None,
    quiet: bool = False,
) -> None:
    if txt_path is not None:
        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text(render_txt(transcript), encoding="utf-8")
        if not quiet:
            print(t("cli.wrote_txt", path=txt_path))

    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(render_json(transcript), encoding="utf-8")
        if not quiet:
            print(t("cli.wrote_json", path=json_path))
