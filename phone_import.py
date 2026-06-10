"""Discover phone storage (MTP/gvfs) and import call recordings."""

from __future__ import annotations

import logging
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

logger = logging.getLogger(__name__)

PhoneScanStatusCallback = Callable[[str, dict[str, object]], None] | None


def _report_status(
    callback: PhoneScanStatusCallback,
    key: str,
    **kwargs: object,
) -> None:
    if callback is not None:
        callback(key, kwargs)

AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".aac", ".amr", ".3gp", ".ogg", ".flac", ".opus"}

MTP_MOUNT_PREFIXES = ("mtp:", "mtp%3a", "gphoto2:", "ptp:", "afc:", "usb:")

# Vendor detection from mount / folder names (lowercase substring match).
VENDOR_PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    ("xiaomi", "vendor_xiaomi", ("xiaomi", "redmi", "poco", "mi ")),
    ("apple", "vendor_apple", ("iphone", "apple", "ipad")),
    ("huawei", "vendor_huawei", ("huawei", "honor")),
    ("oppo", "vendor_oppo", ("oppo", "realme", "oneplus")),
    ("vivo", "vendor_vivo", ("vivo", "iqoo")),
    ("samsung", "vendor_samsung", ("samsung", "galaxy")),
]

# Call-recording folders (relative to storage root). Keep call-specific paths only.
CALL_RECORDING_DIRS: tuple[str, ...] = (
    "MIUI/sound_recorder/call_rec",
    "Sounds/CallRecord",
    "Sounds/Call",
    "Recordings/Call",
    "Record/Call",
    "CallRecordings",
    "Call Recording",
    "PhoneRecord",
    "Recorder/Call",
    "Music/Call recordings",
    "Music/CallRecordings",
)

XIAOMI_CALL_RECORDING_DIRS: tuple[str, ...] = (
    "MIUI/sound_recorder/call_rec",
)

# Directories where every audio file is treated as a call recording.
STRICT_CALL_RECORDING_DIRS: frozenset[str] = frozenset(
    {
        "MIUI/sound_recorder/call_rec",
        "Sounds/CallRecord",
        "Sounds/Call",
        "Recordings/Call",
        "Record/Call",
        "CallRecordings",
        "Call Recording",
        "PhoneRecord",
        "Recorder/Call",
    }
)

# iPhone Voice Memos / limited MTP exposure.
IPHONE_RECORDING_DIRS: tuple[str, ...] = (
    "Recordings",
    "Voice Memos",
    "Internal Storage/Recordings",
)

# Typical MTP storage volume folder names (one level under the gvfs mount).
MTP_STORAGE_DIR_NAMES: tuple[str, ...] = (
    "Internal shared storage",
    "Internal storage",
    "Internal Storage",
    "Phone storage",
    "Phone",
    "Card",
    "SD card",
    "内部存储设备",
    "内部存储",
    "手机存储",
)


@dataclass(frozen=True)
class PhoneRecording:
    source: Path
    size: int
    mtime: float


@dataclass
class PhoneDeviceInfo:
    mount_path: Path
    display_name: str
    vendor: str
    vendor_label_key: str
    recordings: list[PhoneRecording] = field(default_factory=list)


@dataclass
class PhoneImportItem:
    source: PhoneRecording
    destination: Path


@dataclass
class PhoneImportPlan:
    device: PhoneDeviceInfo
    to_import: list[PhoneImportItem]
    skipped_existing: int
    total_on_phone: int


@dataclass
class PhoneImportResult:
    imported: int
    skipped: int
    failed: int
    deleted_from_phone: int
    first_destination_dir: Path | None = None
    last_destination_dir: Path | None = None


def _safe_iterdir(path: Path) -> list[Path]:
    try:
        return list(path.iterdir())
    except OSError as exc:
        logger.debug("Skipping unreadable directory %s: %s", path, exc)
        return []


