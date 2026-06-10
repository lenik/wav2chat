#!/usr/bin/env python3
"""Migrate transcript JSON files to the speakers-indexed format."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wav2chat.models import Transcript, migrate_legacy_transcript_dict


def _migrate_file(path: Path, *, dry_run: bool) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")

    if "speakers" in raw:
        transcript = Transcript.from_dict(raw)
        output = transcript.to_dict()
        action = "normalized"
    else:
        output = migrate_legacy_transcript_dict(raw)
        action = "migrated"

    if not dry_run:
        path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update wav2chat transcript JSON to the speakers-indexed format.",
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="JSON transcript files to update in place",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would change without writing files",
    )
    args = parser.parse_args(argv)

    failures = 0
    for path in args.files:
        try:
            action = _migrate_file(path.resolve(), dry_run=args.dry_run)
            suffix = " (dry run)" if args.dry_run else ""
            print(f"{action}: {path}{suffix}")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            failures += 1
            print(f"error: {path}: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
