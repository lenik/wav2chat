# 手机导入 — 工作原理

[English](phone-support.md)

wav2chat 通过 USB 从连接在桌面电脑上的**手机**导入**通话录音**。在 Linux 上，手机通常通过 **gvfs** 以 **MTP**（Media Transfer Protocol）卷的形式挂载，而不是普通块设备。

实现代码：`phone_import.py`（扫描/复制）与 `phone_import_dialog.py`（GUI）。

---

## 概览

```
手机（USB，文件传输模式）
    → gvfs 挂载点 (/run/user/UID/gvfs/mtp:…)
    → discover_phone_mounts()        # 查找像手机的挂载
    → scan_device_recordings()       # 列出通话录音文件
    → plan_phone_import()            # 跳过已在磁盘上的文件
    → run_phone_import()             # 复制或移动到录音主目录
```

本程序**不使用** ADB 或厂商 PC 套件，只读取桌面 MTP/gvfs 层可见的文件。

---

## 挂载发现

`discover_phone_mounts()` 会扫描以下位置：

| 路径 | 说明 |
|------|------|
| `/run/user/<uid>/gvfs/` | 现代 GNOME/KDE 上的主要位置 |
| `~/.gvfs/` | 旧版 gvfs |
| `/media/`、`/run/media/` | 部分 udisks / 直接挂载 |

当挂载名称或路径暗示 MTP/Android/iPhone（如 `mtp:host=…`、「Xiaomi」、「iPhone」）时，视为手机。网络/SFTP/WebDAV 挂载会被忽略。

**手机端要求**

- USB 已连接
- 模式：**文件传输 / MTP**（非「仅充电」）
- 若手机提示授权，需解锁屏幕

**桌面端要求**

- gvfs + MTP 后端（GNOME/KDE 通常已具备）
- 文件管理器中能看到手机

---

## 厂商识别

根据**挂载显示名称**推断厂商（子串匹配，不区分大小写）：

| 厂商 ID | 匹配关键词（示例） |
|---------|-------------------|
| `xiaomi` | xiaomi, redmi, poco, mi |
| `apple` | iphone, apple, ipad |
| `huawei` | huawei, honor |
| `oppo` | oppo, realme, oneplus |
| `vivo` | vivo, iqoo |
| `samsung` | samsung, galaxy |
| `android` | 名称中含 MTP / android |
| `unknown` | 兜底 |

厂商决定**扫描哪些文件夹**（见下文）。

---

## 通话录音存放位置

在 MTP 设备下扫描的根目录规则：

1. 若存在**内部存储**子目录（`Internal shared storage`、`内部存储` 等），优先以其为根——避免在 MTP 根目录重复扫描。
2. 对每个根目录，尝试下列**相对路径**。

### 小米 / Redmi / POCO（MIUI / HyperOS）

| 路径（存储根下） | 扫描模式 |
|------------------|----------|
| `MIUI/sound_recorder/call_rec` | **严格** — 仅该文件夹**内直接**的音频（不递归子目录） |

MIUI 的自动通话录音在此目录。普通语音备忘录在其他 `sound_recorder` 子目录，**不会**被扫描。

设备上典型完整路径：

`Internal shared storage/MIUI/sound_recorder/call_rec/*.mp3`

### 华为 / 荣耀

| 路径 | 扫描模式 |
|------|----------|
| `Sounds/CallRecord` | 严格 |
| `Sounds/Call` | 严格 |
| （以及下方通用 Android 路径） | 过滤 |

### OPPO / Realme / OnePlus、Vivo / iQOO、Samsung、通用 Android

共用路径列表：

| 相对路径 | 扫描模式 |
|----------|----------|
| `Sounds/CallRecord`、`Sounds/Call` | 严格 |
| `Recordings/Call`、`Record/Call` | 严格 |
| `CallRecordings`、`Call Recording`、`PhoneRecord` | 严格 |
| `Recorder/Call` | 严格 |
| `Music/Call recordings`、`Music/CallRecordings` | 遍历 + 文件名/路径过滤 |

