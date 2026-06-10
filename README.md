# wav2chat

Convert phone recordings, meeting recordings, or ordinary audio files into **chat-style text segmented by speaker**.

Stack: Python 3.10+, ffmpeg, FunASR (ModelScope AutoModel).

[中文文档](README-zh.md)

## Features

- Common audio formats: `.wav`, `.mp3`, `.m4a`, `.amr`, `.aac`, `.flac`, `.ogg`
- Automatic VAD, punctuation restoration, and speaker diarization
- Output as `.txt` and `.json`
- Batch processing for directories
- `--role` maps `spk0` / `spk1` to readable display names
- Desktop GUI with drag-and-drop, file queue, and list/bubble chat views

The first release targets **Chinese phone/meeting recordings** only. No database or web service.

## Dependencies

### System: ffmpeg

Debian / Ubuntu:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

Verify:

```bash
ffmpeg -version
```

### Python

- Python 3.10+
- funasr
- modelscope
- torch

On first run, models are downloaded from ModelScope. This can take a while and requires sufficient disk space.

## Installation

Install in development mode from the project directory:

```bash
pip install -e .
```

Then:

```bash
wav2chat --help
```

## Basic usage

Convert a single file; by default a same-name `.txt` is created:

```bash
wav2chat call.m4a
```

Specify the txt output path:

```bash
wav2chat call.m4a -o call.txt
```

Also write json:

```bash
wav2chat call.m4a -o call.txt --json call.json
```

Limit speaker count (useful for two-party phone calls):

```bash
wav2chat call.wav --min-speakers 2 --max-speakers 2
```

Map speaker display names:

```bash
wav2chat call.m4a -o call.txt --json call.json --role spk0=Me --role spk1=Other
```

Keep the normalized intermediate wav from ffmpeg:

```bash
wav2chat call.m4a --keep-temp --verbose
```

## GUI

The GUI uses **wxPython** via the system package (there are no Linux pip wheels).

Debian / Ubuntu:

```bash
sudo apt install python3-wxgtk4.0
pip install -e .
```

If you use a virtualenv, it must see system packages:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
wav2chat -g
```

Or use `make install-gui` (installs the apt package and wav2chat).

The GUI provides:

- File menu: open waveform, open saved chat session (`.json`), exit
- Left panel: audio path selector, droppable file queue with status markers
  (`?` unconverted, spinner while converting, `=` converted)
- Speaker count (`min`–`max`, default 2–2 for phone calls)
- **Refresh models** checkbox (re-download from ModelScope on next convert; default uses local cache)
- Convert button and Auto Convert checkbox
- Right panel: session title, timestamp/duration, list or bubble chat view
- Status bar and optional log panel for conversion progress
- File list: `Delete` removes selected queue items; `Ctrl+A` selects all

You can pass the same options as the CLI, for example:

```bash
wav2chat -g -n 2 -m 2 -r spk0=Me -r spk1=Other
```

## Batch processing

Scan a directory for supported audio files and write one `.txt` per file:

```bash
wav2chat ./calls --batch -o ./texts
```

With `--json`, same-name `.json` files are written to the json output directory:

```bash
wav2chat ./calls --batch -o ./texts --json ./jsons
```

A failure on one file does not stop the batch. Errors go to stderr and are summarized at the end.

## Recording filenames (by phone brand)

Call-recording naming varies by manufacturer. wav2chat parses **filenames** for contact name, phone number, and recording time (used in the GUI list title and sort order; falls back to file mtime if parsing fails).

| Brand | Typical pattern | Example |
|-------|-----------------|--------|
| **iPhone (iOS)** | `通话录音-date-time` | `通话录音-20260610-173005.m4a` |
| **Xiaomi / Redmi** | `number_date_time` or `name_compact-time` | `13800138000_20260610_173000.mp3`, `李经理_20260610173000.mp3` |
| **Huawei / Honor** | `name_date_time` (dashed) | `张三_2026-06-10_17-30-22.mp3` |
| **OPPO / OnePlus** | `REC_number_compact-time` | `REC_13800138000_20260610173000.mp3` |
| **vivo / iQOO** | `number_compact-time` | `13800138000_20260610173000.mp3` |
| **Samsung** | `通话录音_date_time` | `通话录音_20260610_173000.mp3` |
| **Generic** | `name(phone)_timestamp` | `常汉杰(15967387860)_20230714151024.mp3` |

The GUI shows `Name (phone)` or the number alone. See `filename_meta.py` for parsing rules.

## Output examples

### txt

```text
# source: call_20260609_138xxxx.m4a

