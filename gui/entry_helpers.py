"""Search, entry, and transcript helper functions for the wx GUI."""

from __future__ import annotations

from pathlib import Path

from wav2chat.filename_meta import entry_timestamp, parse_audio_filename
from wav2chat.fs_browser import paths_in_directory
from wav2chat.i18n import t
from wav2chat.models import Segment, Transcript
from wav2chat.pipeline import (
    SUPPORTED_EXTENSIONS,
    default_json_path,
    find_transcript_path,
    is_supported_audio,
    is_transcript_path,
)

from wav2chat.gui.models import FileEntry


def parse_search_keywords(query: str) -> list[str]:
    return [part for part in query.split() if part]


def entry_transcript_text(entry: FileEntry) -> str:
    if entry.transcript is None:
        return ""
    return "\n".join(segment.text for segment in entry.transcript.segments)


def entry_matches_keywords(entry: FileEntry, keywords: list[str]) -> bool:
    if not keywords:
        return True
    return entry_keyword_occurrence_count(entry, keywords) > 0


def entry_keyword_occurrence_count(entry: FileEntry, keywords: list[str]) -> int:
    if not keywords or entry.transcript is None:
        return 0
    haystack = entry_transcript_text(entry).casefold()
    total = 0
    for keyword in keywords:
        needle = keyword.casefold()
        if not needle:
            continue
        start = 0
        while True:
            pos = haystack.find(needle, start)
            if pos == -1:
                break
            total += 1
            start = pos + len(needle)
    return total


def segment_matches_keywords(segment: Segment, keywords: list[str]) -> bool:
    if not keywords:
        return False
    text = segment.text.casefold()
    return all(keyword.casefold() in text for keyword in keywords)


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def entry_timestamp_label(path: Path) -> str:
    return entry_timestamp(path).strftime("%Y-%m-%d %H:%M")


def entry_timestamp_sort_key(path: Path) -> float:
    return entry_timestamp(path).timestamp()


def entry_label(path: Path) -> str:
    return path.name


def entry_title(path: Path) -> str:
    return parse_audio_filename(path).title


def entry_meta(path: Path, duration: float | None) -> str:
    parsed = parse_audio_filename(path)
    if parsed.recorded_at is not None:
        timestamp = parsed.recorded_at.strftime("%Y-%m-%d %H:%M")
    else:
        timestamp = entry_timestamp(path).strftime("%Y-%m-%d %H:%M")
    return f"{timestamp}  {t('meta.duration', duration=format_duration(duration))}"


def try_load_transcript_json(path: Path) -> Transcript | None:
    try:
        return Transcript.load_json(path)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def find_audio_for_stem(stem_path: Path) -> Path | None:
    for ext in SUPPORTED_EXTENSIONS:
        candidate = stem_path.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def entry_has_playable_audio(entry: FileEntry) -> bool:
    return entry.has_audio and entry.path.is_file() and is_supported_audio(entry.path)


def entry_json_path(entry: FileEntry) -> Path:
    if entry.session_only:
        return entry.path
    return default_json_path(entry.path)


def list_directory_paths(directory: Path) -> list[Path]:
    return paths_in_directory(directory)


__all__ = [
    "entry_has_playable_audio",
    "entry_json_path",
    "entry_keyword_occurrence_count",
    "entry_label",
    "entry_matches_keywords",
    "entry_meta",
    "entry_timestamp_label",
    "entry_timestamp_sort_key",
    "entry_transcript_text",
    "find_audio_for_stem",
    "format_duration",
    "list_directory_paths",
    "parse_search_keywords",
    "segment_matches_keywords",
    "try_load_transcript_json",
]