**严格目录：** 该文件夹内每个音频文件都计为通话录音。

**非严格目录：** 仅当路径或文件名像通话录音时才计入（路径含 `call_rec`、`callrecord`、`phonerecord`、`/call/` 等，或文件名匹配 `call` / `通话`）。

支持的音频扩展名：`.mp3`、`.m4a`、`.wav`、`.aac`、`.amr`、`.3gp`、`.ogg`、`.flac`、`.opus`。

### Apple iPhone / iPad

MTP 暴露能力有限，额外路径：

| 路径 | 说明 |
|------|------|
| `Recordings` | 部分系统可见 |
| `Voice Memos` | 语音备忘录 |
| `Internal Storage/Recordings` | 变体布局 |

**iPhone 注意：** 许多 iOS 版本无法通过 MTP 向 Linux 干净地导出通话录音或语音备忘录。系统自带通话录音（若可用）在 Linux 上可能完全不可见。录音已复制到「文件」或可见文件夹时，导入效果最好。

---

## 扫描流程

### 阶段 1 — 查找设备（快速）

`discover_phone_mounts()` 列出像手机的挂载，**不**读取录音文件夹。

### 阶段 2 — 按设备扫描录音

`scan_device_recordings()`：

1. 解析厂商专用目录列表。
2. 对每个存储根 + 目录，**不区分大小写**解析路径段（MTP 文件夹名因设备而异）。
3. 列出或遍历音频文件（基于 `iterdir`；gvfs 上 `rglob` 不可靠）。
4. 按完整路径去重，按修改时间排序（新的在前）。

### 深度扫描（兜底）

若在已知文件夹中**未**找到录音：

1. 以 `deep_scan=True` 重试：在存储内深度至多 8 层遍历，保留符合通话录音路径/文件名启发式的文件。
2. 在 MTP 挂载上，短暂延迟后额外重试一次，以应对 gvfs 枚举较慢。

深度扫描更慢，部分设备可能误报；优先使用常规扫描。

---

## 默认录音主目录

在 **编辑 → 设置…**（F7）中勾选**使用默认**时，导入目标根目录按下列顺序确定（`app_settings.default_recordings_location()`）：

| 优先级 | 路径 | 使用条件 |
|--------|------|----------|
| 1 | `<prefixdir>/data/Recordings` | 存在 `<prefixdir>/data` |
| 2 | `<bindir>/data/Recordings` | 存在 `<bindir>/data` |
| 3 | `<Documents>/Recordings` | 否则（首次使用时创建） |

定义：

- **`bindir`** — 含 `wav2chat.py` 的目录。若无该文件（源码运行），则使用包目录（`app_settings.py` 所在目录）。
- **`prefixdir`** — `bindir` 的父目录。

示例：

| 布局 | 典型默认值 |
|------|------------|
| 安装在 `/opt/wav2chat/`，且有 `/opt/data/` | `/opt/data/Recordings` |
| 便携目录，源码旁有 `./data/` | `./data/Recordings` |
| 普通用户安装，无 `data/` 目录 | `~/Documents/Recordings` |

`<Documents>` 在设置了 `XDG_DOCUMENTS_DIR` 时使用该变量，否则为 `~/Documents`。

可在设置中指定自定义文件夹覆盖默认值；路径保存在 `~/.config/wav2chat/settings.json`。

---

## 导入计划与复制

**录音主目录**是目标**根路径**。导入文件放在年/月子目录下：

```
<录音主目录>/2025/2025-06/recording.mp3
```

用户 fallback 示例：

```
~/Documents/Recordings/2025/2025-06/recording.mp3
```

`plan_phone_import()`：

- 目标路径：`<录音主目录>/<年>/<年-MM>/<原始文件名>`
- 月份目录取源文件修改时间。
- 若目标已存在同名文件则**跳过**（计为「已导入」）。

`run_phone_import()`：

- 默认：**复制**（`shutil.copy2`，保留 mtime）
- 可选：**导入后从手机删除** — 使用 `shutil.move`（复制后删源）

进度在对话框底部状态栏按文件更新。

