"""Core data structures for wav2chat transcripts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Segment:
    start: float
    end: float
    speaker: str
    role: str | None
    text: str


@dataclass
class Transcript:
    source: str
    duration: float | None
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "duration": self.duration,
            "segments": [asdict(segment) for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        segments = [
            Segment(
                start=float(item["start"]),
                end=float(item["end"]),
                speaker=str(item["speaker"]),
                role=item.get("role"),
                text=str(item["text"]),
            )
            for item in data.get("segments", [])
        ]
        duration = data.get("duration")
        return cls(
            source=str(data.get("source", "")),
            duration=float(duration) if duration is not None else None,
            segments=segments,
        )

    @classmethod
    def load_json(cls, path: Path) -> Transcript:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        return cls.from_dict(data)
