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
- **人数** min–max（默认 2–2，适合双人电话）
- **刷新模型**：下次转换时从 ModelScope 重新检查/下载（默认走本地 cache + mmap）
- `[Convert]` 与 `Auto Convert`、可选日志面板
- 右侧：标题、时间/时长、列表或气泡视图；头像、说话人资料、「这是我」
- 底部状态栏显示转换阶段与进度
- 文件列表：`Delete` 删除选中项；`Ctrl+A` 全选

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

## 录音文件名（各品牌）

不同手机的通话录音命名规则不同。wav2chat 会从**文件名**解析联系人、号码与录音时间，用于 GUI 列表标题与时间排序（解析失败则回退为文件修改时间）。

| 品牌 | 常见格式 | 示例 |
|------|----------|------|
| **iPhone（iOS）** | `通话录音-日期-时间` | `通话录音-20260610-173005.m4a` |
| **小米 / Redmi** | `号码_日期_时间` 或 `姓名_紧凑时间` | `13800138000_20260610_173000.mp3`、`李经理_20260610173000.mp3` |
| **华为 / 荣耀** | `姓名_日期_时间`（带连字符） | `张三_2026-06-10_17-30-22.mp3` |
| **OPPO / 一加** | `REC_号码_紧凑时间` | `REC_13800138000_20260610173000.mp3` |
| **vivo / iQOO** | `号码_紧凑时间` | `13800138000_20260610173000.mp3` |
| **三星** | `通话录音_日期_时间` | `通话录音_20260610_173000.mp3` |
| **通用** | `姓名(号码)_时间` | `常汉杰(15967387860)_20230714151024.mp3` |

