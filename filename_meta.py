"""Parse contact names and phone numbers from audio filenames."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

# Example: 99 常汉杰(15967387860)_20230714151024.mp3
_FILENAME_PATTERN = re.compile(
    r"^(?:\d+\s+)?(?P<name>.+?)\((?P<phone>\d{7,})\)(?:_(?P<ts>\d{14}))?$"
)
_PHONE_PATTERN = re.compile(r"(\d{7,})")


@dataclass(frozen=True)
class ParsedFilename:
    raw_stem: str
    display_name: str
    phone: str | None = None
    recorded_at: dt.datetime | None = None

    @property
    def title(self) -> str:
        if self.phone:
            return f"{self.display_name} ({self.phone})"
        return self.display_name


def parse_audio_filename(path: Path) -> ParsedFilename:
    stem = path.stem
    match = _FILENAME_PATTERN.match(stem)
    if match:
        recorded_at = _parse_timestamp(match.group("ts"))
        return ParsedFilename(
            raw_stem=stem,
            display_name=match.group("name").strip(),
            phone=match.group("phone"),
            recorded_at=recorded_at,
        )

    phone_match = _PHONE_PATTERN.search(stem)
    phone = phone_match.group(1) if phone_match else None
    return ParsedFilename(raw_stem=stem, display_name=stem, phone=phone)


def _parse_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError:
        return None


def entry_timestamp(path: Path) -> dt.datetime:
    parsed = parse_audio_filename(path)
    if parsed.recorded_at is not None:
        return parsed.recorded_at
    return dt.datetime.fromtimestamp(path.stat().st_mtime)
