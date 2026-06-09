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
- Convert button and Auto Convert checkbox
- Right panel: session title, timestamp/duration, list or bubble chat view
- Status bar for conversion progress

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
  "segments": [
    {
      "start": 1.2,
      "end": 3.8,
      "speaker": "spk0",
      "role": "Me",
      "text": "喂，你好。"
    }
  ]
}
```

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
| `-k, --keep-temp` | Keep intermediate wav |
| `-v, --verbose` | Debug output |
| `-q, --quiet` | Suppress non-error output |
| `-g, --gui` | Open the desktop GUI |

## Pipeline

```text
audio file
  → ffmpeg to mono / 16 kHz / wav
  → FunASR (paraformer-zh + fsmn-vad + ct-punc + cam++)
  → txt / json
```

## FAQ

### ffmpeg: command not found

Install ffmpeg:

```bash
sudo apt install -y ffmpeg
```

### First run is slow

FunASR downloads ASR, VAD, punctuation, and speaker-diarization models from ModelScope on first use. This is expected. Use `--verbose` for progress-related logs.

### CUDA / CPU

If PyTorch with CUDA is installed, FunASR will try to use the GPU; otherwise it runs on CPU. Long recordings are slower on CPU.

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
  funasr_backend.py
  render.py
  models.py
```

## License

Copyright (C) 2026 Lenik <wav2chat@bodz.net>

Licensed under the GNU Affero General Public License v3 or later. See [LICENSE](LICENSE) for the full text, including supplemental terms.
