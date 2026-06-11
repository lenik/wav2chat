"""Data models for the wx GUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wav2chat.models import Transcript


@dataclass
class FileEntry:
    path: Path
    status: str = "unconverted"
    transcript: Transcript | None = None
    error: str | None = None
    has_audio: bool = True
    session_only: bool = False
    json_invalid: bool = False


@dataclass
class GuiSettings:
    backend: str = "funasr"
    lang: str = "zh"
    ui_lang: str | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    roles: dict[str, str] = field(default_factory=dict)
    keep_temp: bool = False
    verbose: bool = False
    quiet: bool = False
    refresh_models: bool = False