[00:00:01.200 - 00:00:03.800] Me: 喂，你好。
[00:00:04.100 - 00:00:07.600] Other: 你好，我想问一下续贷的事情。
```

Without `--role`, speakers appear as `spk0`, `spk1`, etc.

### json

```json
{
  "source": "call.m4a",
  "duration": 7.6,
  "primary_speaker": 1,
  "speakers": [
    { "name": "spk0", "role": "Other", "gender": "", "avatar": "👦" },
    { "name": "spk1", "role": "me", "gender": "", "avatar": "👧" }
  ],
  "segments": [
    {
      "start": 1.2,
      "end": 3.8,
      "speaker": 0,
      "text": "喂，你好。"
    },
    {
      "start": 4.1,
      "end": 7.6,
      "speaker": 1,
      "text": "你好，我想问一下续贷的事情。"
    }
  ]
}
```

Legacy JSON (string `speaker` / per-segment `role`) is migrated automatically when loaded. Use `jsonfix *.json` to rewrite files to the new format.

## CLI options

| Option | Description |
|------|-------------|
| `input` | Input file or directory |
| `-o, --output` | Output txt file or batch output directory |
| `--json` | Output json file or batch output directory |
| `-b, --batch` | Process a directory in batch mode |
| `-e, --backend` | Default: `funasr` |
| `-l, --lang` | Default: `zh` |
| `-n, --min-speakers` | Minimum number of speakers |
| `-m, --max-speakers` | Maximum number of speakers |
| `-r, --role SPK=NAME` | Speaker display name; repeatable |
| `--refresh-models` | Re-check ModelScope and reload models (default: local cache + mmap) |
| `-k, --keep-temp` | Keep intermediate wav |
| `-v, --verbose` | Debug output |
| `-q, --quiet` | Suppress non-error output |
| `-g, --gui` | Open the desktop GUI |
| `--ui-lang` | GUI language: `en`, `zh`, `ja`, `ko` |
| `--version` | Show version and dependency info |

## Pipeline

```text
audio file
  → ffmpeg to mono / 16 kHz / wav
  → FunASR long-audio pipeline:
      1. fsmn-vad — detect speech segments
      2. paraformer-zh — speech recognition per segment
      3. ct-punc — punctuation restoration
      4. cam++ — speaker diarization (embeddings + clustering)
  → txt / json