导入完成后，在文件列表中选中音频并**转换**，会在同目录生成可读的 `.txt` 与结构化 `.chatlog` 侧车文件。

---

## MTP 常见问题（计数或扫描异常）

| 现象 | wav2chat 中的处理 |
|------|-------------------|
| gvfs `iterdir` 慢或不完整 | 状态回调；MTP 1.5 秒后重试 |
| 递归遍历暴露巨大目录树 | 小米 `call_rec`：**仅非递归**列出 |
| 挂载根 + 内部存储重复扫描 | 优先仅扫描内部存储子目录 |
| 匹配到错误文件夹 | 严格目录 + 厂商专用短列表 |
| 部分文件 `stat()` 失败 | 跳过该文件，继续扫描 |

若设备将通话存在**非标准路径**，深度扫描可能找到；否则在 `phone_import.py` 的 `CALL_RECORDING_DIRS` 中添加路径。

---

## GUI 流程（`phone_import_dialog.py`）

1. 打开 **文件 → 从手机导入…**（Ctrl+I）。
2. 对话框在后台线程扫描挂载点，再扫描各设备的通话录音目录。
3. 选择设备，查看 **新文件 / 总数**，可选启用导入后删除。
4. **重新扫描** 在不关闭对话框的情况下刷新设备列表与计数。
5. **导入** 在后台线程复制文件；成功后主窗口文件浏览器跳转到首个导入文件的月份目录。
6. 导入结束后，对话框**异步重新扫描手机**，使计数保持准确（启用导入后删除时尤为重要）。

扫描详情仅显示在对话框**底部状态栏**（不会重复写入主窗口日志）。

导入进行中时按 **Esc** 无法关闭对话框；空闲时可 Esc 关闭。

---

## 故障排除

| 现象 | 检查项 |
|------|--------|
| 找不到设备 | 手机 MTP 模式；`/run/user/$UID/gvfs/` 下是否有条目；解锁手机 |
| 录音数为 0 | 手机是否开启通话录音；在 PC 文件管理器中能否打开 `call_rec`（或厂商路径） |
| 计数偏高 | 通常已通过严格非递归扫描修复；若仍不对请报告机型与路径 |
| 导入中途失败 | 磁盘空间；gvfs 断开；保持 USB 连接直至完成 |
| 目标文件夹不对 | **编辑 → 设置…** — 检查默认与自定义录音主目录 |

手动检查：

```bash
ls "/run/user/$(id -u)/gvfs/"
# 再浏览 mtp:…/Internal shared storage/MIUI/sound_recorder/call_rec/
```

---

## 相关设置

| 设置 | 文件 / 键 | 用途 |
|------|-----------|------|
| 录音主目录（默认） | `app_settings.py` → `default_recordings_location()` | 勾选「使用默认」时的导入根目录 |
| 自定义录音主目录 | `custom_recordings_location` | 设置中的用户覆盖路径 |
| 导入后删除 | `phone_delete_after_import` | 移动 vs 复制 |
| 面包屑 Home 按钮 | 主窗口 | 文件浏览器跳转到录音主目录 |
| 设置对话框 | **编辑 → 设置…**（F7） | 修改录音主目录 |

GUI 持久状态（窗口布局、上次浏览目录等）保存在 `~/.config/wav2chat/settings.json`。

---

## 代码索引

| 函数 | 作用 |
|------|------|
| `_iter_mount_roots()` | 查找 gvfs/media 挂载点 |
| `discover_phone_mounts()` | 列出手机设备（不扫文件） |
| `_detect_vendor()` | 从挂载名识别厂商 |
| `_call_recording_dirs()` | 各厂商文件夹列表 |
| `_collect_from_dirs()` | 扫描已知文件夹 |
| `_fallback_scan()` | 深度启发式扫描 |
| `destination_for_recording()` | 生成 `<年>/<年-MM>/<文件名>` 路径 |
| `plan_phone_import()` | 构建导入队列，跳过已存在 |
| `run_phone_import()` | 复制/移动文件 |
| `rescan_device_recordings()` | 导入后刷新单台设备 |
