# Phone import — how it works

wav2chat imports **call recordings** from a phone connected to the desktop over USB. On Linux this usually means the phone is exposed as an **MTP** (Media Transfer Protocol) volume through **gvfs**, not as a normal block device.

Implementation: `phone_import.py` (scan/copy) and `phone_import_dialog.py` (GUI).

---

## Overview

```
Phone (USB, file-transfer mode)
    → gvfs mount (/run/user/UID/gvfs/mtp:…)
    → discover_phone_mounts()        # find phone-like mounts
    → scan_device_recordings()       # list call-recording files
    → plan_phone_import()            # skip files already on disk
    → run_phone_import()             # copy or move into Recordings Location
```

The app does **not** use ADB or vendor PC suites. It only reads files visible through the desktop’s MTP/gvfs layer.

---

## Mount discovery

`discover_phone_mounts()` walks these locations:

| Path | Notes |
|------|--------|
| `/run/user/<uid>/gvfs/` | Primary on modern GNOME/KDE |
| `~/.gvfs/` | Legacy gvfs |
| `/media/`, `/run/media/` | Some udisks / direct mounts |

A mount is treated as a phone when its name or path suggests MTP/Android/iPhone (e.g. `mtp:host=…`, “Xiaomi”, “iPhone”). Network/SFTP/WebDAV mounts are ignored.

**Requirements on the phone**

- USB connected
- Mode: **File transfer / MTP** (not “charge only”)
- Screen unlocked if the phone asks for permission

**Requirements on the desktop**

- gvfs + MTP backend (typical on GNOME/KDE)
- Phone appears under gvfs; you can open it in the file manager

---

## Vendor detection

Vendor is inferred from the **mount display name** (substring match, case-insensitive):

| Vendor ID | Matched keywords (examples) |
|-----------|-----------------------------|
| `xiaomi` | xiaomi, redmi, poco, mi |
| `apple` | iphone, apple, ipad |
| `huawei` | huawei, honor |
| `oppo` | oppo, realme, oneplus |
| `vivo` | vivo, iqoo |
| `samsung` | samsung, galaxy |
| `android` | generic MTP / android in name |
| `unknown` | fallback |

Vendor chooses **which folders to scan** (see below).

---

## Where call recordings live

Scan roots under an MTP device:

1. Prefer **internal storage** child folders (`Internal shared storage`, `内部存储`, etc.) when present — avoids scanning the MTP root twice.
2. For each root, try known **relative paths** below.

### Xiaomi / Redmi / POCO (MIUI / HyperOS)

| Path (under storage root) | Scan mode |
|---------------------------|-----------|
| `MIUI/sound_recorder/call_rec` | **Strict** — only audio files **directly in this folder** (no subfolder walk) |

MIUI stores automatic call recordings here. Regular voice memos live in other `sound_recorder` subfolders and are **not** scanned.

Typical full path on device:

`Internal shared storage/MIUI/sound_recorder/call_rec/*.mp3`

### Huawei / Honor

| Path | Scan mode |
|------|-----------|
| `Sounds/CallRecord` | Strict |
| `Sounds/Call` | Strict |
| (also generic Android paths below) | Filtered |

### OPPO / Realme / OnePlus, Vivo / iQOO, Samsung, generic Android

Uses the shared list:

| Relative path | Scan mode |
|---------------|-----------|
| `Sounds/CallRecord`, `Sounds/Call` | Strict |
| `Recordings/Call`, `Record/Call` | Strict |
| `CallRecordings`, `Call Recording`, `PhoneRecord` | Strict |
| `Recorder/Call` | Strict |
| `Music/Call recordings`, `Music/CallRecordings` | Walk + filename/path filter |

**Strict directory:** every audio file in that folder counts as a call recording.

**Non-strict directory:** only files whose path or filename looks like a call recording (path contains `call_rec`, `callrecord`, `phonerecord`, `/call/`, etc., or filename matches `call` / `通话`).

Supported audio extensions: `.mp3`, `.m4a`, `.wav`, `.aac`, `.amr`, `.3gp`, `.ogg`, `.flac`, `.opus`.

### Apple iPhone / iPad

MTP exposure is limited. Extra paths:

