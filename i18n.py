"""UI translations for wav2chat."""

from __future__ import annotations

import locale
import os

SUPPORTED_LOCALES = ("en", "zh", "ja", "ko")
DEFAULT_LOCALE = "en"

_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "app.window_title": "Recordings to Chat",
        "menu.file": "File",
        "menu.language": "Language",
        "menu.open_waveform": "Open waveform...",
        "menu.open_chat_session": "Open chat session...",
        "menu.exit": "Exit",
        "lang.en": "English",
        "lang.zh": "Chinese",
        "lang.ja": "Japanese",
        "lang.ko": "Korean",
        "label.audio_file": "Audio file:",
        "label.files": "Files:",
        "label.file_column": "File",
        "hint.search": "Search transcript (space-separated keywords)",
        "label.view": "View:",
        "button.select": "Select",
        "button.convert": "Convert",
        "button.auto_convert": "Auto Convert",
        "view.list": "List",
        "view.bubbles": "Bubbles",
        "status.no_session": "No session loaded",
        "status.select_or_convert": "Select or convert an audio file",
        "status.ready": "Ready",
        "status.loading_models": "Loading FunASR models...",
        "status.nothing_to_convert": "Nothing to convert",
        "status.converting": "Converting {name}...",
        "status.progress": "[{current}/{total}] {name} — {phase}",
        "status.progress_pct": "[{current}/{total}] {name} — {phase} ({percent}%)",
        "status.loaded_session": "Loaded chat session: {name}",
        "status.playing_segment": "Playing [{start} - {end}]",
        "status.playback_failed": "Playback failed: {error}",
        "phase.loading_models": "Loading models",
        "phase.normalizing": "Normalizing audio",
        "phase.transcribing": "Transcribing",
        "phase.saving": "Saving results",
        "meta.duration": "Duration {duration}",
        "dialog.open_waveform": "Open waveform",
        "dialog.open_chat_session": "Open chat session",
        "dialog.error_title": "wav2chat",
        "dialog.load_json_title": "Open chat session",
        "dialog.load_json_failed": "Failed to load JSON:\n{error}",
        "filetype.audio": "Audio files",
        "filetype.json": "JSON transcript",
        "filetype.all": "All files",
        "log.dnd_disabled": "Drag-and-drop disabled. Install tkinterdnd2 for file drop support: pip install tkinterdnd2",
        "cli.wrote_txt": "Wrote {path}",
        "cli.wrote_json": "Wrote {path}",
        "cli.kept_wav": "Kept normalized wav: {path}",
    },
    "zh": {
        "app.window_title": "录音转聊天",
        "menu.file": "文件",
        "menu.language": "语言",
        "menu.open_waveform": "打开音频...",
        "menu.open_chat_session": "打开聊天会话...",
        "menu.exit": "退出",
        "lang.en": "English",
        "lang.zh": "中文",
        "lang.ja": "日本語",
        "lang.ko": "한국어",
        "label.audio_file": "音频文件：",
        "label.files": "文件：",
        "label.file_column": "文件",
        "hint.search": "搜索转录文本（空格分隔关键词）",
        "label.view": "视图：",
        "button.select": "选择",
        "button.convert": "转换",
        "button.auto_convert": "自动转换",
        "view.list": "列表",
        "view.bubbles": "气泡",
        "status.no_session": "未加载会话",
        "status.select_or_convert": "选择或转换音频文件",
        "status.ready": "就绪",
        "status.loading_models": "正在加载 FunASR 模型...",
        "status.nothing_to_convert": "没有待转换的文件",
        "status.converting": "正在转换 {name}...",
        "status.progress": "[{current}/{total}] {name} — {phase}",
        "status.progress_pct": "[{current}/{total}] {name} — {phase}（{percent}%）",
        "status.loaded_session": "已加载聊天会话：{name}",
        "status.playing_segment": "正在播放 [{start} - {end}]",
        "status.playback_failed": "播放失败：{error}",
        "phase.loading_models": "加载模型",
        "phase.normalizing": "规范化音频",
        "phase.transcribing": "语音识别",
        "phase.saving": "保存结果",
        "meta.duration": "时长 {duration}",
        "dialog.open_waveform": "打开音频",
        "dialog.open_chat_session": "打开聊天会话",
        "dialog.error_title": "wav2chat",
        "dialog.load_json_title": "打开聊天会话",
        "dialog.load_json_failed": "无法加载 JSON：\n{error}",
        "filetype.audio": "音频文件",
        "filetype.json": "JSON 转录",
        "filetype.all": "所有文件",
        "log.dnd_disabled": "拖放已禁用。安装 tkinterdnd2 以启用：pip install tkinterdnd2",
        "cli.wrote_txt": "已写入 {path}",
        "cli.wrote_json": "已写入 {path}",
        "cli.kept_wav": "已保留规范化 wav：{path}",
    },
    "ja": {
        "app.window_title": "録音をチャットに",
        "menu.file": "ファイル",
        "menu.language": "言語",
        "menu.open_waveform": "音声を開く...",
        "menu.open_chat_session": "チャットセッションを開く...",
        "menu.exit": "終了",
        "lang.en": "English",
        "lang.zh": "中文",
        "lang.ja": "日本語",
        "lang.ko": "한국어",
        "label.audio_file": "音声ファイル：",
        "label.files": "ファイル：",
        "label.file_column": "ファイル",
        "hint.search": "文字起こしを検索（スペース区切り）",
        "label.view": "表示：",
        "button.select": "選択",
        "button.convert": "変換",
        "button.auto_convert": "自動変換",
        "view.list": "リスト",
        "view.bubbles": "吹き出し",
        "status.no_session": "セッション未読み込み",
        "status.select_or_convert": "音声ファイルを選択または変換してください",
        "status.ready": "準備完了",
        "status.loading_models": "FunASR モデルを読み込み中...",
        "status.nothing_to_convert": "変換対象がありません",
        "status.converting": "{name} を変換中...",
        "status.progress": "[{current}/{total}] {name} — {phase}",
        "status.progress_pct": "[{current}/{total}] {name} — {phase}（{percent}%）",
        "status.loaded_session": "チャットセッションを読み込みました：{name}",
        "status.playing_segment": "再生中 [{start} - {end}]",
        "status.playback_failed": "再生に失敗しました：{error}",
        "phase.loading_models": "モデル読み込み",
        "phase.normalizing": "音声正規化",
        "phase.transcribing": "文字起こし",
        "phase.saving": "結果保存",
        "meta.duration": "長さ {duration}",
        "dialog.open_waveform": "音声を開く",
        "dialog.open_chat_session": "チャットセッションを開く",
        "dialog.error_title": "wav2chat",
        "dialog.load_json_title": "チャットセッションを開く",
        "dialog.load_json_failed": "JSON の読み込みに失敗しました：\n{error}",
        "filetype.audio": "音声ファイル",
        "filetype.json": "JSON transcript",
        "filetype.all": "すべてのファイル",
        "log.dnd_disabled": "ドラッグ＆ドロップは無効です。tkinterdnd2 をインストールしてください：pip install tkinterdnd2",
        "cli.wrote_txt": "出力しました：{path}",
        "cli.wrote_json": "出力しました：{path}",
        "cli.kept_wav": "正規化 wav を保存しました：{path}",
    },
    "ko": {
        "app.window_title": "녹음을 채팅으로",
        "menu.file": "파일",
        "menu.language": "언어",
        "menu.open_waveform": "오디오 열기...",
        "menu.open_chat_session": "채팅 세션 열기...",
        "menu.exit": "종료",
        "lang.en": "English",
        "lang.zh": "中文",
        "lang.ja": "日本語",
        "lang.ko": "한국어",
        "label.audio_file": "오디오 파일:",
        "label.files": "파일:",
        "label.file_column": "파일",
        "hint.search": "전사 검색 (공백으로 키워드 구분)",
        "label.view": "보기:",
        "button.select": "선택",
        "button.convert": "변환",
        "button.auto_convert": "자동 변환",
        "view.list": "목록",
        "view.bubbles": "말풍선",
        "status.no_session": "세션 없음",
        "status.select_or_convert": "오디오 파일을 선택하거나 변환하세요",
        "status.ready": "준비됨",
        "status.loading_models": "FunASR 모델 로드 중...",
        "status.nothing_to_convert": "변환할 항목 없음",
        "status.converting": "{name} 변환 중...",
        "status.progress": "[{current}/{total}] {name} — {phase}",
        "status.progress_pct": "[{current}/{total}] {name} — {phase} ({percent}%)",
        "status.loaded_session": "채팅 세션 로드됨: {name}",
        "status.playing_segment": "재생 중 [{start} - {end}]",
        "status.playback_failed": "재생 실패: {error}",
        "phase.loading_models": "모델 로드",
        "phase.normalizing": "오디오 정규화",
        "phase.transcribing": "음성 인식",
        "phase.saving": "결과 저장",
        "meta.duration": "길이 {duration}",
        "dialog.open_waveform": "오디오 열기",
        "dialog.open_chat_session": "채팅 세션 열기",
        "dialog.error_title": "wav2chat",
        "dialog.load_json_title": "채팅 세션 열기",
        "dialog.load_json_failed": "JSON 로드 실패:\n{error}",
        "filetype.audio": "오디오 파일",
        "filetype.json": "JSON transcript",
        "filetype.all": "모든 파일",
        "log.dnd_disabled": "드래그 앤 드롭 비활성화. tkinterdnd2 설치: pip install tkinterdnd2",
        "cli.wrote_txt": "저장됨: {path}",
        "cli.wrote_json": "저장됨: {path}",
        "cli.kept_wav": "정규화 wav 보존: {path}",
    },
}