def _safe_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _is_mtp_like_mount(path: Path) -> bool:
    name = path.name.lower()
    return any(name.startswith(prefix) or prefix in name for prefix in MTP_MOUNT_PREFIXES)


def _iter_mount_roots() -> list[Path]:
    roots: list[Path] = []
    uid = os.getuid()
    gvfs = Path(f"/run/user/{uid}/gvfs")
    if _safe_is_dir(gvfs):
        roots.extend(entry for entry in _safe_iterdir(gvfs) if _safe_is_dir(entry))
    legacy_gvfs = Path.home() / ".gvfs"
    if _safe_is_dir(legacy_gvfs):
        roots.extend(entry for entry in _safe_iterdir(legacy_gvfs) if _safe_is_dir(entry))
    for base in (Path("/media"), Path("/run/media")):
        if not _safe_is_dir(base):
            continue
        for entry in _safe_iterdir(base):
            if not _safe_is_dir(entry):
                continue
            roots.append(entry)
            for sub in _safe_iterdir(entry):
                if _safe_is_dir(sub):
                    roots.append(sub)
    # Deduplicate while preserving order; avoid resolve() on gvfs/MTP paths.
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def _iter_device_scan_roots(mount: Path) -> list[Path]:
    """Return mount path plus typical MTP storage subfolders."""
    if not _is_mtp_like_mount(mount):
        return [mount]
    storage_names = {name.casefold() for name in MTP_STORAGE_DIR_NAMES}
    storage_roots: list[Path] = []
    for child in _safe_iterdir(mount):
        if not _safe_is_dir(child):
            continue
        if child.name in MTP_STORAGE_DIR_NAMES or child.name.casefold() in storage_names:
            storage_roots.append(child)
            continue
        lowered = child.name.lower()
        if any(
            token in lowered
            for token in (
                "internal",
                "storage",
                "phone",
                "card",
                "内部",
                "存储",
                "手机",
            )
        ):
            storage_roots.append(child)
    if storage_roots:
        return storage_roots
    return [mount]


def _detect_vendor(name: str) -> tuple[str, str]:
    lowered = name.lower()
    for vendor_id, label_key, needles in VENDOR_PATTERNS:
        if any(n in lowered for n in needles):
            return vendor_id, label_key
    if "mtp" in lowered or "android" in lowered:
        return "android", "vendor_android"
    return "unknown", "vendor_unknown"


def _is_audio_file(path: Path) -> bool:
    if path.suffix.lower() not in AUDIO_SUFFIXES:
        return False
    try:
        return path.is_file()
    except OSError:
        return False


def _resolve_relative_dir(root: Path, rel: str) -> Path | None:
    """Resolve a relative path under root, matching folder names case-insensitively."""
    target = root
    for part in Path(rel).parts:
        if not _safe_is_dir(target):
            return None
        exact = target / part
        if _safe_is_dir(exact):
            target = exact
            continue
        match: Path | None = None
        lowered = part.casefold()
        for child in _safe_iterdir(target):
            if child.name.casefold() == lowered and _safe_is_dir(child):
                match = child
                break
        if match is None:
            return None
        target = match
    return target


def _walk_audio_files(
    base: Path,
    *,
    max_depth: int = 12,
    status_callback: PhoneScanStatusCallback = None,
    device_name: str = "",
) -> list[Path]:
    """Walk a directory tree using iterdir (works on gvfs/MTP; rglob often does not)."""
    found: list[Path] = []
    stack: list[tuple[Path, int]] = [(base, 0)]
    visited_dirs = 0
    while stack:
        current, depth = stack.pop()
        if depth > max_depth:
            continue
        visited_dirs += 1
        if visited_dirs == 1 or visited_dirs % 8 == 0:
            _report_status(
                status_callback,
                "dialog.phone_status_walk_dir",
                device=device_name,
                path=str(current),
                count=len(found),
            )
        for entry in _safe_iterdir(current):
            if _safe_is_dir(entry):
                stack.append((entry, depth + 1))
                continue
            if entry.suffix.lower() not in AUDIO_SUFFIXES:
                continue
            if _is_audio_file(entry):
                found.append(entry)
    return found


