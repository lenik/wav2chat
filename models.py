"""Core data structures for wav2chat transcripts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_SPEAKER_AVATARS = ("👦", "👧", "👨", "👩")
ME_SPEAKER_ROLE = "me"


def default_speaker_role(name: str, role: str = "") -> str:
    if name == "spk1" and not role.strip():
        return ME_SPEAKER_ROLE
    return role


def default_speaker_avatar(speaker_index: int) -> str:
    return DEFAULT_SPEAKER_AVATARS[speaker_index % len(DEFAULT_SPEAKER_AVATARS)]


def speaker_index_from_name(name: str) -> int | None:
    if name.startswith("spk") and name[3:].isdigit():
        return int(name[3:])
    return None


@dataclass
class Speaker:
    name: str
    role: str = ""
    gender: str = ""
    avatar: str = ""

    def display_label(self) -> str:
        return self.role or self.name

    def to_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "role": self.role,
            "gender": self.gender,
            "avatar": self.avatar,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Speaker:
        name = str(data.get("name", "spk0"))
        return cls(
            name=name,
            role=default_speaker_role(name, str(data.get("role", ""))),
            gender=str(data.get("gender", "")),
            avatar=str(data.get("avatar", "")),
        )


@dataclass
class Segment:
    start: float
    end: float
    speaker: int
    text: str


@dataclass
class Transcript:
    source: str
    duration: float | None
    speakers: list[Speaker] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    primary_speaker: int | None = None

    def speaker_at(self, index: int) -> Speaker:
        if 0 <= index < len(self.speakers):
            return self.speakers[index]
        fallback = f"spk{index}"
        return Speaker(name=fallback, role=fallback)

    def speaker_label(self, index: int) -> str:
        return self.speaker_at(index).display_label()

    def is_me_speaker(self, speaker_index: int) -> bool:
        me_index = self._me_speaker_index()
        if me_index is not None:
            return speaker_index == me_index
        if not self.segments:
            return speaker_index == 0
        legacy_left = self.segments[0].speaker
        return speaker_index != legacy_left

    def _me_speaker_index(self) -> int | None:
        if self.primary_speaker is not None:
            return self.primary_speaker
        for index, speaker in enumerate(self.speakers):
            if speaker.role.strip().lower() == ME_SPEAKER_ROLE:
                return index
        return None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "duration": self.duration,
            "speakers": [speaker.to_dict() for speaker in self.speakers],
            "segments": [asdict(segment) for segment in self.segments],
        }
        if self.primary_speaker is not None:
            payload["primary_speaker"] = self.primary_speaker
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        if "speakers" not in data:
            data = migrate_legacy_transcript_dict(data)
        speakers = [Speaker.from_dict(item) for item in data.get("speakers", [])]
        segments = [
            Segment(
                start=float(item["start"]),
                end=float(item["end"]),
                speaker=int(item["speaker"]),
                text=str(item["text"]),
            )
            for item in data.get("segments", [])
        ]
        duration = data.get("duration")
        primary_raw = data.get("primary_speaker")
        primary_speaker = int(primary_raw) if primary_raw is not None else None
        return cls(
            source=str(data.get("source", "")),
            duration=float(duration) if duration is not None else None,
            speakers=speakers,
            segments=segments,
            primary_speaker=primary_speaker,
        )

    @classmethod
    def load_json(cls, path: Path) -> Transcript:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected a JSON object in {path}")
        return cls.from_dict(data)


def migrate_legacy_transcript_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Convert pre-speakers JSON (string speaker + segment role) to indexed format."""
    speaker_order: list[str] = []
    speaker_to_index: dict[str, int] = {}
    segment_roles: dict[str, str] = {}

    for item in data.get("segments", []):
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker", "spk0"))
        if speaker_id not in speaker_to_index:
            speaker_to_index[speaker_id] = len(speaker_order)
            speaker_order.append(speaker_id)
        role = item.get("role")
        if role and speaker_id not in segment_roles:
            segment_roles[speaker_id] = str(role)

    speakers = [
        {
            "name": speaker_id,
            "role": default_speaker_role(
                speaker_id,
                segment_roles.get(speaker_id, ""),
            ),
            "gender": "",
            "avatar": default_speaker_avatar(index),
        }
        for index, speaker_id in enumerate(speaker_order)
    ]

    segments: list[dict[str, Any]] = []
    for item in data.get("segments", []):
        if not isinstance(item, dict):
            continue
        speaker_id = str(item.get("speaker", "spk0"))
        segments.append(
            {
                "start": item["start"],
                "end": item["end"],
                "speaker": speaker_to_index.get(speaker_id, 0),
                "text": item.get("text", ""),
            }
        )

    return {
        "source": data.get("source", ""),
        "duration": data.get("duration"),
        "speakers": speakers,
        "segments": segments,
    }


def index_string_speaker_segments(
    segments: list[tuple[float, float, str, str]],
    roles: dict[str, str] | None = None,
) -> tuple[list[Speaker], list[Segment]]:
    """Build speakers list and indexed segments from FunASR string speaker ids."""
    role_map = roles or {}
    speaker_order: list[str] = []
    speaker_to_index: dict[str, int] = {}

    indexed_segments: list[Segment] = []
    for start, end, speaker_id, text in segments:
        if speaker_id not in speaker_to_index:
            speaker_to_index[speaker_id] = len(speaker_order)
            speaker_order.append(speaker_id)
        indexed_segments.append(
            Segment(
                start=start,
                end=end,
                speaker=speaker_to_index[speaker_id],
                text=text,
            )
        )

    speakers = [
        Speaker(
            name=speaker_id,
            role=default_speaker_role(speaker_id, role_map.get(speaker_id, "")),
            avatar=default_speaker_avatar(index),
        )
        for index, speaker_id in enumerate(speaker_order)
    ]
    return speakers, indexed_segments