GUI 中显示为「姓名 (号码)」或号码；带时间戳的文件按录音时间排序。实现见 `filename_meta.py`。

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
  "primary_speaker": 1,
  "speakers": [
    { "name": "spk0", "role": "对方", "gender": "", "avatar": "👦" },
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

`segments[].speaker` 为 **speakers 数组的下标**（整数）。旧版 JSON（字符串 `speaker`、每段 `role`）打开时会自动迁移；批量重写可用 `jsonfix *.json`。

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
| `--refresh-models` | 从 ModelScope 刷新模型（默认：本地 cache + mmap） |
| `-k, --keep-temp` | 保留中间 wav |
| `-v, --verbose` | 调试输出 |
| `-q, --quiet` | 仅显示错误 |
| `-g, --gui` | 打开桌面 GUI |
| `--ui-lang` | 界面语言：`en`、`zh`、`ja`、`ko` |
| `--version` | 显示版本与依赖信息 |

## 处理流程

```text
音频文件
  → ffmpeg 转 mono / 16 kHz / wav
  → FunASR 长音频流水线：
      1. fsmn-vad — 检测语音段
      2. paraformer-zh — 分段识别
      3. ct-punc — 标点恢复
      4. cam++ — 说话人分离（嵌入 + 聚类）
  → txt / json
```

这不是「只跑一个 ASR」，标点与说话人分离会显著增加计算量，CPU 上尤其明显。

## 性能与调优

### 为什么慢？

| 阶段 | 做什么 | 大致耗时 |
|------|--------|----------|
| **加载模型** | 四个模型（ASR、VAD、标点、说话人）读入内存 | 同一会话首次约 10–40 s；已加载则跳过 |
| **规范化** | ffmpeg → mono 16 kHz | 通常数秒 |
| **转写** | 全段 VAD + 识别 + 标点 + 分离 | CPU 上常见 **0.2–1.0 倍实时**（10 分钟音频约 2–10 分钟）；GPU 快得多 |

**CPU 上** FunASR 会关闭动态批处理，VAD 切段后基本逐段推理，长电话会很慢——这是 FunASR 的行为，不是 wav2chat 额外开销。

**GUI 进度：** 状态栏如 `[1/1] 文件 — 语音识别 (25%)` 可能每几秒涨一点（心跳），不代表 FunASR 的细粒度进度。请开日志或 `-v` 查看 `Transcribing …` 及 FunASR 耗时行。模型加载阶段会显示「正在加载 FunASR 模型…」，与转写阶段分开。

### 模型加载（cache / 刷新）

**首次运行：** 从 ModelScope 下载 paraformer-zh、fsmn-vad、ct-punc、cam++ 到本地 cache（常见路径 `~/.cache/modelscope/`），需磁盘与网络，每个版本一次。

**之后默认：**

- 使用 **本地 cache 路径**，跳过 hub 更新检查（`disable_update=True`）
- 权重读取启用 **`torch.load(…, mmap=True)`**（在 PyTorch 支持时）
- GUI/CLI **同一会话只加载一次** 模型，第二次转换不再读盘
- **jieba**（标点模型依赖）持久化 cache：`~/.cache/wav2chat/jieba/`（或 `$XDG_CACHE_HOME/wav2chat/jieba/`），仅在 jieba 词典或版本变化时 rebuild

**强制刷新**（cache 损坏、需要拉新模型）：

```bash
wav2chat --refresh-models call.m4a
```

或在 GUI 勾选 **刷新模型** 再点转换（刷新完成后自动取消勾选）。

手动清除 jieba cache：`rm -rf ~/.cache/wav2chat/jieba/`

查看环境：`wav2chat --version`

### 速度与质量

**当前可调**（CLI / GUI）：

| 参数 | 速度 | 质量 | 说明 |
|------|------|------|------|
| **GPU / CPU** | GPU 常快 **5–20 倍** | 相近 | 安装 CUDA 版 PyTorch；FunASR 自动用 `cuda:0` |
| **`--min-speakers` / `--max-speakers`** | 范围收窄（如 2–2）加快聚类 | 已知双人电话更稳 | GUI 人数行，默认 2–2 |
| **`--refresh-models`** | 更慢（检查 hub + 全量加载） | 刷新后相同 | 仅在 cache 异常时使用 |
| **`--verbose`** | 不变 | — | 显示 FunASR 加载/转写日志与 RTF |

**wav2chat 内写死、尚未暴露 CLI**（FunASR `generate()` 参数）：

| 参数 | 当前值 | 作用 |
|------|--------|------|
| `batch_size_s` | `300` | GPU 上 ASR 动态批时长上限（秒）；CPU 受 FunASR 限制 |
| `batch_size_threshold_s` | FunASR 默认 `60` | 短于该阈值的 VAD 段可能合并批处理 |
| `vad_kwargs.max_single_segment_time` | FunASR 默认约 60000 ms | VAD 单段上限；越大段越少、略快，可能模糊说话人边界 |
| 模型链 | paraformer + vad + punc + cam++ | 关闭说话人可大幅加速，但 wav2chat 始终开启分离 |
| `ncpu` | FunASR 默认 `4` | FunASR 内部 CPU 线程数 |

### 实用建议

1. **尽量用 GPU** — 长录音收益最大。
2. **电话：** `--min-speakers 2 --max-speakers 2`（GUI 默认）。
3. **同一会话：** 保持 GUI 不关，首次转换后模型常驻内存。
4. **不要常开「刷新模型」**，除非 cache 坏了或要更新上游模型。
5. **长任务：** 打开日志或 `-v`；CPU 转写可能跑很多分钟，百分比仅作参考，确认阶段是 **语音识别** 而非 **加载模型**。
6. **说话人不对：** 调整人数与 `--role`；`spk0`/`spk1` 顺序不一定对应真实身份。

后续可能增加 CLI/GUI 预设（如 `--fast` 跳过分离、`--device`、`--batch-size-s`）；集成入口见 `funasr_backend.py`。

## 常见问题

### ffmpeg: command not found

先安装 ffmpeg：

```bash
sudo apt install -y ffmpeg
```

### 首次运行很慢

FunASR 首次会从 ModelScope 下载四个模型；之后从本地 cache + mmap 加载。详见 [性能与调优](#性能与调优)。

### CUDA / CPU

若已安装带 CUDA 的 PyTorch，FunASR 会尝试使用 GPU；否则使用 CPU。CPU 上长录音明显更慢，完整分离流水线常见 **0.2–1.0 倍实时**。详见 [性能与调优](#性能与调优)。

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
  filename_meta.py
  funasr_backend.py
  jieba_cache.py
  jsonfix.py
  speaker_ui.py
  i18n.py
  render.py
  models.py
```

## 许可证

Copyright (C) 2026 Lenik <wav2chat@bodz.net>

采用 GNU Affero General Public License v3 或更高版本。完整条款（含补充限制）见 [LICENSE](LICENSE)。
