"""Filesystem helpers for the wav2chat directory browser."""

from __future__ import annotations

from pathlib import Path

from wav2chat.pipeline import CHATLOG_EXTENSION, is_supported_audio

# Placeholder child so wx shows the expander before lazy load.
TREE_DUMMY_LABEL = "\u200b"


def list_subdirectories(path: Path) -> list[Path]:
    try:
        return sorted(
            child
            for child in path.iterdir()
            if child.is_dir() and not child.name.startswith(".")
        )
    except OSError:
        return []


def paths_in_directory(directory: Path) -> list[Path]:
    """Supported audio and orphan chatlog files in one directory (non-recursive)."""
    try:
        items = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    audio_paths = [path for path in items if is_supported_audio(path)]
    chatlog_paths = [
        path
        for path in items
        if path.is_file() and path.suffix.lower() == CHATLOG_EXTENSION
    ]
    audio_stems = {path.stem for path in audio_paths}
    combined = list(audio_paths)
    for chatlog_path in chatlog_paths:
        if chatlog_path.stem not in audio_stems:
            combined.append(chatlog_path)
    return sorted(combined, key=lambda p: p.name.lower())


def iter_browser_paths(
    directory: Path,
    *,
    recursive: bool = False,
    max_items: int = 0,
) -> list[Path]:
    """Collect browser file paths; ``max_items`` 0 means no limit."""
    collected: list[Path] = []
    seen: set[Path] = set()
    limit = max_items if max_items > 0 else None

    def add(path: Path) -> bool:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in seen:
            return True
        seen.add(resolved)
        collected.append(resolved)
        if limit is not None and len(collected) >= limit:
            return False
        return True

    dirs_to_visit = [directory]
    while dirs_to_visit:
        current = dirs_to_visit.pop(0)
        for path in paths_in_directory(current):
            if not add(path):
                return collected
        if recursive:
            dirs_to_visit.extend(list_subdirectories(current))
    return collected


def format_breadcrumb(path: Path) -> str:
    segments = path_breadcrumb_segments(path)
    labels = [label for label, _path in segments]
    return " > ".join(labels)


def path_breadcrumb_segments(path: Path) -> list[tuple[str, Path]]:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        resolved = path.expanduser()
    parts = resolved.parts
    if not parts:
        return [("/", Path("/"))]
    segments: list[tuple[str, Path]] = []
    current = Path(parts[0])
    segments.append(("/", current))
    for part in parts[1:]:
        current = current / part
        segments.append((part, current))
    return segments