| Path | Notes |
|------|--------|
| `Recordings` | May appear on some setups |
| `Voice Memos` | Voice Memos app |
| `Internal Storage/Recordings` | Variant layout |

**iPhone caveat:** many iOS versions do **not** export call recordings or Voice Memos cleanly over MTP. Built-in Phone call recording (where available) may not be visible to Linux at all. Import works best when recordings are already copied to Files or a visible folder.

---

## Scan pipeline

### Phase 1 — Find devices (fast)

`discover_phone_mounts()` lists phone-like mounts **without** reading recording folders.

### Phase 2 — Scan recordings per device

`scan_device_recordings()`:

1. Resolve vendor-specific directory list.
2. For each storage root + directory, resolve path segments **case-insensitively** (MTP folder names vary).
3. List or walk audio files (`iterdir`-based; `rglob` is unreliable on gvfs).
4. Deduplicate by full path, sort by modification time (newest first).

### Deep scan (fallback)

If **no** recordings are found in known folders:

1. Retry with `deep_scan=True`: walk storage up to depth 8 and keep files matching call-recording path/name heuristics.
2. On MTP mounts, an extra retry after a short delay handles slow gvfs enumeration.

Deep scan is slower and may pick up false positives on some devices; normal scan is preferred.

---

## Import plan and copy

**Recordings Location** (Settings) is the destination root, e.g.:

```
~/Documents/Recordings/2025/2025-06/recording.mp3
```

`plan_phone_import()`:

- Destination: `Recordings/<year>/<year-MM>/<original filename>`
- Skips files that **already exist** at the destination (counts as “already imported”)

`run_phone_import()`:

- Default: **copy** (`shutil.copy2`, preserves mtime)
- Optional: **Delete from phone after import** — uses `shutil.move` (copy + delete source)

Progress is reported per file in the dialog status bar.

---

## MTP quirks (why counts or scans can look wrong)

| Issue | Mitigation in wav2chat |
|-------|-------------------------|
| gvfs `iterdir` slow or incomplete | Status callbacks; MTP retry after 1.5 s |
| Recursive walk exposes huge trees | Xiaomi `call_rec`: **non-recursive** listing only |
| Duplicate scan at mount root + internal storage | Prefer internal-storage children only |
| Wrong folder matched | Strict dirs + vendor-specific short lists |
| `stat()` fails on some files | Skip file, continue scan |

If a device stores calls in a **non-standard path**, deep scan may find them; otherwise add the path to `CALL_RECORDING_DIRS` in `phone_import.py`.

---

## GUI flow (`phone_import_dialog.py`)

1. Open **File → Import from phone…** (Ctrl+I).
2. Dialog scans mounts, then each device’s call-recording folders.
3. Choose device, review **new / total** counts, optionally enable delete-after-import.
4. **Import** copies files; on success the file browser can jump to the destination month folder.

Scan details appear in the dialog **bottom status bar** only (not duplicated in the main window log stream).

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No device found | Phone in MTP mode; entry under `/run/user/$UID/gvfs/`; unlock phone |
| 0 recordings | Call recording enabled on phone; open `call_rec` (or vendor path) in file manager from PC |
| Count too high | Usually fixed by strict non-recursive scan; report device model + path if wrong |
| Import fails mid-way | Disk space; gvfs disconnect; keep USB connected until finished |

Manual check:

```bash
ls "/run/user/$(id -u)/gvfs/"
# then explore mtp:…/Internal shared storage/MIUI/sound_recorder/call_rec/
```

---

## Related settings

| Setting | File | Purpose |
|---------|------|---------|
| Recordings Location | `app_settings.py` | Import destination root |
| Delete after import | `phone_delete_after_import` | Move vs copy |
| Home breadcrumb button | Main window | Jumps browser to Recordings Location |

---

## Code map

| Function | Role |
|----------|------|
| `_iter_mount_roots()` | Find gvfs/media mount points |
| `discover_phone_mounts()` | Phone devices without file scan |
| `_detect_vendor()` | Vendor from mount name |
| `_call_recording_dirs()` | Per-vendor folder list |
| `_collect_from_dirs()` | Scan known folders |
| `_fallback_scan()` | Deep heuristic scan |
| `plan_phone_import()` | Build import queue, skip existing |
| `run_phone_import()` | Copy/move files |
