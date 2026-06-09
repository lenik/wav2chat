"""Shared audio conversion pipeline for CLI and GUI."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path

from wav2chat.audio import normalize_audio
from wav2chat.errors import InputNotFoundError, UnsupportedInputError
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.i18n import t
from wav2chat.models import Transcript
from wav2chat.render import render_json, render_txt

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".amr", ".aac", ".flac", ".ogg"}

# phase, file_percent (0-100 within the current file, or None if unknown)
ProgressCallback = Callable[[str, int | None], None]


def is_supported_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


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

        def on_transcribe_percent(sub_percent: int) -> None:
            if progress_callback is None:
                return
            file_percent = 10 + int(85 * sub_percent / 100)
            progress_callback("transcribing", file_percent)

        return backend.transcribe(
            wav_path=normalized_path,
            source_name=input_path.name,
            roles=roles,
            disable_progress=suppress_progress and not use_progress_hook,
            progress_callback=on_transcribe_percent if use_progress_hook else None,
        )
    finally:
        if keep_temp and normalized_path is not None and normalized_path.exists():
            kept_path = input_path.with_name(f"{input_path.stem}_normalized.wav")
            kept_path.write_bytes(normalized_path.read_bytes())
            logging.info(t("cli.kept_wav", path=kept_path))
            temp_ctx.cleanup()
        elif not keep_temp:
            temp_ctx.cleanup()


def default_json_path(input_path: Path) -> Path:
    return input_path.with_suffix(".json")


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