_current_locale = DEFAULT_LOCALE


def normalize_locale(code: str | None) -> str:
    if not code:
        return detect_locale()

    normalized = code.strip().lower().replace("_", "-")
    base = normalized.split("-", 1)[0]
    if base in SUPPORTED_LOCALES:
        return base

    aliases = {
        "cn": "zh",
        "jp": "ja",
        "kr": "ko",
        "english": "en",
        "chinese": "zh",
        "japanese": "ja",
        "korean": "ko",
    }
    return aliases.get(base, DEFAULT_LOCALE)


def detect_locale() -> str:
    for env_var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_var)
        if value and value.lower() not in {"c", "posix"}:
            candidate = normalize_locale(value.split(".", 1)[0])
            if candidate in SUPPORTED_LOCALES:
                return candidate

    try:
        code, _encoding = locale.getdefaultlocale()
        if code:
            candidate = normalize_locale(code)
            if candidate in SUPPORTED_LOCALES:
                return candidate
    except (ValueError, TypeError):
        pass

    return DEFAULT_LOCALE


def set_locale(code: str | None = None) -> str:
    global _current_locale
    _current_locale = normalize_locale(code)
    return _current_locale


def get_locale() -> str:
    return _current_locale


def t(key: str, **kwargs: object) -> str:
    table = _MESSAGES.get(_current_locale) or _MESSAGES[DEFAULT_LOCALE]
    message = table.get(key) or _MESSAGES[DEFAULT_LOCALE].get(key) or key
    if kwargs:
        return message.format(**kwargs)
    return message
