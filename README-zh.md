# wav2chat

把电话录音、会议录音或普通音频文件转换成**按说话人分段的聊天文本**。

技术栈：Python 3.10+、ffmpeg、FunASR（ModelScope AutoModel）。

[English README](README.md)

## 功能

- 支持常见音频格式：`.wav`、`.mp3`、`.m4a`、`.amr`、`.aac`、`.flac`、`.ogg`
- 自动 VAD、标点恢复、说话人分离
- 输出 `.txt` 和 `.json`
- 支持批量处理目录
- 支持 `--role` 把 `spk0` / `spk1` 映射为可读名称
- 桌面 GUI：拖放文件、转换队列、列表/气泡聊天视图

第一版仅面向 **中文电话/会议录音**，无数据库、无 Web 服务。

## 依赖

### 系统依赖：ffmpeg

Debian / Ubuntu：

```bash
sudo apt update
sudo apt install -y ffmpeg
```

验证：

```bash
ffmpeg -version
```

### Python 依赖

- Python 3.10+
- funasr
- modelscope
- torch

首次运行会从 ModelScope 下载模型，可能需要较长时间和足够磁盘空间。

## 安装

在项目目录中开发安装：

```bash
pip install -e .
```

安装后可用：

```bash
wav2chat --help
```

## 基本用法

转换单个文件，默认生成同名 `.txt`：

```bash
wav2chat call.m4a
```

指定 txt 输出路径：

```bash
wav2chat call.m4a -o call.txt
```

同时输出 json：

```bash
wav2chat call.m4a -o call.txt --json call.json
```

限制说话人数量（适合双人电话）：

```bash
wav2chat call.wav --min-speakers 2 --max-speakers 2
```

映射说话人显示名：

```bash
wav2chat call.m4a -o call.txt --json call.json --role spk0=我 --role spk1=对方
```

保留 ffmpeg 规范化后的中间 wav：

```bash
wav2chat call.m4a --keep-temp --verbose
```

## GUI

GUI 使用系统自带的 **wxPython**（Linux 上 pip 没有预编译包）。

Debian / Ubuntu：

```bash
sudo apt install python3-wxgtk4.0
pip install -e .
```

若使用 virtualenv，需启用系统 site-packages：

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
wav2chat -g
```

或直接：`make install-gui`

界面包含：

- 菜单 File：打开音频、打开聊天会话（`.json`）、退出
- 左侧：音频路径、可拖放文件队列（`?` 未转换、转换中动画、`=` 已转换）
- `[Convert]` 与 `Auto Convert`
- 右侧：标题、时间/时长、列表或气泡视图
- 底部状态栏

示例：

```bash
wav2chat -g -n 2 -m 2 -r spk0=我 -r spk1=对方
```

## 批处理

扫描目录内所有支持的音频文件，每个文件生成一个同名 `.txt`：

```bash
wav2chat ./calls --batch -o ./texts
```

若同时传入 `--json`，会在 json 输出目录（或 `--json` 指定目录）生成同名 `.json`：

```bash
wav2chat ./calls --batch -o ./texts --json ./jsons
```

单个文件失败不会中断整个批处理，错误会打印到 stderr 并在最后汇总。

## 输出示例

### txt

```text
# source: call_20260609_138xxxx.m4a

[00:00:01.200 - 00:00:03.800] 我: 喂，你好。
[00:00:04.100 - 00:00:07.600] 对方: 你好，我想问一下续贷的事情。
```

未设置 `--role` 时显示 `spk0`、`spk1` 等。

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
      "role": "我",
      "text": "喂，你好。"
    }
  ]
}
```

## CLI 参数

| 参数 | 说明 |
|------|------|
| `input` | 输入文件或目录 |
| `-o, --output` | 输出 txt 文件或批处理输出目录 |
| `--json` | 输出 json 文件或批处理输出目录 |
| `-b, --batch` | 批量处理目录 |
| `-e, --backend` | 默认 `funasr` |
| `-l, --lang` | 默认 `zh` |
| `-n, --min-speakers` | 最小说话人数 |
| `-m, --max-speakers` | 最大说话人数 |
| `-r, --role SPK=NAME` | 说话人显示名，可重复 |
| `-k, --keep-temp` | 保留中间 wav |
| `-v, --verbose` | 调试输出 |
| `-q, --quiet` | 仅显示错误 |
| `-g, --gui` | 打开桌面 GUI |

## 处理流程

```text
音频文件
  → ffmpeg 转 mono / 16 kHz / wav
  → FunASR (paraformer-zh + fsmn-vad + ct-punc + cam++)
  → txt / json
```

## 常见问题

### ffmpeg: command not found

先安装 ffmpeg：

```bash
sudo apt install -y ffmpeg
```

### 首次运行很慢

FunASR 会从 ModelScope 下载 ASR、VAD、标点、说话人分离模型，属正常现象。可使用 `--verbose` 查看进度相关日志。

### CUDA / CPU

若已安装带 CUDA 的 PyTorch，FunASR 会尝试使用 GPU；否则使用 CPU。CPU 下长录音会更慢。

### 说话人标签不对

- 电话双人场景可尝试：`--min-speakers 2 --max-speakers 2`
- 用 `--role spk0=我 --role spk1=对方` 手动映射显示名；FunASR 的 `spk0`/`spk1` 顺序不一定对应真实身份

### 批处理目录为空

确认目录中存在支持的后缀文件：`.wav`、`.mp3`、`.m4a`、`.amr`、`.aac`、`.flac`、`.ogg`。

### FunASR import failed / ModuleNotFoundError: torchaudio

FunASR 运行时需要 `torchaudio`，但 pip 有时不会自动装上。重新安装项目即可：

```bash
pip install -e .
```

或单独安装：

```bash
pip install torchaudio
```

### FunASR 返回空结果

检查音频是否过短、静音过多，或 ffmpeg 转换是否成功。可加 `--verbose` 排查。

## 开发

项目结构：

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

## 许可证

Copyright (C) 2026 Lenik <wav2chat@bodz.net>

采用 GNU Affero General Public License v3 或更高版本。完整条款（含补充限制）见 [LICENSE](LICENSE)。