```

This is **not** a single ASR pass. Diarization and punctuation add significant compute, especially on CPU.

## Performance and tuning

### Why does it take so long?

| Phase | What happens | Typical cost |
|-------|----------------|----------------|
| **Model load** | Four models (ASR, VAD, punctuation, speaker) loaded into memory | ~10–40 s first time in a session; skipped if already loaded |
| **Normalize** | ffmpeg → mono 16 kHz WAV | Usually seconds |
| **Transcribe** | VAD + ASR + punctuation + speaker separation on full audio | Often **0.2–1.0× realtime** on CPU (10 min audio → ~2–10 min); much faster on GPU |

On **CPU**, FunASR disables dynamic batching and processes VAD segments largely one-by-one, which makes long phone calls slow. That is FunASR behaviour, not extra overhead from wav2chat.

**Progress in the GUI:** status like `[1/1] file — Transcribing (25%)` may advance every few seconds even when FunASR does not report fine-grained progress (heartbeat). Use `-v` / **Show log** to see `Transcribing …` and FunASR timing lines. Model load shows `Loading FunASR models…` before transcribe starts.

### Model loading (cache / refresh)

**First ever run:** ModelScope downloads paraformer-zh, fsmn-vad, ct-punc, and cam++ to the ModelScope cache (often under `~/.cache/modelscope/`). Needs disk space and network; happens once per model version.

**Default afterwards:**

- wav2chat resolves **local cache paths** and skips hub update checks (`disable_update=True`)
- Checkpoints are read with **`torch.load(…, mmap=True)`** where supported
- The GUI/CLI keeps one **in-memory model** for the session — a second conversion in the same window does not reload weights
- **jieba** (used by the punctuation model) uses a persistent cache at `~/.cache/wav2chat/jieba/` (or `$XDG_CACHE_HOME/wav2chat/jieba/`). The cache is rebuilt only when the jieba dictionary or package version changes

**Force refresh** (broken cache, new upstream model):

```bash
wav2chat --refresh-models call.m4a
```

Or check **Refresh models** in the GUI before Convert (auto-unchecks after one reload).

Clear jieba cache manually: `rm -rf ~/.cache/wav2chat/jieba/`

Check environment: `wav2chat --version`

### Speed vs quality

Parameters you can control **today** (CLI / GUI):

| Parameter | Speed | Quality / accuracy | Notes |
|-----------|-------|-------------------|--------|
| **GPU vs CPU** | GPU often **5–20× faster** | Similar | Install CUDA-enabled PyTorch; FunASR picks `cuda:0` when available |
| **`--min-speakers` / `--max-speakers`** | Narrow range (e.g. `2`–`2`) speeds clustering | Better for known two-party calls | GUI: speaker count row, default 2–2 |
| **`--refresh-models`** | Slower (hub check + full reload) | Same after refresh | Use only when cache is stale |
| **`--verbose`** | No change | — | Shows FunASR load/transcribe logs and RTF hints |

**Hardcoded in wav2chat today** (FunASR `generate()` kwargs — not yet CLI flags):

| Parameter | Current value | Effect |
|-----------|---------------|--------|
| `batch_size_s` | `300` | Max batch duration (seconds) for ASR on GPU; CPU batching is limited by FunASR |
| `batch_size_threshold_s` | FunASR default `60` | Segments shorter than this may be batched together |
| `vad_kwargs.max_single_segment_time` | FunASR default ~60000 ms | Max VAD segment length; larger → fewer splits, slightly faster, may blur speaker boundaries |
| Models | paraformer-zh + fsmn-vad + ct-punc + cam++ | Full pipeline; skipping speaker model would be much faster but wav2chat always enables diarization |
| `ncpu` | FunASR default `4` | CPU threads inside FunASR |

### Practical recommendations

1. **Use a GPU** when possible — largest win for long recordings.
2. **Phone calls:** set `--min-speakers 2 --max-speakers 2` (GUI default).
3. **Same session:** keep the GUI open; models stay loaded after the first convert.
4. **Do not use Refresh models** unless you need to re-download or fix a corrupt cache.
5. **Long jobs:** enable log panel or `-v`; ignore coarse percentage if CPU transcribe runs for many minutes — check that status says **Transcribing**, not **Loading models**.
6. **Wrong speakers:** tune speaker count and `--role`; diarization order may not match real identities.

Future CLI/GUI presets (e.g. `--fast` without diarization, `--device`, `--batch-size-s`) may be added; see `funasr_backend.py` for the integration point.

## FAQ

### ffmpeg: command not found

Install ffmpeg:

```bash
sudo apt install -y ffmpeg
```

### First run is slow

FunASR downloads four models from ModelScope on first use. Later runs load from the local ModelScope cache with mmap. See [Performance and tuning](#performance-and-tuning).

### CUDA / CPU

If PyTorch with CUDA is installed, FunASR will try to use the GPU; otherwise it runs on CPU. Long recordings are much slower on CPU — often 0.2–1.0× realtime for the full diarization pipeline. See [Performance and tuning](#performance-and-tuning).

### Wrong speaker labels

- For two-party phone calls, try: `--min-speakers 2 --max-speakers 2`
- Map display names with `--role spk0=Me --role spk1=Other`; FunASR's `spk0`/`spk1` order may not match real identities

### Empty batch directory

Make sure the directory contains files with supported extensions: `.wav`, `.mp3`, `.m4a`, `.amr`, `.aac`, `.flac`, `.ogg`.

### FunASR import failed / ModuleNotFoundError: torchaudio

FunASR requires `torchaudio`, which pip may not install automatically. Reinstall the project:

```bash
pip install -e .
```

Or install it directly:

```bash
pip install torchaudio
```

### FunASR returns empty results

Check whether the audio is too short, mostly silent, or whether ffmpeg conversion succeeded. Use `--verbose` to debug.

## Development

Project layout:

```text
wav2chat/
  pyproject.toml
  LICENSE
  README.md
  README-zh.md
  __init__.py
  cli.py
  gui.py
  pipeline.py
  audio.py
  filename_meta.py
  funasr_backend.py
  jieba_cache.py
  jsonfix.py
  speaker_ui.py
  i18n.py
  render.py
  models.py
```

## License

Copyright (C) 2026 Lenik <wav2chat@bodz.net>

Licensed under the GNU Affero General Public License v3 or later. See [LICENSE](LICENSE) for the full text, including supplemental terms.
