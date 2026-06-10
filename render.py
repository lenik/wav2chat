"""Render transcripts to txt and json."""

from __future__ import annotations

import json

from wav2chat.models import Segment, Transcript


def _format_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def display_name(transcript: Transcript, segment: Segment) -> str:
    return transcript.speaker_label(segment.speaker)


def render_txt(transcript: Transcript) -> str:
    lines = [f"# source: {transcript.source}", ""]
    for segment in transcript.segments:
        start = _format_timestamp(segment.start)
        end = _format_timestamp(segment.end)
        name = display_name(transcript, segment)
        lines.append(f"[{start} - {end}] {name}: {segment.text}")
    return "\n".join(lines).rstrip() + "\n"


def format_timestamp(seconds: float) -> str:
    return _format_timestamp(seconds)


def render_json(transcript: Transcript) -> str:
    return json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2) + "\n"