def _list_dir_audio_files(base: Path) -> list[Path]:
    """List audio files directly in base (no subdirectories)."""
    found: list[Path] = []
    for entry in _safe_iterdir(base):
        if _is_audio_file(entry):
            found.append(entry)
    return found


def _call_recording_dirs(vendor: str) -> tuple[str, ...]:
    if vendor == "xiaomi":
        return XIAOMI_CALL_RECORDING_DIRS
    if vendor == "apple":
        return CALL_RECORDING_DIRS + IPHONE_RECORDING_DIRS
    return CALL_RECORDING_DIRS


def _is_call_recording_path(path: Path) -> bool:
    parts = [p.lower() for p in path.parts]
    joined = "/".join(parts)
    if any(
        token in joined
        for token in (
            "call_rec",
            "callrecord",
            "call record",
            "callrecordings",
            "phonerecord",
            "/call/",
            "sounds/call",
            "recordings/call",
            "record/call",
            "recorder/call",
        )
    ):
        return True
    stem = path.stem.lower()
    return bool(re.search(r"(call|通话)", stem))


def _looks_like_call_recording(path: Path) -> bool:
    return _is_call_recording_path(path)


def _collect_from_dirs(
    root: Path,
    relative_dirs: tuple[str, ...],
    *,
    status_callback: PhoneScanStatusCallback = None,
    device_name: str = "",
) -> list[PhoneRecording]:
    found: list[PhoneRecording] = []
    for rel in relative_dirs:
        base = _resolve_relative_dir(root, rel)
        if base is None:
            continue
        _report_status(
            status_callback,
            "dialog.phone_status_scan_dir",
            device=device_name,
            path=str(base),
        )
        strict_dir = rel in STRICT_CALL_RECORDING_DIRS
        if strict_dir:
            paths = _list_dir_audio_files(base)
        else:
            paths = _walk_audio_files(
                base,
                max_depth=3,
                status_callback=status_callback,
                device_name=device_name,
            )
        for path in paths:
            if not strict_dir and not _is_call_recording_path(path):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            found.append(PhoneRecording(source=path, size=stat.st_size, mtime=stat.st_mtime))
        if paths:
            _report_status(
                status_callback,
                "dialog.phone_status_scan_dir_files",
                device=device_name,
                path=str(base),
                count=len(paths),
            )
    return found


def _fallback_scan(
    root: Path,
    max_depth: int = 8,
    *,
    status_callback: PhoneScanStatusCallback = None,
    device_name: str = "",
) -> list[PhoneRecording]:
    found: list[PhoneRecording] = []
    _report_status(
        status_callback,
        "dialog.phone_status_deep_scan_root",
        device=device_name,
        path=str(root),
    )

    def walk(current: Path, depth: int) -> None:
        if depth > max_depth:
            return
        for entry in _safe_iterdir(current):
            if _safe_is_dir(entry):
                walk(entry, depth + 1)
            elif _is_audio_file(entry) and _looks_like_call_recording(entry):
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                found.append(
                    PhoneRecording(source=entry, size=stat.st_size, mtime=stat.st_mtime)
                )

    walk(root, 0)
    return found


