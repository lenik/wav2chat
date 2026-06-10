"""Persistent application settings for the wav2chat GUI."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path

SETTINGS_VERSION = 7
LOG_PANEL_DEFAULT_HEIGHT = 120
DEFAULT_WINDOW_WIDTH = 1180
DEFAULT_WINDOW_HEIGHT = 680
MIN_CONTENT_HEIGHT = 120


def _config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "wav2chat"
    return Path.home() / ".config" / "wav2chat"


def settings_path() -> Path:
    return _config_dir() / "settings.json"


def default_documents_dir() -> Path:
    xdg = os.environ.get("XDG_DOCUMENTS_DIR")
    if xdg:
        return Path(xdg)
    return Path.home() / "Documents"


def wav2chat_bindir() -> Path:
    candidate = Path(sys.argv[0])
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if candidate.is_file():
        return candidate.parent
    return candidate


def find_data_dir() -> Path | None:
    bindir = wav2chat_bindir()
    prefix = bindir.parent
    for candidate in (bindir / "data", prefix / "data"):
        if candidate.is_dir():
            return candidate
    return None


def default_recordings_location() -> Path:
    data_dir = find_data_dir()
    if data_dir is not None:
        return data_dir / "Recordings"
    return default_documents_dir() / "wav2chat" / "Recordings"


@dataclass
class AppSettings:
    use_default_recordings_location: bool = True
    custom_recordings_location: Path | None = None
    last_browser_directory: Path | None = None
    phone_delete_after_import: bool = False
    splitter_main_pos: int | None = None
    splitter_browser_pos: int | None = None
    log_sash_height: int = LOG_PANEL_DEFAULT_HEIGHT
    directory_tree_visible: bool = True
    log_panel_visible: bool = True
    refresh_models: bool = False
    window_width: int | None = None
    window_height: int | None = None
    window_x: int | None = None
    window_y: int | None = None
    window_maximized: bool = False
    large_tools: bool = False
    show_tool_labels: bool = False
    toolbar_visible: bool = True

    @property
    def recordings_location(self) -> Path:
        if self.use_default_recordings_location:
            return default_recordings_location()
        if self.custom_recordings_location is not None:
            return self.custom_recordings_location.expanduser()
        return default_recordings_location()

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "custom_recordings_location":
                payload[field.name] = None if value is None else str(value)
            elif field.name == "last_browser_directory":
                payload[field.name] = None if value is None else str(value)
            else:
                payload[field.name] = value
        payload["version"] = SETTINGS_VERSION
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> AppSettings:
        last_raw = data.get("last_browser_directory")
        last_dir = Path(str(last_raw)).expanduser() if last_raw else None
        delete_after = bool(data.get("phone_delete_after_import", False))
        splitter_main = data.get("splitter_main_pos")
        splitter_browser = data.get("splitter_browser_pos")
        log_height_raw = data.get("log_sash_height", LOG_PANEL_DEFAULT_HEIGHT)
        try:
            log_height = int(log_height_raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            log_height = LOG_PANEL_DEFAULT_HEIGHT
        tree_visible = bool(data.get("directory_tree_visible", True))
        log_visible = bool(data.get("log_panel_visible", True))
        refresh_models = bool(data.get("refresh_models", False))
        window_width = data.get("window_width")
        window_height = data.get("window_height")
        window_x = data.get("window_x")
        window_y = data.get("window_y")
        window_maximized = bool(data.get("window_maximized", False))
        large_tools = bool(data.get("large_tools", False))
        show_tool_labels = bool(data.get("show_tool_labels", False))
        toolbar_visible = bool(data.get("toolbar_visible", True))

        if "use_default_recordings_location" in data:
            use_default = bool(data.get("use_default_recordings_location", True))
            custom_raw = data.get("custom_recordings_location")
            custom = Path(str(custom_raw)).expanduser() if custom_raw else None
        else:
            legacy_raw = data.get("recordings_location")
            if legacy_raw:
                use_default = False
                custom = Path(str(legacy_raw)).expanduser()
            else:
                use_default = True
                custom = None

        return cls(
            use_default_recordings_location=use_default,
            custom_recordings_location=custom,
            last_browser_directory=last_dir,
            phone_delete_after_import=delete_after,
            splitter_main_pos=int(splitter_main) if splitter_main is not None else None,
            splitter_browser_pos=(
                int(splitter_browser) if splitter_browser is not None else None
            ),
            log_sash_height=max(48, log_height),
            directory_tree_visible=tree_visible,
            log_panel_visible=log_visible,
            refresh_models=refresh_models,
            window_width=int(window_width) if window_width is not None else None,
            window_height=int(window_height) if window_height is not None else None,
            window_x=int(window_x) if window_x is not None else None,
            window_y=int(window_y) if window_y is not None else None,
            window_maximized=window_maximized,
            large_tools=large_tools,
            show_tool_labels=show_tool_labels,
            toolbar_visible=toolbar_visible,
        )


def load_app_settings() -> AppSettings:
    path = settings_path()
    if not path.is_file():
        settings = AppSettings()
        save_app_settings(settings)
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = AppSettings()
        save_app_settings(settings)
        return settings
    if not isinstance(raw, dict):
        settings = AppSettings()
        save_app_settings(settings)
        return settings
    settings = AppSettings.from_dict(raw)
    settings.recordings_location.mkdir(parents=True, exist_ok=True)
    return settings


def save_app_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
