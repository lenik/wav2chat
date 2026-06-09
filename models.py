"""Core data structures for wav2chat transcripts."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


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