def _scan_device_recordings(
    root: Path,
    vendor: str,
    *,
    deep_scan: bool = False,
    status_callback: PhoneScanStatusCallback = None,
    device_name: str = "",
) -> list[PhoneRecording]:
    dirs = _call_recording_dirs(vendor)
    recordings: list[PhoneRecording] = []
    scan_roots = _iter_device_scan_roots(root)
    for scan_root in scan_roots:
        _report_status(
            status_callback,
            "dialog.phone_status_scan_root",
            device=device_name,
            path=str(scan_root),
        )
        recordings.extend(
            _collect_from_dirs(
                scan_root,
                dirs,
                status_callback=status_callback,
                device_name=device_name,
            )
        )
    if not recordings and deep_scan:
        _report_status(
            status_callback,
            "dialog.phone_status_deep_scan",
            device=device_name,
        )
        for scan_root in scan_roots:
            recordings.extend(
                _fallback_scan(
                    scan_root,
                    status_callback=status_callback,
                    device_name=device_name,
                )
            )
    by_path: dict[str, PhoneRecording] = {}
    for rec in recordings:
        by_path[str(rec.source)] = rec
    result = sorted(by_path.values(), key=lambda r: r.mtime, reverse=True)
    _report_status(
        status_callback,
        "dialog.phone_status_device_done",
        device=device_name,
        count=len(result),
        deep="yes" if deep_scan else "no",
    )
    return result


def _device_display_name(mount: Path) -> str:
    name = mount.name
    if name.startswith("mtp:") or "mtp:" in name.lower():
        name = re.sub(r"^mtp:/*", "", name, flags=re.IGNORECASE)
        name = re.sub(r"^host=", "", name, flags=re.IGNORECASE)
    name = unquote(name.replace("_", " "))
    name = name.replace("%20", " ").rstrip("/")
    return name.strip() or str(mount)


def _is_phone_like_mount(name: str, mount: Path) -> bool:
    lowered = name.lower()
    if any(
        skip in lowered
        for skip in ("network", "sftp", "dav", "cifs", "ftp", "webdav", "computer")
    ):
        return False
    vendor, _label = _detect_vendor(name)
    if vendor != "unknown":
        return True
    if _is_mtp_like_mount(mount):
        return True
    return any(token in lowered for token in ("mtp", "android", "gphoto2", "ptp", "afc"))


def _probe_mount(
    mount: Path,
    *,
    scan_recordings: bool = True,
    deep_scan: bool = False,
) -> PhoneDeviceInfo | None:
    name = _device_display_name(mount)
    if not _is_phone_like_mount(name, mount):
        return None
    vendor, label_key = _detect_vendor(name)
    recordings: list[PhoneRecording] = []
    if scan_recordings:
        try:
            recordings = _scan_device_recordings(mount, vendor, deep_scan=deep_scan)
        except OSError as exc:
            logger.debug("Could not scan mount %s: %s", mount, exc)
    return PhoneDeviceInfo(
        mount_path=mount,
        display_name=name,
        vendor=vendor,
        vendor_label_key=label_key,
        recordings=recordings,
    )


def rescan_device_recordings(device: PhoneDeviceInfo) -> PhoneDeviceInfo:
    return scan_device_recordings(device, deep_scan=False)


def discover_phone_mounts(
    *,
    status_callback: PhoneScanStatusCallback = None,
) -> list[PhoneDeviceInfo]:
    """List connected phone mounts without scanning recordings."""
    devices: list[PhoneDeviceInfo] = []
    _report_status(status_callback, "dialog.phone_status_scanning_mounts")
    roots = _iter_mount_roots()
    _report_status(
        status_callback,
        "dialog.phone_status_mount_candidates",
        count=len(roots),
    )
    for index, mount in enumerate(roots, start=1):
        _report_status(
            status_callback,
            "dialog.phone_status_checking_mount",
            current=index,
            total=len(roots),
            path=str(mount),
        )
        try:
            device = _probe_mount(mount, scan_recordings=False)
        except OSError as exc:
            logger.debug("Skipping mount %s: %s", mount, exc)
            _report_status(
                status_callback,
                "dialog.phone_status_mount_skip",
                path=str(mount),
                error=str(exc),
            )
            continue
        if device is not None:
            _report_status(
                status_callback,
                "dialog.phone_status_found_device",
                name=device.display_name,
                path=str(mount),
            )
            devices.append(device)
    _report_status(
        status_callback,
        "dialog.phone_status_found_devices",
        count=len(devices),
    )
    return devices


