"""Filesystem helpers for the wav2chat directory browser."""

from __future__ import annotations

from pathlib import Path

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
