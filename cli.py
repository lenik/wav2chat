"""Command-line interface for wav2chat."""

from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from wav2chat import __version__
from wav2chat.audio import normalize_audio
from wav2chat.errors import (
    EmptyBatchDirectoryError,
    InputNotFoundError,
    UnsupportedBackendError,
    UnsupportedInputError,
    Wav2ChatError,
)
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.render import render_json, render_txt

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".amr", ".aac", ".flac", ".ogg"}


def _parse_roles(values: list[str] | None) -> dict[str, str]:
    roles: dict[str, str] = {}
    if not values:
        return roles
    for item in values:
        if "=" not in item:
            raise UnsupportedInputError(
                f"Invalid --role value {item!r}. Expected format: spk0=我"
            )
        speaker, role = item.split("=", 1)
        speaker = speaker.strip()
        role = role.strip()
        if not speaker or not role:
            raise UnsupportedInputError(
                f"Invalid --role value {item!r}. Speaker and role must be non-empty."
            )
        roles[speaker] = role
    return roles


def _is_supported_audio(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS


def _collect_batch_files(directory: Path) -> list[Path]:
    files = sorted(
        path
        for path in directory.iterdir()
        if _is_supported_audio(path)
    )
    if not files:
        raise EmptyBatchDirectoryError(
            f"No supported audio files found in {directory}. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
    return files


def _resolve_output_paths(
    input_path: Path,
    output: Path | None,
    json_output: Path | None,
    batch: bool,
) -> tuple[Path | None, Path | None]:
    if batch:
        txt_dir = output or input_path
        json_dir = json_output
        txt_dir.mkdir(parents=True, exist_ok=True)
        if json_dir is not None:
            json_dir.mkdir(parents=True, exist_ok=True)
        return txt_dir, json_dir

    txt_path = output
    json_path = json_output
    if txt_path is not None:
        txt_path.parent.mkdir(parents=True, exist_ok=True)
    if json_path is not None:
        json_path.parent.mkdir(parents=True, exist_ok=True)
    return txt_path, json_path


def _default_txt_path(input_path: Path) -> Path:
    return input_path.with_suffix(".txt")


def _default_json_path(input_path: Path) -> Path:
    return input_path.with_suffix(".json")


def _create_backend(args: argparse.Namespace) -> FunASRBackend:
    if args.backend != "funasr":
        raise UnsupportedBackendError(
            f"Unsupported backend {args.backend!r}. Only 'funasr' is available."
        )
    if args.lang != "zh":
        logging.warning("Only Chinese (zh) is supported in this version; continuing anyway.")
    return FunASRBackend(
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
    )


def _process_file(
    input_path: Path,
    backend: FunASRBackend,
    roles: dict[str, str],
    txt_path: Path | None,
    json_path: Path | None,
    keep_temp: bool,
    verbose: bool,
) -> None:
    input_path = input_path.resolve()
    if not input_path.is_file():
        raise InputNotFoundError(f"Input file not found: {input_path}")
    if not _is_supported_audio(input_path):
        raise UnsupportedInputError(
            f"Unsupported input type: {input_path.suffix or '(no extension)'}. "
            f"Supported extensions: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )

    if txt_path is None and json_path is None:
        txt_path = _default_txt_path(input_path)

    temp_ctx = tempfile.TemporaryDirectory(prefix="wav2chat_")
    temp_dir = Path(temp_ctx.name)
    normalized_path: Path | None = None

    try:
        normalized_path = normalize_audio(input_path, temp_dir)
        if verbose:
            logging.info("Normalized audio: %s", normalized_path)

        transcript = backend.transcribe(
            wav_path=normalized_path,
            source_name=input_path.name,
            roles=roles,
        )

        if txt_path is not None:
            txt_path.write_text(render_txt(transcript), encoding="utf-8")
            print(f"Wrote {txt_path}")

        if json_path is not None:
            json_path.write_text(render_json(transcript), encoding="utf-8")
            print(f"Wrote {json_path}")
    finally:
        if keep_temp and normalized_path is not None and normalized_path.exists():
            kept_path = input_path.with_name(f"{input_path.stem}_normalized.wav")
            kept_path.write_bytes(normalized_path.read_bytes())
            print(f"Kept normalized wav: {kept_path}")
            temp_ctx.cleanup()
        elif not keep_temp:
            temp_ctx.cleanup()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wav2chat",
        description="Convert audio recordings into speaker-segmented chat transcripts.",
    )
    parser.add_argument("input", type=Path, help="Input audio file or directory")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Output .txt file, or output directory in batch mode",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        type=Path,
        help="Output .json file, or output directory in batch mode",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all supported audio files in a directory",
    )
    parser.add_argument(
        "--backend",
        default="funasr",
        help="Transcription backend (default: funasr)",
    )
    parser.add_argument(
        "--lang",
        default="zh",
        help="Language hint (default: zh)",
    )
    parser.add_argument(
        "--min-speakers",
        type=int,
        default=None,
        help="Minimum number of speakers for diarization",
    )
    parser.add_argument(
        "--max-speakers",
        type=int,
        default=None,
        help="Maximum number of speakers for diarization",
    )
    parser.add_argument(
        "--role",
        action="append",
        default=[],
        metavar="SPK=NAME",
        help="Map speaker id to display name, e.g. --role spk0=我",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the normalized intermediate WAV file",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print debug information",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    try:
        roles = _parse_roles(args.role)
        backend = _create_backend(args)
        input_path = args.input.resolve()

        if not input_path.exists():
            raise InputNotFoundError(f"Input path does not exist: {input_path}")

        if args.batch:
            if not input_path.is_dir():
                raise UnsupportedInputError(
                    f"--batch requires a directory, got file: {input_path}"
                )
            txt_dir, json_dir = _resolve_output_paths(
                input_path,
                args.output,
                args.json_output,
                batch=True,
            )
            files = _collect_batch_files(input_path)
            failures: list[str] = []

            for file_path in files:
                txt_path = txt_dir / f"{file_path.stem}.txt"
                json_path = (
                    json_dir / f"{file_path.stem}.json" if json_dir is not None else None
                )
                try:
                    _process_file(
                        input_path=file_path,
                        backend=backend,
                        roles=roles,
                        txt_path=txt_path,
                        json_path=json_path,
                        keep_temp=args.keep_temp,
                        verbose=args.verbose,
                    )
                except Wav2ChatError as exc:
                    failures.append(f"{file_path.name}: {exc}")
                    logging.error("%s: %s", file_path.name, exc)
                except Exception as exc:
                    failures.append(f"{file_path.name}: {exc}")
                    logging.exception("Unexpected error while processing %s", file_path.name)

            if failures:
                logging.error("Batch finished with %d failure(s).", len(failures))
                for message in failures:
                    logging.error("  - %s", message)
                return 1
            return 0

        if input_path.is_dir():
            raise UnsupportedInputError(
                f"Input is a directory: {input_path}. Use --batch to process a folder."
            )

        txt_path, json_path = _resolve_output_paths(
            input_path,
            args.output,
            args.json_output,
            batch=False,
        )
        _process_file(
            input_path=input_path,
            backend=backend,
            roles=roles,
            txt_path=txt_path,
            json_path=json_path,
            keep_temp=args.keep_temp,
            verbose=args.verbose,
        )
        return 0

    except Wav2ChatError as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logging.error("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
