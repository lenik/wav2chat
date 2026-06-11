"""Command-line interface for wav2chat."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wav2chat.errors import (
    EmptyBatchDirectoryError,
    InputNotFoundError,
    UnsupportedBackendError,
    UnsupportedInputError,
    Wav2ChatError,
)
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.i18n import set_locale
from wav2chat.pipeline import (
    SUPPORTED_EXTENSIONS,
    convert_file,
    default_json_path,
    default_txt_path,
    is_supported_audio,
    write_transcript_outputs,
)


from wav2chat.version_info import format_version_info


class _VersionAction(argparse.Action):
    def __init__(
        self,
        option_strings: list[str],
        dest: str = argparse.SUPPRESS,
        default: str = argparse.SUPPRESS,
        help: str | None = None,
    ) -> None:
        super().__init__(
            option_strings=option_strings,
            dest=dest,
            nargs=0,
            default=default,
            help=help,
        )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        print(format_version_info())
        parser.exit()


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


def _collect_batch_files(directory: Path) -> list[Path]:
    files = sorted(
        path
        for path in directory.iterdir()
        if is_supported_audio(path)
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
        refresh_models=getattr(args, "refresh_models", False),
    )


def _configure_logging(verbose: bool, quiet: bool) -> None:
    if quiet and not verbose:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _process_file(
    input_path: Path,
    backend: FunASRBackend,
    roles: dict[str, str],
    txt_path: Path | None,
    json_path: Path | None,
    keep_temp: bool,
    verbose: bool,
    quiet: bool,
) -> None:
    input_path = input_path.resolve()
    if txt_path is None and json_path is None:
        txt_path = default_txt_path(input_path)

    transcript = convert_file(
        input_path=input_path,
        backend=backend,
        roles=roles,
        keep_temp=keep_temp,
        verbose=verbose,
    )
    write_transcript_outputs(
        transcript,
        txt_path=txt_path,
        json_path=json_path,
        quiet=quiet,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wav2chat",
        description="Convert audio recordings into speaker-segmented chat transcripts.",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        help="Input audio file or directory",
    )
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
        help="Output .chatlog file, or output directory in batch mode",
    )
    parser.add_argument(
        "-b",
        "--batch",
        action="store_true",
        help="Process all supported audio files in a directory",
    )
    parser.add_argument(
        "-e",
        "--backend",
        default="funasr",
        help="Transcription backend (default: funasr)",
    )
    parser.add_argument(
        "-l",
        "--lang",
        default="zh",
        help="Language hint (default: zh)",
    )
    parser.add_argument(
        "-n",
        "--min-speakers",
        type=int,
        default=None,
        help="Minimum number of speakers for diarization",
    )
    parser.add_argument(
        "-m",
        "--max-speakers",
        type=int,
        default=None,
        help="Maximum number of speakers for diarization",
    )
    parser.add_argument(
        "-r",
        "--role",
        action="append",
        default=[],
        metavar="SPK=NAME",
        help="Map speaker id to display name, e.g. --role spk0=我",
    )
    parser.add_argument(
        "-k",
        "--keep-temp",
        action="store_true",
        help="Keep the normalized intermediate WAV file",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print debug information",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )
    parser.add_argument(
        "-g",
        "--gui",
        action="store_true",
        help="Open the desktop GUI",
    )
    parser.add_argument(
        "--refresh-models",
        action="store_true",
        help="Re-check ModelScope and reload models (default: load from local cache with mmap)",
    )
    parser.add_argument(
        "--ui-lang",
        choices=["en", "zh", "ja", "ko"],
        default=None,
        help="UI language (default: auto from LANG/LC_MESSAGES)",
    )
    parser.add_argument(
        "--version",
        action=_VersionAction,
        help="Show program version and dependency information",
    )
    return parser


def _argv_for_parse(argv: list[str] | None) -> list[str]:
    effective = sys.argv[1:] if argv is None else list(argv)
    if getattr(sys, "frozen", False) and not effective:
        return ["--gui"]
    return effective


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_argv_for_parse(argv))

    _configure_logging(args.verbose, args.quiet)
    set_locale(args.ui_lang)

    try:
        roles = _parse_roles(args.role)
        args._roles = roles  # used by GUI

        if args.gui:
            from wav2chat.gui import run_gui

            return run_gui(args)

        if args.input is None:
            raise UnsupportedInputError("Input path is required unless --gui is used.")

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
                json_path = json_dir / default_json_path(file_path).name if json_dir is not None else None
                try:
                    _process_file(
                        input_path=file_path,
                        backend=backend,
                        roles=roles,
                        txt_path=txt_path,
                        json_path=json_path,
                        keep_temp=args.keep_temp,
                        verbose=args.verbose,
                        quiet=args.quiet,
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
            quiet=args.quiet,
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