def scan_device_recordings(
    device: PhoneDeviceInfo,
    *,
    deep_scan: bool = False,
    status_callback: PhoneScanStatusCallback = None,
) -> PhoneDeviceInfo:
    _report_status(
        status_callback,
        "dialog.phone_status_scan_device",
        name=device.display_name,
        path=str(device.mount_path),
    )
    recordings = _scan_device_recordings(
        device.mount_path,
        device.vendor,
        deep_scan=deep_scan,
        status_callback=status_callback,
        device_name=device.display_name,
    )
    if not recordings and not deep_scan:
        _report_status(
            status_callback,
            "dialog.phone_status_deep_scan",
            device=device.display_name,
        )
        recordings = _scan_device_recordings(
            device.mount_path,
            device.vendor,
            deep_scan=True,
            status_callback=status_callback,
            device_name=device.display_name,
        )
    if not recordings and _is_mtp_like_mount(device.mount_path):
        _report_status(
            status_callback,
            "dialog.phone_status_mtp_retry",
            device=device.display_name,
        )
        time.sleep(1.5)
        recordings = _scan_device_recordings(
            device.mount_path,
            device.vendor,
            deep_scan=True,
            status_callback=status_callback,
            device_name=device.display_name,
        )
    device.recordings = recordings
    return device


def discover_phone_devices(*, deep_scan: bool = False) -> list[PhoneDeviceInfo]:
    devices: list[PhoneDeviceInfo] = []
    for mount in _iter_mount_roots():
        try:
            device = _probe_mount(mount, scan_recordings=True, deep_scan=deep_scan)
        except OSError as exc:
            logger.debug("Skipping mount %s: %s", mount, exc)
            continue
        if device is not None:
            devices.append(device)
    return devices


def destination_for_recording(recordings_root: Path, recording: PhoneRecording) -> Path:
    ts = datetime.fromtimestamp(recording.mtime)
    month_dir = recordings_root / str(ts.year) / f"{ts.year}-{ts.month:02d}"
    month_dir.mkdir(parents=True, exist_ok=True)
    return month_dir / recording.source.name


def plan_phone_import(
    device: PhoneDeviceInfo,
    recordings_root: Path,
) -> PhoneImportPlan:
    recordings_root = recordings_root.expanduser()
    recordings_root.mkdir(parents=True, exist_ok=True)
    to_import: list[PhoneImportItem] = []
    skipped = 0
    for rec in device.recordings:
        dest = destination_for_recording(recordings_root, rec)
        if dest.is_file():
            skipped += 1
            continue
        to_import.append(PhoneImportItem(source=rec, destination=dest))
    return PhoneImportPlan(
        device=device,
        to_import=to_import,
        skipped_existing=skipped,
        total_on_phone=len(device.recordings),
    )


def run_phone_import(
    plan: PhoneImportPlan,
    *,
    delete_from_phone: bool = False,
    progress_callback=None,
) -> PhoneImportResult:
    imported = 0
    skipped = plan.skipped_existing
    failed = 0
    deleted = 0
    first_dest_dir: Path | None = None
    last_dest_dir: Path | None = None
    total = len(plan.to_import)

    for index, item in enumerate(plan.to_import, start=1):
        src = item.source.source
        dest = item.destination
        if dest.is_file():
            skipped += 1
            if progress_callback:
                progress_callback(index, total, src.name, skipped=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if delete_from_phone:
                shutil.move(str(src), str(dest))
                deleted += 1
            else:
                shutil.copy2(str(src), str(dest))
            imported += 1
            if first_dest_dir is None:
                first_dest_dir = dest.parent
            last_dest_dir = dest.parent
        except OSError:
            failed += 1
        if progress_callback:
            progress_callback(index, total, src.name, skipped=False)

    return PhoneImportResult(
        imported=imported,
        skipped=skipped,
        failed=failed,
        deleted_from_phone=deleted,
        first_destination_dir=first_dest_dir,
        last_destination_dir=last_dest_dir,
    )
