"""Parse contact names and phone numbers from audio filenames."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

# Legacy / generic: 99 常汉杰(15967387860)_20230714151024.mp3
_PATTERN_NAME_PHONE_TS = re.compile(
    r"^(?:\d+\s+)?(?P<name>.+?)\((?P<phone>\d{7,})\)(?:_(?P<ts>\d{14}))?$"
)
# Huawei / Honor: 张三_2026-06-10_17-30-22.mp3
_PATTERN_HUAWEI = re.compile(
    r"^(?P<name>.+)_(?P<date>\d{4}-\d{2}-\d{2})_(?P<time>\d{2}-\d{2}-\d{2})$"
)
# OPPO / OnePlus: REC_13800138000_20260610173000.mp3
_PATTERN_OPPO = re.compile(
    r"^REC[_-](?P<phone>\d{7,})_(?P<ts>\d{12,14})$",
    re.IGNORECASE,
)
# Xiaomi / vivo: 13800138000_20260610_173000.mp3
_PATTERN_PHONE_DATE_TIME = re.compile(
    r"^(?P<phone>\d{7,})_(?P<date>\d{8})_(?P<time>\d{6})$"
)
# Xiaomi / vivo compact: 13800138000_20260610173000.mp3
_PATTERN_PHONE_TS = re.compile(r"^(?P<phone>\d{7,})_(?P<ts>\d{12,14})$")
# Xiaomi name variant: 李经理_20260610173000.mp3
_PATTERN_NAME_TS = re.compile(r"^(?P<name>(?!\d{7,}$).+?)_(?P<ts>\d{12,14})$")
# iPhone: 通话录音-20260610-173005.m4a
_PATTERN_IPHONE = re.compile(
    r"^(?:通话录音|Call Recording|Voice Memo)[-_](?P<date>\d{8})[-_](?P<time>\d{6})$",
    re.IGNORECASE,
)
# Samsung: 通话录音_20260610_173000.mp3
_PATTERN_SAMSUNG = re.compile(r"^通话录音_(?P<date>\d{8})_(?P<time>\d{6})$")
_PHONE_PATTERN = re.compile(r"(\d{7,})")


@dataclass(frozen=True)
class ParsedFilename:
    raw_stem: str
    display_name: str
    phone: str | None = None
    recorded_at: dt.datetime | None = None

    @property
    def title(self) -> str:
        if self.phone and self.display_name != self.phone:
            return f"{self.display_name} ({self.phone})"
        if self.phone:
            return self.phone
        return self.display_name


def parse_audio_filename(path: Path) -> ParsedFilename:
    stem = path.stem

    match = _PATTERN_NAME_PHONE_TS.match(stem)
    if match:
        return _build(
            stem,
            display_name=match.group("name").strip(),
            phone=match.group("phone"),
            recorded_at=_parse_compact_timestamp(match.group("ts")),
        )

    match = _PATTERN_HUAWEI.match(stem)
    if match:
        return _build(
            stem,
            display_name=match.group("name").strip(),
            recorded_at=_parse_dashed_datetime(
                match.group("date"),
                match.group("time"),
            ),
        )

    match = _PATTERN_OPPO.match(stem)
    if match:
        return _build(
            stem,
            display_name=match.group("phone"),
            phone=match.group("phone"),
            recorded_at=_parse_compact_timestamp(match.group("ts")),
        )

    match = _PATTERN_PHONE_DATE_TIME.match(stem)
    if match:
        phone = match.group("phone")
        return _build(
            stem,
            display_name=phone,
            phone=phone,
            recorded_at=_parse_date_time(
                match.group("date"),
                match.group("time"),
            ),
        )

    match = _PATTERN_PHONE_TS.match(stem)
    if match:
        phone = match.group("phone")
        return _build(
            stem,
            display_name=phone,
            phone=phone,
            recorded_at=_parse_compact_timestamp(match.group("ts")),
        )

    match = _PATTERN_NAME_TS.match(stem)
    if match:
        return _build(
            stem,
            display_name=match.group("name").strip(),
            recorded_at=_parse_compact_timestamp(match.group("ts")),
        )

    match = _PATTERN_IPHONE.match(stem)
    if match:
        return _build(
            stem,
            display_name="通话录音",
            recorded_at=_parse_date_time(match.group("date"), match.group("time")),
        )

    match = _PATTERN_SAMSUNG.match(stem)
    if match:
        return _build(
            stem,
            display_name="通话录音",
            recorded_at=_parse_date_time(match.group("date"), match.group("time")),
        )

    phone_match = _PHONE_PATTERN.search(stem)
    phone = phone_match.group(1) if phone_match else None
    display_name = phone if phone and stem.replace(phone, "").strip("_- ") == "" else stem
    return ParsedFilename(raw_stem=stem, display_name=display_name, phone=phone)


def _build(
    stem: str,
    *,
    display_name: str,
    phone: str | None = None,
    recorded_at: dt.datetime | None = None,
) -> ParsedFilename:
    return ParsedFilename(
        raw_stem=stem,
        display_name=display_name,
        phone=phone,
        recorded_at=recorded_at,
    )


def _parse_date_time(date: str, time: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(f"{date}{time}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _parse_dashed_datetime(date: str, time: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(f"{date} {time.replace('-', ':')}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_compact_timestamp(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    for fmt, length in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(digits) >= length:
            try:
                return dt.datetime.strptime(digits[:length], fmt)
            except ValueError:
                continue
    if len(digits) == 13:
        try:
            return dt.datetime.strptime(
                f"{digits[:8]}{digits[8:10]}{digits[10:12]}{digits[12:].ljust(2, '0')}",
                "%Y%m%d%H%M%S",
            )
        except ValueError:
            return None
    return None


def entry_timestamp(path: Path) -> dt.datetime:
    parsed = parse_audio_filename(path)
    if parsed.recorded_at is not None:
        return parsed.recorded_at
    return dt.datetime.fromtimestamp(path.stat().st_mtime)
