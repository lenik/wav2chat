"""Desktop GUI for wav2chat (wxPython)."""

from __future__ import annotations

import argparse
import logging
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import wx

from wav2chat.app_settings import (
    DEFAULT_WINDOW_HEIGHT,
    DEFAULT_WINDOW_WIDTH,
    MIN_CONTENT_HEIGHT,
    load_app_settings,
    save_app_settings,
)
from wav2chat.audio_playback import SegmentPlayer, segment_play_range
from wav2chat.dialog_utils import bind_dialog_escape_close, setup_dialog_fonts
from wav2chat.errors import FunASREmptyResultError, Wav2ChatError
from wav2chat.fs_browser import (
    TREE_DUMMY_LABEL,
    list_subdirectories,
    path_breadcrumb_segments,
)
from wav2chat.filename_meta import entry_timestamp, parse_audio_filename
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.i18n import SUPPORTED_LOCALES, set_locale, t
from wav2chat.models import Segment, Speaker, Transcript
from wav2chat.pipeline import (
    CHATLOG_EXTENSION,
    SUPPORTED_EXTENSIONS,
    collect_supported_audio_paths,
    convert_file,
    default_json_path,
    find_transcript_path,
    is_supported_audio,
    is_transcript_path,
    write_transcript_outputs,
)
from wav2chat.render import display_name, format_timestamp
from wav2chat.phone_import import PhoneImportResult
from wav2chat.phone_import_dialog import PhoneImportDialog
from wav2chat.settings_dialog import SettingsDialog
from wav2chat.speaker_ui import RoundedAvatarPanel, SpeakerProfileDialog

AUDIO_WILDCARD = "*.wav;*.mp3;*.m4a;*.amr;*.aac;*.flac;*.ogg"
CHATLOG_WILDCARD = "*.chatlog;*.json"

IMG_UNCONVERTED = 0
IMG_CONVERTED = 1
IMG_EMPTY = 2
IMG_ERROR = 3
IMG_CONVERTING = 4
IMG_WARNING = 5
IMG_SESSION_ONLY = 6
STATUS_DOT_RGB = {
    IMG_UNCONVERTED: (198, 40, 40),
    IMG_CONVERTED: (46, 125, 50),
    IMG_EMPTY: (173, 216, 230),
    IMG_ERROR: (198, 40, 40),
    IMG_CONVERTING: (21, 101, 192),
    IMG_SESSION_ONLY: (255, 255, 255),
}
STATUS_ICON_SIZE = 14
PANEL_PADDING = 10
SPLITTER_GUTTER = 8
TOOLBAR_BITMAP_MEDIUM = 24
TOOLBAR_BITMAP_LARGE = 32
LOG_PANEL_DEFAULT_HEIGHT = 120
LOG_PANEL_MIN_HEIGHT = 48
FILE_PANEL_DEFAULT_WIDTH = 320
MIN_FILE_PANEL_WIDTH = 100
MIN_TREE_PANEL_WIDTH = 120
MIN_CHAT_PANEL_WIDTH = 420
STATUS_PROGRESS_WIDTH = 140
NAME_COL = 0
STATUS_COL = 1
STATUS_COL_WIDTH = STATUS_ICON_SIZE + 14
PLAYING_SEGMENT_RGB = (0xBB, 0xDE, 0xFB)
SEARCH_MATCH_RGB = (255, 249, 196)
SEARCH_BUBBLE_RGB = (255, 244, 180)
BUBBLE_LEFT_RGB = (255, 255, 255)
BUBBLE_RIGHT_RGB = (0x95, 0xEC, 0x69)
CHAT_BG_RGB = (236, 236, 236)
MESSAGE_TEXT_RGB = (0, 0, 0)
BUBBLE_PRIMARY_RGB = BUBBLE_RIGHT_RGB
BUBBLE_OTHER_RGB = BUBBLE_LEFT_RGB
AVATAR_SIZE = 40
AVATAR_COL_WIDTH = AVATAR_SIZE + 12
BUBBLE_RADIUS = 10
BUBBLE_INNER_PAD = 10
BUBBLE_TEXT_WIDTH_PAD = 16
BUBBLE_AVATAR_H_MARGIN = 6
BUBBLE_AVATAR_RESERVE = AVATAR_COL_WIDTH + BUBBLE_AVATAR_H_MARGIN * 2
BUBBLE_SIDE_CHROME = BUBBLE_AVATAR_RESERVE + 32
LIST_SIDE_CHROME = 40
RENDER_CHUNK_SIZE = 30
SPEAKER_EMOJI_FRAMES = ("🔈", "🔉", "🔊")
NAME_CAPTION_RGB = (110, 110, 110)
SPEAKER_AVATAR_RGBS = (
    (33, 150, 243),
    (76, 175, 80),
    (255, 152, 0),
    (156, 39, 176),
    (0, 172, 193),
    (244, 67, 54),
)


def _rgb_colour(red: int, green: int, blue: int) -> wx.Colour:
    return wx.Colour(red, green, blue)

from wav2chat.ui_fonts import apply_ui_font, pick_unicode_font


MENU_BITMAP_SIZE = 16


def _menu_stock_bitmap(art_id: str) -> wx.Bitmap:
    return wx.ArtProvider.GetBitmap(
        art_id,
        wx.ART_MENU,
        wx.Size(MENU_BITMAP_SIZE, MENU_BITMAP_SIZE),
    )


def _play_stock_bitmap(size: int = 16) -> wx.Bitmap:
    """Toolbar/button play icon; gtk-media-play on GTK, GO_FORWARD elsewhere."""
    px = wx.Size(size, size)
    play = wx.ArtProvider.GetBitmap("gtk-media-play", wx.ART_BUTTON, px)
    if play.IsOk():
        return play
    return wx.ArtProvider.GetBitmap(wx.ART_GO_FORWARD, wx.ART_BUTTON, px)


def _append_menu_item(
    menu: wx.Menu,
    item_id: int,
    label: str,
    *,
    art_id: str | None = None,
    kind: int = wx.ITEM_NORMAL,
) -> wx.MenuItem:
    item = wx.MenuItem(menu, item_id, label, kind=kind)
    if art_id is not None and kind == wx.ITEM_NORMAL:
        bitmap = _menu_stock_bitmap(art_id)
        if bitmap.IsOk():
            item.SetBitmap(bitmap)
    menu.Append(item)
    return item


class _FlatLinkButton(wx.Panel):
    """Flat breadcrumb segment with hover border."""

    def __init__(self, parent: wx.Window, label: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._hover = False
        self._active = False
        self._enabled = True
        self._border = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNSHADOW)
        self._label = wx.StaticText(self, label=label)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self._label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.SetSizer(sizer)
        self.SetToolTip(label)
        self._apply_colours()
        self._click_handler: Callable[[], None] | None = None
        self.Bind(wx.EVT_PAINT, self._on_paint)
        for target in (self, self._label):
            target.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
            target.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
            target.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
            target.Bind(wx.EVT_LEFT_UP, self._on_left_up)

    def SetLabel(self, label: str) -> None:
        self._label.SetLabel(label)
        self.SetToolTip(label)

    def GetLabel(self) -> str:
        return self._label.GetLabel()

    def BindClick(self, handler: Callable[[], None]) -> None:
        self._click_handler = handler

    def SetActive(self, active: bool) -> None:
        self._active = active
        self.Refresh()

    def Enable(self, enable: bool = True) -> None:
        self._enabled = enable
        colour = wx.SystemSettings.GetColour(
            wx.SYS_COLOUR_GRAYTEXT if not enable else wx.SYS_COLOUR_WINDOWTEXT
        )
        self._label.SetForegroundColour(colour)
        if not enable:
            self._hover = False
        self._apply_colours()
        self.Refresh()
        super().Enable(enable)

    def _apply_colours(self) -> None:
        bg = self.GetParent().GetBackgroundColour()
        self.SetBackgroundColour(bg)
        self._label.SetBackgroundColour(bg)

    def _on_paint(self, event: wx.PaintEvent) -> None:
        if not self._enabled or not (self._hover or self._active):
            event.Skip()
            return
        dc = wx.PaintDC(self)
        width, height = self.GetSize()
        dc.SetPen(wx.Pen(self._border, 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(0, 0, width - 1, height - 1)
        event.Skip()

    def _on_enter(self, _event: wx.Event) -> None:
        if not self._enabled:
            return
        self._hover = True
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Refresh()

    def _on_leave(self, _event: wx.Event) -> None:
        self._hover = False
        self.SetCursor(wx.NullCursor)
        self.Refresh()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        handler = self._click_handler
        if not self._enabled or handler is None:
            event.Skip()
            return
        source = event.GetEventObject()
        if not isinstance(source, wx.Window):
            event.Skip()
            return
        pos = self.ScreenToClient(source.ClientToScreen(event.GetPosition()))
        clicked = self.GetClientRect().Contains(pos)
        event.Skip()
        if clicked:
            wx.CallAfter(handler)


class _IntSpinRow(wx.Panel):
    """Compact integer field; Up/Down keys adjust the value (no spin buttons)."""

    def __init__(
        self,
        parent: wx.Window,
        value: int,
        *,
        min_value: int = 1,
        max_value: int = 99,
    ) -> None:
        super().__init__(parent)
        self._min_value = min_value
        self._max_value = max_value
        self._value = self._clamp(value)
        self._change_handler: Callable[[], None] | None = None
        self._text = wx.TextCtrl(
            self,
            value=str(self._value),
            style=wx.TE_CENTRE | wx.TE_PROCESS_ENTER,
            size=wx.Size(44, -1),
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self._text, 0, wx.ALIGN_CENTER_VERTICAL)
        self.SetSizer(row)
        self._text.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self._text.Bind(wx.EVT_KILL_FOCUS, self._on_text_done)
        self._text.Bind(wx.EVT_TEXT_ENTER, self._on_text_done)

    def BindValueChanged(self, handler: Callable[[], None]) -> None:
        self._change_handler = handler

    def _clamp(self, value: int) -> int:
        return max(self._min_value, min(self._max_value, value))

    def GetValue(self) -> int:
        return self._value

    def SetValue(self, value: int) -> None:
        self._value = self._clamp(value)
        self._text.SetValue(str(self._value))

    def _notify_change(self) -> None:
        if self._change_handler is not None:
            self._change_handler()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_UP:
            self.SetValue(self._value + 1)
            self._notify_change()
            return
        if key == wx.WXK_DOWN:
            self.SetValue(self._value - 1)
            self._notify_change()
            return
        event.Skip()

    def _on_text_done(self, event: wx.Event) -> None:
        try:
            value = int(self._text.GetValue().strip())
        except ValueError:
            value = self._value
        previous = self._value
        self.SetValue(value)
        if self._value != previous:
            self._notify_change()
        event.Skip()

    def Disable(self) -> bool:
        self._text.Disable()
        return super().Disable()

    def Enable(self, enable: bool = True) -> bool:
        self._text.Enable(enable)
        return super().Enable(enable)


@dataclass
class FileEntry:
    path: Path
    status: str = "unconverted"
    transcript: Transcript | None = None
    error: str | None = None
    has_audio: bool = True
    session_only: bool = False
    json_invalid: bool = False


@dataclass
class GuiSettings:
    backend: str = "funasr"
    lang: str = "zh"
    ui_lang: str | None = None
    min_speakers: int | None = None
    max_speakers: int | None = None
    roles: dict[str, str] = field(default_factory=dict)
    keep_temp: bool = False
    verbose: bool = False
    quiet: bool = False
    refresh_models: bool = False


def _parse_search_keywords(query: str) -> list[str]:
    return [part for part in query.split() if part]


def _entry_transcript_text(entry: FileEntry) -> str:
    if entry.transcript is None:
        return ""
    return "\n".join(segment.text for segment in entry.transcript.segments)


def _entry_matches_keywords(entry: FileEntry, keywords: list[str]) -> bool:
    if not keywords:
        return True
    if entry.transcript is None:
        return False
    haystack = _entry_transcript_text(entry).casefold()
    return all(keyword.casefold() in haystack for keyword in keywords)


def _segment_matches_keywords(segment: Segment, keywords: list[str]) -> bool:
    if not keywords:
        return False
    text = segment.text.casefold()
    return all(keyword.casefold() in text for keyword in keywords)


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _entry_label(path: Path) -> str:
    return path.name


def _entry_title(path: Path) -> str:
    return parse_audio_filename(path).title


def _entry_meta(path: Path, duration: float | None) -> str:
    parsed = parse_audio_filename(path)
    if parsed.recorded_at is not None:
        timestamp = parsed.recorded_at.strftime("%Y-%m-%d %H:%M")
    else:
        timestamp = entry_timestamp(path).strftime("%Y-%m-%d %H:%M")
    return f"{timestamp}  {t('meta.duration', duration=_format_duration(duration))}"


def _try_load_transcript_json(path: Path) -> Transcript | None:
    try:
        return Transcript.load_json(path)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _find_audio_for_stem(stem_path: Path) -> Path | None:
    for ext in SUPPORTED_EXTENSIONS:
        candidate = stem_path.with_suffix(ext)
        if candidate.is_file():
            return candidate
    return None


def _entry_has_playable_audio(entry: FileEntry) -> bool:
    return entry.has_audio and entry.path.is_file() and is_supported_audio(entry.path)


def _entry_json_path(entry: FileEntry) -> Path:
    if entry.session_only:
        return entry.path
    return default_json_path(entry.path)


def _list_directory_paths(directory: Path) -> list[Path]:
    try:
        items = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return []
    audio_paths = [path for path in items if is_supported_audio(path)]
    chatlog_paths = [
        path
        for path in items
        if path.is_file() and path.suffix.lower() == CHATLOG_EXTENSION
    ]
    audio_stems = {path.stem for path in audio_paths}
    combined = list(audio_paths)
    for chatlog_path in chatlog_paths:
        if chatlog_path.stem not in audio_stems:
            combined.append(chatlog_path)
    return sorted(combined, key=lambda p: p.name.lower())


def _transcript_is_empty(transcript: Transcript | None) -> bool:
    if transcript is None:
        return False
    return not any(segment.text.strip() for segment in transcript.segments)


def _create_dot_bitmap(
    colour: wx.Colour,
    size: int = STATUS_ICON_SIZE,
    *,
    outline: bool = False,
) -> wx.Bitmap:
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    image = wx.Image(size, size)
    if not image.IsOk():
        return wx.Bitmap(size, size)
    for y in range(size):
        for x in range(size):
            image.SetRGB(x, y, bg.Red(), bg.Green(), bg.Blue())
    bitmap = wx.Bitmap(image)
    dc = wx.MemoryDC(bitmap)
    dc.SetBrush(wx.Brush(colour))
    if outline:
        dc.SetPen(wx.Pen(wx.Colour(160, 160, 160)))
    else:
        dc.SetPen(wx.Pen(colour))
    radius = max(2, size // 2 - 2)
    dc.DrawCircle(size // 2, size // 2, radius)
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def _create_warning_bitmap(size: int = STATUS_ICON_SIZE) -> wx.Bitmap:
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    image = wx.Image(size, size)
    if not image.IsOk():
        return wx.Bitmap(size, size)
    for y in range(size):
        for x in range(size):
            image.SetRGB(x, y, bg.Red(), bg.Green(), bg.Blue())
    bitmap = wx.Bitmap(image)
    dc = wx.MemoryDC(bitmap)
    gc = wx.GraphicsContext.Create(dc)
    if gc is not None:
        path = gc.CreatePath()
        path.MoveToPoint(size / 2, 2)
        path.AddLineToPoint(size - 2, size - 2)
        path.AddLineToPoint(2, size - 2)
        path.CloseSubpath()
        gc.SetBrush(wx.Brush(wx.Colour(255, 193, 7)))
        gc.SetPen(wx.Pen(wx.Colour(230, 140, 0)))
        gc.FillPath(path)
        font = wx.Font(max(7, size - 7), wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        gc.SetFont(font, wx.Colour(40, 40, 40))
        gc.DrawText("!", size / 2 - 3, size / 2 - 6)
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def _build_status_image_list() -> wx.ImageList:
    images = wx.ImageList(STATUS_ICON_SIZE, STATUS_ICON_SIZE, True)
    mask = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    for index in range(IMG_CONVERTING + 1):
        red, green, blue = STATUS_DOT_RGB[index]
        bitmap = _create_dot_bitmap(wx.Colour(red, green, blue))
        images.Add(bitmap, mask)
    images.Add(_create_warning_bitmap(), mask)
    white = STATUS_DOT_RGB[IMG_SESSION_ONLY]
    images.Add(_create_dot_bitmap(wx.Colour(*white), outline=True), mask)
    return images


def _status_image_index(entry: FileEntry) -> int:
    if entry.json_invalid:
        return IMG_WARNING
    if entry.session_only:
        return IMG_SESSION_ONLY
    if entry.status == "converted":
        if _transcript_is_empty(entry.transcript):
            return IMG_EMPTY
        return IMG_CONVERTED
    if entry.status == "error":
        return IMG_ERROR
    if entry.status == "converting":
        return IMG_CONVERTING
    return IMG_UNCONVERTED


class _RoundedBubblePanel(wx.Panel):
    """Chat bubble with rounded corners drawn in OnPaint."""

    def __init__(self, parent: wx.Window, colour: wx.Colour, radius: int = BUBBLE_RADIUS) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._bg_colour = colour
        self._radius = radius
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def set_colour(self, colour: wx.Colour) -> None:
        self._bg_colour = colour
        self.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return
        if gc is None:
            dc.SetBrush(wx.Brush(self._bg_colour))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, width, height)
            return
        gc.SetBrush(wx.Brush(self._bg_colour))
        gc.SetPen(wx.Pen(self._bg_colour))
        gc.DrawRoundedRectangle(0, 0, width, height, self._radius)
        event.Skip()


class _GuiLogHandler(logging.Handler):
    def __init__(self, enqueue) -> None:
        super().__init__()
        self._enqueue = enqueue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._enqueue(record.levelno, self.format(record))
        except Exception:
            self.handleError(record)


class _PathDropTarget(wx.FileDropTarget):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def OnDropFiles(self, _x: int, _y: int, filenames: list[str]) -> bool:
        paths = [Path(path) for path in filenames]
        wx.CallAfter(self._callback, paths)
        return True


class _ImportDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            title=t("dialog.importing"),
            style=(wx.DEFAULT_DIALOG_STYLE & ~wx.CLOSE_BOX) | wx.STAY_ON_TOP,
        )
        self._status = wx.StaticText(self, label=t("dialog.import_scanning"))
        self._gauge = wx.Gauge(self, range=100, size=(360, 22))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._status, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(self._gauge, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        self.SetSizer(sizer)
        self.Fit()
        setup_dialog_fonts(self)
        bind_dialog_escape_close(self)
        self.CentreOnParent()

    def set_message(self, message: str) -> None:
        self._status.SetLabel(message)
        self.Layout()

    def set_indeterminate(self) -> None:
        self.set_message(t("dialog.import_scanning"))
        if self._gauge.GetRange() != 100:
            self._gauge.SetRange(100)
        self._gauge.SetValue(0)

    def set_progress(self, current: int, total: int, name: str) -> None:
        self.set_message(
            t("dialog.import_progress", current=current, total=total, name=name)
        )
        self._gauge.SetRange(max(total, 1))
        self._gauge.SetValue(current)

    def set_refreshing(self) -> None:
        self.set_message(t("dialog.import_refreshing"))
        self._gauge.SetRange(100)
        self._gauge.SetValue(100)


class Wav2ChatFrame(wx.Frame):
    ID_OPEN_DIRECTORY = wx.NewIdRef()
    ID_OPEN_SESSION = wx.NewIdRef()
    ID_IMPORT_PHONE = wx.NewIdRef()
    ID_REFRESH_MODELS = wx.NewIdRef()
    ID_REFRESH_BROWSER = wx.NewIdRef()
    ID_EXIT = wx.NewIdRef()
    ID_SETTINGS = wx.NewIdRef()
    ID_SHOW_DIRECTORY = wx.NewIdRef()
    ID_SHOW_LOG = wx.NewIdRef()
    ID_CONVERT = wx.NewIdRef()
    ID_LARGE_TOOLS = wx.NewIdRef()
    ID_SHOW_TOOL_LABELS = wx.NewIdRef()
    ID_SHOW_TOOLBAR = wx.NewIdRef()

    def __init__(
        self,
        settings: GuiSettings,
        initial_paths: list[Path] | None = None,
    ) -> None:
        app_settings = load_app_settings()
        ui_lang = settings.ui_lang or app_settings.ui_lang
        settings.ui_lang = ui_lang
        set_locale(ui_lang)

        super().__init__(
            None,
            title=t("app.window_title"),
            size=wx.Size(
                app_settings.window_width or DEFAULT_WINDOW_WIDTH,
                app_settings.window_height or DEFAULT_WINDOW_HEIGHT,
            ),
        )
        self.settings = settings
        self.app_settings = app_settings
        if not settings.refresh_models:
            settings.refresh_models = self.app_settings.refresh_models

        self.entries: list[FileEntry] = []
        self.focus_index: int | None = None
        self._current_directory: Path | None = None
        self._tree_root_item: wx.TreeItemId | None = None
        self._tree_selecting = False
        self.view_mode = "bubbles"
        self._status_key = "status.ready"
        self._status_kwargs: dict[str, object] = {}
        self._backend: FunASRBackend | None = None
        self._convert_thread: threading.Thread | None = None
        self._import_thread: threading.Thread | None = None
        self._import_dialog: _ImportDialog | None = None
        self._import_active = False
        self._import_added_indices: list[int] = []
        self._phone_import_dialog: PhoneImportDialog | None = None
        self._pending_browser_directory: Path | None = None
        self._stop_convert = threading.Event()
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._status_images = _build_status_image_list()
        self._render_generation = 0
        self._segment_player = SegmentPlayer()
        self._playing_segment_index: int | None = None
        self._segment_rows: list[tuple[wx.Panel, wx.Colour, int]] = []
        self._speaker_icons: dict[int, wx.StaticText] = {}
        self._speaker_emoji_frame = 0
        self._last_bubble_layout_width = 0
        self._last_list_layout_width = 0
        self._search_keywords: list[str] = []
        self._visible_entry_indices: list[int] = []
        self._segment_scroll_targets: dict[int, wx.Window] = {}
        self._search_blur_generation = 0
        self._selection_explicit_empty = False
        self._suppress_file_select = False
        self._converting_active = False
        self._last_progress_log_phase: str | None = None
        self._last_progress_log_percent: int | None = None
        self._render_in_progress = False
        self._render_state: dict | None = None
        self._log_handler: _GuiLogHandler | None = None
        self._log_sash_height = self.app_settings.log_sash_height or LOG_PANEL_DEFAULT_HEIGHT
        self._log_panel_visible = True
        self._directory_tree_visible = True
        self._toolbar_visible = self.app_settings.toolbar_visible
        self._splitter_browser_pos = self.app_settings.splitter_browser_pos or 240
        self._splitter_file_pos = self.app_settings.splitter_main_pos or FILE_PANEL_DEFAULT_WIDTH
        self._pending_tree_directory: Path | None = None
        self._tree_needs_init = False
        self._file_list_needs_sync = False
        self._avatar_panels: dict[int, RoundedAvatarPanel] = {}

        self._build_ui()
        self._setup_ui_fonts()
        self._setup_logging()
        self._bind_events()

        self._queue_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_queue_timer, self._queue_timer)
        self._queue_timer.Start(100)

        self._speaker_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_speaker_timer, self._speaker_timer)

        self._relayout_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_relayout_timer, self._relayout_timer)

        self._render_chunk_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_render_chunk_timer, self._render_chunk_timer)

        start_dir = self.app_settings.last_browser_directory or Path.home()
        if initial_paths:
            first = initial_paths[0].expanduser().resolve()
            start_dir = first.parent if first.is_file() else first
        self._select_tree_directory(start_dir)
        self._load_directory_files(start_dir)
        wx.CallAfter(self._apply_locale)
        wx.CallAfter(self._restore_layout)

    def _build_ui(self) -> None:
        statusbar = self.CreateStatusBar(2)
        statusbar.SetStatusWidths([-2, STATUS_PROGRESS_WIDTH])
        self._progress_gauge = wx.Gauge(statusbar, range=100)
        self._progress_gauge.Hide()
        statusbar.Bind(wx.EVT_SIZE, self._on_statusbar_size)
        self._set_status("status.ready")

        panel = wx.Panel(self)
        root_sizer = wx.BoxSizer(wx.VERTICAL)

        self._main_splitter = wx.SplitterWindow(panel, style=wx.SP_LIVE_UPDATE)
        self._main_splitter.SetSashGravity(1.0)
        self._main_splitter.SetMinimumPaneSize(LOG_PANEL_MIN_HEIGHT)

        self._content_wrap = wx.Panel(self._main_splitter)
        content_sizer = wx.BoxSizer(wx.VERTICAL)

        self._breadcrumb_bar = wx.Panel(self._content_wrap)
        breadcrumb_sizer = wx.BoxSizer(wx.VERTICAL)
        breadcrumb_sizer.Add(self._build_main_toolbar(self._breadcrumb_bar), 0, wx.EXPAND | wx.BOTTOM, 4)
        breadcrumb_row = wx.BoxSizer(wx.HORIZONTAL)
        breadcrumb_row.Add(self._build_home_nav_button(self._breadcrumb_bar), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        self._breadcrumb_panel = wx.Panel(self._breadcrumb_bar, style=wx.BORDER_NONE)
        self._breadcrumb_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._breadcrumb_panel.SetSizer(self._breadcrumb_sizer)
        breadcrumb_row.Add(self._breadcrumb_panel, 1, wx.EXPAND)
        breadcrumb_sizer.Add(breadcrumb_row, 0, wx.EXPAND)
        self._breadcrumb_bar.SetSizer(breadcrumb_sizer)
        self._apply_breadcrumb_nav_colours()

        self._browser_splitter = wx.SplitterWindow(self._content_wrap, style=wx.SP_LIVE_UPDATE)
        self._tree_panel = wx.Panel(self._browser_splitter)
        self._work_panel = wx.Panel(self._browser_splitter)

        splitter_main = wx.SplitterWindow(self._work_panel, style=wx.SP_LIVE_UPDATE)
        self._file_panel = wx.Panel(splitter_main)
        chat_panel = wx.Panel(splitter_main)
        splitter_main.SplitVertically(
            self._file_panel,
            chat_panel,
            self._splitter_file_pos,
        )
        splitter_main.SetMinimumPaneSize(MIN_FILE_PANEL_WIDTH)
        splitter_main.SetSashGravity(0.0)

        tree_sizer = wx.BoxSizer(wx.VERTICAL)
        self._dir_tree = wx.TreeCtrl(
            self._tree_panel,
            style=wx.TR_DEFAULT_STYLE | wx.TR_LINES_AT_ROOT | wx.BORDER_SUNKEN,
        )
        tree_sizer.Add(self._dir_tree, 1, wx.EXPAND)
        self._tree_panel.SetSizer(tree_sizer)

        file_sizer = wx.BoxSizer(wx.VERTICAL)
        self._label_files = wx.StaticText(self._file_panel, label=t("label.files"))
        self._search_box = wx.TextCtrl(self._file_panel, style=wx.TE_PROCESS_ENTER)
        try:
            self._search_box.SetHint(t("hint.search"))
        except AttributeError:
            pass

        self._file_list = wx.ListCtrl(
            self._file_panel,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN,
        )
        self._file_list.SetWindowStyleFlag(
            self._file_list.GetWindowStyleFlag() & ~wx.LC_SINGLE_SEL
        )
        self._file_list.SetImageList(self._status_images, wx.IMAGE_LIST_SMALL)
        self._file_list.InsertColumn(
            NAME_COL,
            t("label.file_column"),
            format=wx.LIST_FORMAT_LEFT,
            width=200,
        )
        self._file_list.InsertColumn(
            STATUS_COL,
            "",
            format=wx.LIST_FORMAT_CENTRE,
            width=STATUS_COL_WIDTH,
        )

        min_speakers, max_speakers = self._speaker_count_defaults()
        speaker_row = wx.BoxSizer(wx.HORIZONTAL)
        self._label_speaker_count = wx.StaticText(self._file_panel, label=t("label.speaker_count"))
        self._spin_min_speakers = _IntSpinRow(self._file_panel, min_speakers)
        self._label_speaker_to = wx.StaticText(self._file_panel, label=t("label.speaker_count_to"))
        self._spin_max_speakers = _IntSpinRow(self._file_panel, max_speakers)
        self._label_speaker_unit = wx.StaticText(self._file_panel, label=t("label.speaker_count_unit"))
        speaker_row.Add(self._label_speaker_count, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        speaker_row.Add(self._spin_min_speakers, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        speaker_row.Add(self._label_speaker_to, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        speaker_row.Add(self._spin_max_speakers, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        speaker_row.Add(self._label_speaker_unit, 0, wx.ALIGN_CENTER_VERTICAL)

        control_row = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_convert = wx.Button(self._file_panel, label=t("button.convert"))
        play_bitmap = _play_stock_bitmap()
        if play_bitmap.IsOk():
            self._btn_convert.SetBitmap(play_bitmap)
            self._btn_convert.SetBitmapPosition(wx.LEFT)
        self._btn_convert.Bind(wx.EVT_BUTTON, self._on_convert_clicked)
        self._chk_auto_convert = wx.CheckBox(self._file_panel, label=t("button.auto_convert"))
        control_row.Add(self._btn_convert, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        control_row.AddStretchSpacer(1)
        control_row.Add(self._chk_auto_convert, 0, wx.ALIGN_CENTER_VERTICAL)

        file_sizer.Add(self._label_files, 0, wx.BOTTOM, 4)
        file_sizer.Add(self._search_box, 0, wx.EXPAND | wx.BOTTOM, 4)
        file_sizer.Add(self._file_list, 1, wx.EXPAND | wx.BOTTOM, 8)
        file_sizer.Add(speaker_row, 0, wx.EXPAND | wx.BOTTOM, 6)
        file_sizer.Add(control_row, 0, wx.EXPAND)
        file_outer = wx.BoxSizer(wx.HORIZONTAL)
        file_outer.Add(file_sizer, 1, wx.EXPAND | wx.RIGHT, SPLITTER_GUTTER)
        self._file_panel.SetSizer(file_outer)

        work_sizer = wx.BoxSizer(wx.VERTICAL)
        work_sizer.Add(splitter_main, 1, wx.EXPAND)
        self._work_panel.SetSizer(work_sizer)

        self._browser_splitter.SplitVertically(
            self._tree_panel,
            self._work_panel,
            self._splitter_browser_pos,
        )
        self._browser_splitter.SetMinimumPaneSize(MIN_TREE_PANEL_WIDTH)
        self._browser_splitter.SetSashGravity(0.0)

        self._init_directory_tree()

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self._title_label = wx.StaticText(chat_panel, label=t("status.no_session"))

        view_row = wx.BoxSizer(wx.HORIZONTAL)
        self._label_view = wx.StaticText(chat_panel, label=t("label.view"))
        self._rb_list = wx.RadioButton(chat_panel, label=t("view.list"), style=wx.RB_GROUP)
        self._rb_bubbles = wx.RadioButton(chat_panel, label=t("view.bubbles"))
        self._rb_bubbles.SetValue(True)
        view_row.Add(self._label_view, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        view_row.Add(self._rb_bubbles, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        view_row.Add(self._rb_list, 0, wx.ALIGN_CENTER_VERTICAL)
        header.Add(self._title_label, 1, wx.ALIGN_CENTER_VERTICAL)
        header.Add(view_row, 0, wx.ALIGN_CENTER_VERTICAL)

        self._meta_label = wx.StaticText(chat_panel, label=t("status.select_or_convert"))
        self._list_panel = wx.ScrolledWindow(chat_panel, style=wx.VSCROLL | wx.BORDER_NONE)
        self._list_panel.SetScrollRate(0, 10)
        self._list_sizer = wx.BoxSizer(wx.VERTICAL)
        self._list_panel.SetSizer(self._list_sizer)
        self._bubble_panel = wx.ScrolledWindow(chat_panel, style=wx.VSCROLL | wx.BORDER_NONE)
        self._bubble_panel.SetBackgroundColour(_rgb_colour(*CHAT_BG_RGB))
        self._bubble_panel.SetScrollRate(0, 10)
        self._bubble_sizer = wx.BoxSizer(wx.VERTICAL)
        self._bubble_panel.SetSizer(self._bubble_sizer)
        self._list_panel.Hide()

        right_sizer.Add(header, 0, wx.EXPAND | wx.BOTTOM, 4)
        right_sizer.Add(self._meta_label, 0, wx.EXPAND | wx.BOTTOM, 8)
        right_sizer.Add(self._list_panel, 1, wx.EXPAND)
        right_sizer.Add(self._bubble_panel, 1, wx.EXPAND)
        chat_outer = wx.BoxSizer(wx.HORIZONTAL)
        chat_outer.Add(right_sizer, 1, wx.EXPAND | wx.LEFT, SPLITTER_GUTTER)
        chat_panel.SetSizer(chat_outer)

        content_sizer.Add(self._breadcrumb_bar, 0, wx.EXPAND | wx.BOTTOM, 4)
        content_sizer.Add(self._browser_splitter, 1, wx.EXPAND)
        self._content_wrap.SetSizer(content_sizer)
        self._splitter_main = splitter_main
        self._chat_panel = chat_panel

        self._log_wrap = wx.Panel(self._main_splitter)
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        self._log_panel = wx.TextCtrl(
            self._log_wrap,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        log_sizer.Add(self._log_panel, 1, wx.EXPAND)
        self._log_wrap.SetSizer(log_sizer)

        self._main_splitter.SplitHorizontally(
            self._content_wrap,
            self._log_wrap,
            -self._log_sash_height,
        )

        root_sizer.Add(self._main_splitter, 1, wx.EXPAND | wx.ALL, PANEL_PADDING)
        panel.SetSizer(root_sizer)

        self._build_menubar()
        self._register_drop_targets()
        self._resize_file_list_columns()
        self._sync_tree_column_width()

    def _setup_ui_fonts(self) -> None:
        self._ui_font = pick_unicode_font()
        self._ui_font_bold = pick_unicode_font(weight=wx.FONTWEIGHT_BOLD)
        self._caption_font = wx.Font(self._ui_font)
        self._caption_font.SetPointSize(max(8, self._ui_font.GetPointSize() - 2))
        self._emoji_font = wx.Font(self._ui_font)
        self._emoji_font.SetPointSize(self._ui_font.GetPointSize() + 2)
        apply_ui_font(self, self._ui_font)
        self._title_label.SetFont(self._ui_font_bold)
        self._log_panel.SetFont(self._ui_font)
        menubar = self.GetMenuBar()
        if menubar is not None:
            menubar.SetFont(self._ui_font)

    def _effective_log_level(self) -> int:
        if self.settings.quiet and not self.settings.verbose:
            return logging.ERROR
        if self.settings.verbose:
            return logging.DEBUG
        return logging.INFO

    def _setup_logging(self) -> None:
        level = self._effective_log_level()
        self._log_handler = _GuiLogHandler(
            lambda levelno, msg: self._ui_queue.put(("log", (levelno, msg)))
        )
        self._log_handler.setLevel(level)
        self._log_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(self._log_handler)
        root.setLevel(level)

    def _append_log(self, levelno: int, message: str) -> None:
        if levelno < self._effective_log_level():
            return
        if not message.endswith("\n"):
            message += "\n"
        self._log_panel.AppendText(message)
        self._log_panel.ShowPosition(self._log_panel.GetLastPosition())

    def _layout_status_gauge(self) -> None:
        if not self._progress_gauge.IsShown():
            return
        statusbar = self.GetStatusBar()
        if statusbar is None:
            return
        rect = statusbar.GetFieldRect(1)
        if rect.width <= 0 or rect.height <= 0:
            return
        self._progress_gauge.SetPosition((rect.x + 4, rect.y + 2))
        self._progress_gauge.SetSize(
            (max(20, rect.width - 8), max(10, rect.height - 4))
        )

    def _on_statusbar_size(self, event: wx.SizeEvent) -> None:
        self._layout_status_gauge()
        event.Skip()

    def _set_progress(self, percent: int | None) -> None:
        if percent is None:
            self._progress_gauge.Hide()
            return
        value = max(0, min(100, int(percent)))
        self._progress_gauge.SetValue(value)
        if not self._progress_gauge.IsShown():
            self._progress_gauge.Show()
            self._layout_status_gauge()

    def _build_menubar(self) -> None:
        menubar = wx.MenuBar()
        file_menu = wx.Menu()
        _append_menu_item(
            file_menu,
            self.ID_OPEN_DIRECTORY,
            t("menu.open_directory"),
            art_id=wx.ART_FOLDER_OPEN,
        )
        _append_menu_item(
            file_menu,
            self.ID_OPEN_SESSION,
            t("menu.open_chat_session"),
            art_id=wx.ART_FILE_OPEN,
        )
        _append_menu_item(
            file_menu,
            self.ID_IMPORT_PHONE,
            t("menu.import_from_phone"),
            art_id=wx.ART_GO_DOWN,
        )
        file_menu.AppendSeparator()
        _append_menu_item(
            file_menu,
            self.ID_REFRESH_MODELS,
            t("menu.refresh_models"),
            kind=wx.ITEM_CHECK,
        )
        file_menu.Check(self.ID_REFRESH_MODELS, self.settings.refresh_models)
        file_menu.AppendSeparator()
        _append_menu_item(
            file_menu,
            self.ID_EXIT,
            t("menu.exit") + "\tCtrl+Q",
            art_id=wx.ART_QUIT,
        )

        edit_menu = wx.Menu()
        _append_menu_item(
            edit_menu,
            self.ID_SETTINGS,
            t("menu.settings"),
            art_id=wx.ART_HELP_SETTINGS,
        )

        view_menu = wx.Menu()
        _append_menu_item(
            view_menu,
            self.ID_REFRESH_BROWSER,
            t("menu.refresh_browser"),
            art_id=wx.ART_REDO,
        )
        view_menu.AppendSeparator()
        _append_menu_item(
            view_menu,
            self.ID_SHOW_DIRECTORY,
            t("menu.show_directory"),
            kind=wx.ITEM_CHECK,
        )
        _append_menu_item(
            view_menu,
            self.ID_SHOW_LOG,
            t("menu.show_loggings"),
            kind=wx.ITEM_CHECK,
        )
        view_menu.AppendSeparator()
        _append_menu_item(
            view_menu,
            self.ID_SHOW_TOOLBAR,
            t("menu.show_toolbar"),
            kind=wx.ITEM_CHECK,
        )
        _append_menu_item(
            view_menu,
            self.ID_LARGE_TOOLS,
            t("menu.large_tools"),
            kind=wx.ITEM_CHECK,
        )
        _append_menu_item(
            view_menu,
            self.ID_SHOW_TOOL_LABELS,
            t("menu.show_tool_labels"),
            kind=wx.ITEM_CHECK,
        )
        view_menu.Check(self.ID_SHOW_DIRECTORY, self._directory_tree_visible)
        view_menu.Check(self.ID_SHOW_LOG, self._log_panel_visible)
        view_menu.Check(self.ID_SHOW_TOOLBAR, self._toolbar_visible)
        view_menu.Check(self.ID_LARGE_TOOLS, self.app_settings.large_tools)
        view_menu.Check(self.ID_SHOW_TOOL_LABELS, self.app_settings.show_tool_labels)

        lang_menu = wx.Menu()
        self._lang_menu_ids: dict[str, int] = {}
        for code in SUPPORTED_LOCALES:
            item_id = wx.NewIdRef()
            self._lang_menu_ids[code] = int(item_id)
            lang_menu.Append(item_id, t(f"lang.{code}"))

        menubar.Append(file_menu, t("menu.file"))
        menubar.Append(edit_menu, t("menu.edit"))
        menubar.Append(view_menu, t("menu.view"))
        menubar.Append(lang_menu, t("menu.language"))
        self.SetMenuBar(menubar)
        self._file_menu = file_menu
        self._edit_menu = edit_menu
        self._view_menu = view_menu
        self._lang_menu = lang_menu

    def _register_drop_targets(self) -> None:
        drop = _PathDropTarget(self._import_dropped_paths)
        self.SetDropTarget(drop)
        self._file_list.SetDropTarget(_PathDropTarget(self._import_dropped_paths))

    def _init_directory_tree(self) -> None:
        if not self._directory_tree_ui_active():
            self._tree_needs_init = True
            return
        self._tree_needs_init = False
        self._dir_tree.DeleteAllItems()
        root_path = Path("/")
        root = self._dir_tree.AddRoot("/")
        self._dir_tree.SetItemData(root, root_path)
        self._tree_root_item = root
        if list_subdirectories(root_path):
            placeholder = self._dir_tree.AppendItem(root, TREE_DUMMY_LABEL)
            self._dir_tree.SetItemData(placeholder, None)

    def _tree_append_dir_node(self, parent: wx.TreeItemId, path: Path) -> wx.TreeItemId:
        label = path.name or str(path)
        item = self._dir_tree.AppendItem(parent, label)
        self._dir_tree.SetItemData(item, path)
        if list_subdirectories(path):
            placeholder = self._dir_tree.AppendItem(item, TREE_DUMMY_LABEL)
            self._dir_tree.SetItemData(placeholder, None)
        return item

    def _tree_find_child(self, parent: wx.TreeItemId, path: Path) -> wx.TreeItemId | None:
        try:
            target = path.resolve()
        except OSError:
            target = path
        child, cookie = self._dir_tree.GetFirstChild(parent)
        while child.IsOk():
            data = self._dir_tree.GetItemData(child)
            if isinstance(data, Path):
                try:
                    if data.resolve() == target:
                        return child
                except OSError:
                    if data == path:
                        return child
            child, cookie = self._dir_tree.GetNextChild(parent, cookie)
        return None

    def _tree_populate_children(self, item: wx.TreeItemId, path: Path) -> None:
        if not self._dir_tree.ItemHasChildren(item):
            return
        first, _cookie = self._dir_tree.GetFirstChild(item)
        if first.IsOk() and self._dir_tree.GetItemText(first) == TREE_DUMMY_LABEL:
            self._dir_tree.DeleteChildren(item)
            for child_path in list_subdirectories(path):
                self._tree_append_dir_node(item, child_path)

    def _on_dir_tree_expanding(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        data = self._dir_tree.GetItemData(item)
        if isinstance(data, Path):
            self._tree_populate_children(item, data)
        event.Skip()

    def _on_dir_tree_sel_changed(self, event: wx.TreeEvent) -> None:
        if self._tree_selecting:
            event.Skip()
            return
        item = event.GetItem()
        data = self._dir_tree.GetItemData(item)
        if isinstance(data, Path) and data.is_dir():
            self._load_directory_files(data)
        event.Skip()

    def _set_breadcrumbs(self, directory: Path) -> None:
        self._breadcrumb_sizer.Clear(delete_windows=True)
        segments = path_breadcrumb_segments(directory)
        for index, (label, segment_path) in enumerate(segments):
            if index > 0:
                chevron = _FlatLinkButton(self._breadcrumb_panel, ">")
                chevron.SetToolTip(t("tooltip.breadcrumb_siblings"))
                chevron.BindClick(
                    lambda path=segment_path, btn=chevron: self._on_breadcrumb_siblings(
                        path,
                        btn,
                    ),
                )
                self._breadcrumb_sizer.Add(chevron, 0, wx.ALIGN_CENTER_VERTICAL)
            button = _FlatLinkButton(self._breadcrumb_panel, label)
            button.SetToolTip(str(segment_path))
            button.BindClick(
                lambda path=segment_path: self._navigate_from_breadcrumb(path),
            )
            self._breadcrumb_sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL)
        self._apply_breadcrumb_nav_colours()
        self._breadcrumb_panel.Layout()

    def _breadcrumb_nav_background(self) -> wx.Colour:
        return self._content_wrap.GetBackgroundColour()

    def _apply_breadcrumb_nav_colours(self) -> None:
        if not hasattr(self, "_content_wrap"):
            return
        bg = self._breadcrumb_nav_background()
        if hasattr(self, "_breadcrumb_bar"):
            self._breadcrumb_bar.SetBackgroundColour(bg)
        if hasattr(self, "_breadcrumb_panel"):
            self._breadcrumb_panel.SetBackgroundColour(bg)
        if hasattr(self, "_breadcrumb_sizer"):
            for index in range(self._breadcrumb_sizer.GetItemCount()):
                window = self._breadcrumb_sizer.GetItem(index).GetWindow()
                if isinstance(window, _FlatLinkButton):
                    window._apply_colours()
                elif isinstance(window, wx.StaticText):
                    window.SetBackgroundColour(bg)

    def _on_breadcrumb_siblings(
        self,
        segment_path: Path,
        anchor: wx.Window,
    ) -> None:
        parent_dir = segment_path.parent
        siblings = list_subdirectories(parent_dir)
        if not siblings:
            return

        menu = wx.Menu()
        for sibling in siblings:
            item_id = wx.NewIdRef()
            item_label = sibling.name
            if sibling == segment_path:
                item_label = f"✓ {item_label}"
            menu.Append(item_id, item_label)
            self.Bind(
                wx.EVT_MENU,
                lambda event, path=sibling: self._navigate_from_breadcrumb(path),
                id=item_id,
            )

        pos = anchor.GetScreenPosition()
        size = anchor.GetSize()
        self._breadcrumb_panel.PopupMenu(
            menu,
            self._breadcrumb_panel.ScreenToClient(wx.Point(pos.x, pos.y + size.height)),
        )
        menu.Destroy()

    def _navigate_from_breadcrumb(self, directory: Path) -> None:
        if self._converting_active or self._import_active:
            return
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            return
        self._select_tree_directory(directory)
        self._load_directory_files(directory)

    def _toolbar_bitmap_size(self) -> wx.Size:
        side = (
            TOOLBAR_BITMAP_LARGE
            if self.app_settings.large_tools
            else TOOLBAR_BITMAP_MEDIUM
        )
        return wx.Size(side, side)

    def _toolbar_tool_art(self) -> tuple[tuple[int, str], ...]:
        return (
            (self.ID_OPEN_DIRECTORY, wx.ART_FOLDER_OPEN),
            (self.ID_OPEN_SESSION, wx.ART_FILE_OPEN),
            (self.ID_IMPORT_PHONE, wx.ART_GO_DOWN),
            (self.ID_SHOW_DIRECTORY, wx.ART_LIST_VIEW),
            (self.ID_SHOW_LOG, wx.ART_INFORMATION),
            (self.ID_SETTINGS, wx.ART_HELP_SETTINGS),
            (self.ID_CONVERT, wx.ART_EXECUTABLE_FILE),
        )

    def _home_nav_bitmap_size(self) -> wx.Size:
        side = 16 if not self.app_settings.large_tools else 20
        return wx.Size(side, side)

    def _build_home_nav_button(self, parent: wx.Window) -> wx.Button:
        bitmap = wx.ArtProvider.GetBitmap(
            wx.ART_GO_HOME,
            wx.ART_TOOLBAR,
            self._home_nav_bitmap_size(),
        )
        button = wx.Button(parent, label=t("button.home"))
        if bitmap.IsOk():
            button.SetBitmap(bitmap)
        button.Bind(wx.EVT_BUTTON, lambda _event: self._on_toolbar_home())
        self._home_nav_button = button
        return button

    def _update_home_nav_button(self) -> None:
        if not hasattr(self, "_home_nav_button"):
            return
        button = self._home_nav_button
        button.SetLabel(t("button.home"))
        bitmap = wx.ArtProvider.GetBitmap(
            wx.ART_GO_HOME,
            wx.ART_TOOLBAR,
            self._home_nav_bitmap_size(),
        )
        if bitmap.IsOk():
            button.SetBitmap(bitmap)
        self._breadcrumb_bar.Layout()

    def _sync_convert_controls(self, enabled: bool | None = None) -> None:
        if enabled is None:
            enabled = not self._converting_active
        if hasattr(self, "_main_toolbar"):
            self._main_toolbar.EnableTool(self.ID_CONVERT, enabled)
        if hasattr(self, "_btn_convert"):
            self._btn_convert.Enable(enabled)

    def _on_convert_clicked(self, _event: wx.CommandEvent) -> None:
        self.convert_pending()

    def _apply_toolbar_size(self) -> None:
        if not hasattr(self, "_main_toolbar"):
            return
        toolbar = self._main_toolbar
        size = self._toolbar_bitmap_size()
        toolbar.SetToolBitmapSize(size)
        for tool_id, art_id in self._toolbar_tool_art():
            bitmap = wx.ArtProvider.GetBitmap(art_id, wx.ART_TOOLBAR, size)
            toolbar.SetToolNormalBitmap(tool_id, bitmap)
        convert_enabled = not self._converting_active
        self._sync_convert_controls(convert_enabled)
        toolbar.Realize()
        self._update_home_nav_button()
        self._breadcrumb_bar.Layout()
        self.Layout()

    def _toolbar_tool_label(self, key: str) -> str:
        if self.app_settings.show_tool_labels:
            return t(key)
        return ""

    def _build_main_toolbar(self, parent: wx.Window) -> wx.ToolBar:
        style = wx.TB_FLAT | wx.TB_NODIVIDER
        if self.app_settings.show_tool_labels:
            style |= wx.TB_TEXT
        toolbar = wx.ToolBar(parent, style=style)
        bitmap_size = self._toolbar_bitmap_size()
        toolbar.SetToolBitmapSize(bitmap_size)
        self._main_toolbar = toolbar

        def stock(art_id: str) -> wx.Bitmap:
            return wx.ArtProvider.GetBitmap(art_id, wx.ART_TOOLBAR, bitmap_size)

        def add_tool(
            tool_id: int,
            key: str,
            art_id: str,
            kind: int = wx.ITEM_NORMAL,
        ) -> None:
            help_text = t(key)
            toolbar.AddTool(
                tool_id,
                self._toolbar_tool_label(key),
                stock(art_id),
                help_text,
                kind,
            )

        add_tool(self.ID_OPEN_DIRECTORY, "toolbar.location", wx.ART_FOLDER_OPEN)
        add_tool(self.ID_OPEN_SESSION, "toolbar.open_session", wx.ART_FILE_OPEN)
        toolbar.AddSeparator()
        add_tool(self.ID_IMPORT_PHONE, "toolbar.import_phone", wx.ART_GO_DOWN)
        toolbar.AddSeparator()
        add_tool(
            self.ID_SHOW_DIRECTORY,
            "toolbar.toggle_tree",
            wx.ART_LIST_VIEW,
            wx.ITEM_CHECK,
        )
        add_tool(
            self.ID_SHOW_LOG,
            "toolbar.toggle_log",
            wx.ART_INFORMATION,
            wx.ITEM_CHECK,
        )
        toolbar.AddSeparator()
        add_tool(self.ID_SETTINGS, "toolbar.settings", wx.ART_HELP_SETTINGS)
        toolbar.AddSeparator()
        add_tool(self.ID_CONVERT, "toolbar.convert", wx.ART_EXECUTABLE_FILE)
        toolbar.Realize()
        self._sync_toolbar_toggles()
        return toolbar

    def _refresh_main_toolbar(self) -> None:
        if not hasattr(self, "_breadcrumb_bar") or not hasattr(self, "_main_toolbar"):
            return
        old = self._main_toolbar
        convert_enabled = old.GetToolEnabled(self.ID_CONVERT)
        sizer = old.GetContainingSizer()
        if sizer is None:
            return
        toolbar = self._build_main_toolbar(self._breadcrumb_bar)
        if not sizer.Replace(old, toolbar):
            toolbar.Destroy()
            return
        old.Destroy()
        self._sync_convert_controls(convert_enabled)
        self._sync_toolbar_toggles()
        self._apply_toolbar_visibility(self._toolbar_visible)
        self._breadcrumb_bar.Layout()
        self.Layout()

    def _apply_toolbar_visibility(self, visible: bool) -> None:
        if visible == self._toolbar_visible and hasattr(self, "_main_toolbar"):
            if self._main_toolbar.IsShown() == visible:
                self._view_menu.Check(self.ID_SHOW_TOOLBAR, visible)
                return
        self._toolbar_visible = visible
        self._view_menu.Check(self.ID_SHOW_TOOLBAR, visible)
        if hasattr(self, "_main_toolbar"):
            self._main_toolbar.Show(visible)
            toolbar_sizer = self._main_toolbar.GetContainingSizer()
            if toolbar_sizer is not None:
                item = toolbar_sizer.GetItem(self._main_toolbar)
                if item is not None:
                    item.Show(visible)
        self._breadcrumb_bar.Layout()
        self._refresh_workspace_layout()

    def _on_show_toolbar_menu(self, event: wx.CommandEvent) -> None:
        self._apply_toolbar_visibility(event.IsChecked())

    def _update_toolbar_labels(self) -> None:
        self._refresh_main_toolbar()

    def _on_show_tool_labels_menu(self, event: wx.CommandEvent) -> None:
        show = event.IsChecked()
        if show == self.app_settings.show_tool_labels:
            self._view_menu.Check(self.ID_SHOW_TOOL_LABELS, show)
            return
        self.app_settings.show_tool_labels = show
        self._view_menu.Check(self.ID_SHOW_TOOL_LABELS, show)
        save_app_settings(self.app_settings)
        self._update_toolbar_labels()

    def _sync_toolbar_toggles(self) -> None:
        if not hasattr(self, "_main_toolbar"):
            return
        self._main_toolbar.ToggleTool(self.ID_SHOW_DIRECTORY, self._directory_tree_visible)
        self._main_toolbar.ToggleTool(self.ID_SHOW_LOG, self._log_panel_visible)

    def _on_toolbar_home(self, _event: wx.CommandEvent | None = None) -> None:
        target = self.app_settings.recordings_location.expanduser()
        target.mkdir(parents=True, exist_ok=True)
        self._select_tree_directory(target)
        self._load_directory_files(target)

    def _on_large_tools_menu(self, event: wx.CommandEvent) -> None:
        large = event.IsChecked()
        if large == self.app_settings.large_tools:
            self._view_menu.Check(self.ID_LARGE_TOOLS, large)
            return
        self.app_settings.large_tools = large
        self._view_menu.Check(self.ID_LARGE_TOOLS, large)
        self._apply_toolbar_size()

    def _restore_layout(self) -> None:
        if self.app_settings.window_x is not None and self.app_settings.window_y is not None:
            self.SetPosition(wx.Point(self.app_settings.window_x, self.app_settings.window_y))
        elif not self.app_settings.window_maximized:
            self.Centre()

        if self.app_settings.splitter_main_pos:
            self._splitter_main.SetSashPosition(
                self._clamp_file_splitter_sash(self.app_settings.splitter_main_pos)
            )
        self._apply_directory_tree_visibility(
            self.app_settings.directory_tree_visible,
            from_toggle=False,
        )
        if self._directory_tree_visible and self.app_settings.splitter_browser_pos:
            self._splitter_browser_pos = self.app_settings.splitter_browser_pos
            self._sync_tree_column_width()
        self._apply_log_panel_visibility(self.app_settings.log_panel_visible)
        self._apply_toolbar_visibility(self.app_settings.toolbar_visible)
        self._file_menu.Check(self.ID_REFRESH_MODELS, self.settings.refresh_models)
        self._view_menu.Check(self.ID_LARGE_TOOLS, self.app_settings.large_tools)
        self._view_menu.Check(self.ID_SHOW_TOOL_LABELS, self.app_settings.show_tool_labels)

        if self.app_settings.window_maximized:
            self.Maximize(True)

        if not self._log_panel_visible:
            wx.CallAfter(self._expand_content_to_main_splitter)
        else:
            self._refresh_workspace_layout()

    def _clamped_log_height(self, total_height: int) -> int:
        if total_height <= 0:
            return self._log_sash_height
        max_log = max(LOG_PANEL_MIN_HEIGHT, total_height - MIN_CONTENT_HEIGHT)
        return max(LOG_PANEL_MIN_HEIGHT, min(self._log_sash_height, max_log))

    def _top_pane_height(self, total_height: int) -> int:
        if total_height <= 0:
            return MIN_CONTENT_HEIGHT
        log_height = self._clamped_log_height(total_height)
        top = total_height - log_height
        top = min(top, total_height - LOG_PANEL_MIN_HEIGHT)
        return max(1, top)

    def _content_sash_position(self, total_height: int) -> int:
        log_height = self._clamped_log_height(total_height)
        if total_height <= 0:
            return -log_height
        return self._top_pane_height(total_height)

    def _save_layout_settings(self) -> None:
        if self.IsMaximized():
            self.app_settings.window_maximized = True
        else:
            self.app_settings.window_maximized = False
            size = self.GetSize()
            pos = self.GetPosition()
            self.app_settings.window_width = size.width
            self.app_settings.window_height = size.height
            self.app_settings.window_x = pos.x
            self.app_settings.window_y = pos.y
        if self._splitter_main.IsSplit():
            sash = self._splitter_main.GetSashPosition()
            if sash > 0:
                self.app_settings.splitter_main_pos = sash
        self.app_settings.splitter_browser_pos = self._splitter_browser_pos
        self.app_settings.log_sash_height = self._log_sash_height
        self.app_settings.directory_tree_visible = self._directory_tree_visible
        self.app_settings.log_panel_visible = self._log_panel_visible
        self.app_settings.toolbar_visible = self._toolbar_visible
        self.app_settings.ui_lang = self.settings.ui_lang
        self.app_settings.refresh_models = self.settings.refresh_models
        save_app_settings(self.app_settings)

    def _directory_tree_ui_active(self) -> bool:
        if not self._directory_tree_visible:
            return False
        if not hasattr(self, "_browser_splitter"):
            return False
        return self._browser_splitter.IsSplit() and self._tree_panel.IsShown()

    def _flush_deferred_browser_ui(self) -> None:
        if not self._directory_tree_ui_active():
            return
        if self._tree_needs_init or self._tree_root_item is None or not self._tree_root_item.IsOk():
            self._init_directory_tree()
        pending_tree = self._pending_tree_directory
        if pending_tree is not None:
            self._pending_tree_directory = None
            self._select_tree_directory(pending_tree)
        if self._file_list_needs_sync:
            self._file_list_needs_sync = False
            self._sync_file_list(force=True)

    def _clamp_browser_splitter_sash(self, sash: int) -> int:
        if not hasattr(self, "_browser_splitter"):
            return max(MIN_TREE_PANEL_WIDTH, sash)
        client = self._browser_splitter.GetClientSize()
        if client.width <= 0:
            return max(MIN_TREE_PANEL_WIDTH, sash)
        sash_width = self._browser_splitter.GetSashSize()
        min_work = MIN_FILE_PANEL_WIDTH + MIN_CHAT_PANEL_WIDTH + sash_width
        max_tree = client.width - min_work - sash_width
        if max_tree < MIN_TREE_PANEL_WIDTH:
            return MIN_TREE_PANEL_WIDTH
        return max(MIN_TREE_PANEL_WIDTH, min(sash, max_tree))

    def _sync_tree_column_width(self) -> None:
        if not hasattr(self, "_browser_splitter"):
            return
        splitter = self._browser_splitter
        if self._directory_tree_visible:
            splitter.SetMinimumPaneSize(MIN_TREE_PANEL_WIDTH)
            self._tree_panel.Show()
            self._work_panel.Show()
            sash = self._clamp_browser_splitter_sash(self._splitter_browser_pos)
            if not splitter.IsSplit():
                splitter.SplitVertically(self._tree_panel, self._work_panel, sash)
            else:
                splitter.SetSashPosition(sash)
        else:
            if splitter.IsSplit():
                current = splitter.GetSashPosition()
                if current > 0:
                    self._splitter_browser_pos = current
                splitter.Unsplit(self._tree_panel)
            splitter.SetMinimumPaneSize(0)
        splitter.Layout()
        if self._directory_tree_visible:
            self._flush_deferred_browser_ui()

    def _on_browser_splitter_changing(self, event: wx.SplitterEvent) -> None:
        sash = self._clamp_browser_splitter_sash(event.GetSashPosition())
        if sash != event.GetSashPosition():
            event.SetSashPosition(sash)
        event.Skip()

    def _on_browser_splitter_changed(self, event: wx.SplitterEvent) -> None:
        if self._browser_splitter.IsSplit():
            sash = self._browser_splitter.GetSashPosition()
            if sash > 0:
                self._splitter_browser_pos = sash
        event.Skip()

    def _apply_directory_tree_visibility(
        self,
        visible: bool,
        *,
        from_toggle: bool = True,
    ) -> None:
        del from_toggle
        if visible == self._directory_tree_visible:
            self._view_menu.Check(self.ID_SHOW_DIRECTORY, visible)
            self._sync_toolbar_toggles()
            return
        self._directory_tree_visible = visible
        self._view_menu.Check(self.ID_SHOW_DIRECTORY, visible)
        self._sync_tree_column_width()
        self._sync_toolbar_toggles()
        self._refresh_workspace_layout()

    def _refresh_workspace_layout(self) -> None:
        self._main_splitter.Layout()
        self._content_wrap.Layout()
        if hasattr(self, "_browser_splitter"):
            self._browser_splitter.Layout()
        self._work_panel.Layout()
        self._splitter_main.Layout()
        parent = self._main_splitter.GetParent()
        if parent is not None:
            parent.Layout()
        self.Layout()

    def _expand_content_to_main_splitter(self) -> None:
        client = self._main_splitter.GetClientSize()
        if client.width > 0 and client.height > 0:
            self._content_wrap.SetSize(client)
        self._refresh_workspace_layout()

    def _on_directory_tree_menu(self, event: wx.CommandEvent) -> None:
        self._apply_directory_tree_visibility(event.IsChecked())

    def _on_show_log_menu(self, event: wx.CommandEvent) -> None:
        self._apply_log_panel_visibility(event.IsChecked())

    def _on_refresh_models_menu(self, event: wx.CommandEvent) -> None:
        refresh = event.IsChecked()
        if refresh == self.settings.refresh_models:
            return
        self.settings.refresh_models = refresh
        if self._backend is not None:
            self._backend.unload()
            self._backend = None

    def _clamp_file_splitter_sash(self, sash: int) -> int:
        client = self._splitter_main.GetClientSize()
        if client.width <= 0:
            return max(MIN_FILE_PANEL_WIDTH, sash)
        sash_width = self._splitter_main.GetSashSize()
        max_file = client.width - MIN_CHAT_PANEL_WIDTH - sash_width
        if max_file < MIN_FILE_PANEL_WIDTH:
            return MIN_FILE_PANEL_WIDTH
        return max(MIN_FILE_PANEL_WIDTH, min(sash, max_file))

    def _on_splitter_main_changing(self, event: wx.SplitterEvent) -> None:
        sash = self._clamp_file_splitter_sash(event.GetSashPosition())
        if sash != event.GetSashPosition():
            event.SetSashPosition(sash)
        event.Skip()

    def _on_splitter_main_changed(self, event: wx.SplitterEvent) -> None:
        if self._splitter_main.IsSplit():
            sash = self._splitter_main.GetSashPosition()
            if sash > 0:
                self._splitter_file_pos = sash
        event.Skip()

    def _load_directory_files(self, directory: Path) -> None:
        if self._converting_active or self._import_active:
            return
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            return

        self._current_directory = directory
        self._set_breadcrumbs(directory)
        self._persist_browser_directory(directory)
        self._search_box.SetValue("")
        self._search_keywords = []
        self._selection_explicit_empty = True
        self.entries.clear()

        for path in _list_directory_paths(directory):
            self._append_entry(path)

        self.focus_index = None
        self._sync_file_list()
        self._deselect_all_file_rows()
        self._clear_session_view()

    def refresh_browser(self) -> None:
        if self._converting_active or self._import_active:
            return
        directory = self._current_directory
        if directory is None:
            raw = self.app_settings.last_browser_directory
            directory = raw if raw is not None else Path.home()
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            return
        if self._directory_tree_ui_active():
            self._init_directory_tree()
            self._select_tree_directory(directory)
        else:
            self._tree_needs_init = True
            self._pending_tree_directory = directory
        self._load_directory_files(directory)

    def _select_tree_directory(self, directory: Path) -> None:
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            directory = directory.parent
        if not self._directory_tree_ui_active():
            self._pending_tree_directory = directory
            return
        item = self._ensure_tree_item(directory)
        if item is None or not item.IsOk():
            return
        self._tree_selecting = True
        try:
            self._dir_tree.SelectItem(item)
            self._dir_tree.EnsureVisible(item)
        finally:
            wx.CallAfter(self._release_tree_selecting)

    def _release_tree_selecting(self) -> None:
        self._tree_selecting = False

    def _ensure_tree_item(self, directory: Path) -> wx.TreeItemId | None:
        try:
            directory = directory.resolve()
        except OSError:
            return None
        if self._tree_root_item is None or not self._tree_root_item.IsOk():
            self._init_directory_tree()
        item = self._dir_tree.GetRootItem()
        if not item.IsOk():
            return None
        root_data = self._dir_tree.GetItemData(item)
        if isinstance(root_data, Path):
            current = root_data
        else:
            current = Path("/")

        try:
            rel_parts = directory.relative_to(current).parts
        except ValueError:
            current = Path(directory.anchor)
            item = self._dir_tree.GetRootItem()
            try:
                rel_parts = directory.relative_to(current).parts
            except ValueError:
                return item if item.IsOk() else None

        for part in rel_parts:
            current = current / part
            child = self._tree_find_child(item, current)
            if child is None:
                parent_data = self._dir_tree.GetItemData(item)
                if isinstance(parent_data, Path):
                    self._tree_populate_children(item, parent_data)
                child = self._tree_find_child(item, current)
                if child is None:
                    child = self._tree_append_dir_node(item, current)
            item = child
            self._dir_tree.Expand(item)
        return item

    def _bind_events(self) -> None:
        self.Bind(wx.EVT_MENU, lambda _e: self.open_directory(), id=self.ID_OPEN_DIRECTORY)
        self.Bind(wx.EVT_MENU, lambda _e: self.open_chat_session(), id=self.ID_OPEN_SESSION)
        self.Bind(wx.EVT_MENU, lambda _e: self.import_from_phone(), id=self.ID_IMPORT_PHONE)
        self.Bind(wx.EVT_MENU, self._on_refresh_models_menu, id=self.ID_REFRESH_MODELS)
        self.Bind(wx.EVT_MENU, lambda _e: self.refresh_browser(), id=self.ID_REFRESH_BROWSER)
        self.Bind(wx.EVT_MENU, lambda _e: self.open_settings(), id=self.ID_SETTINGS)
        self.Bind(wx.EVT_MENU, self._on_directory_tree_menu, id=self.ID_SHOW_DIRECTORY)
        self.Bind(wx.EVT_MENU, self._on_show_log_menu, id=self.ID_SHOW_LOG)
        self.Bind(wx.EVT_MENU, self._on_show_toolbar_menu, id=self.ID_SHOW_TOOLBAR)
        self.Bind(wx.EVT_MENU, self._on_large_tools_menu, id=self.ID_LARGE_TOOLS)
        self.Bind(wx.EVT_MENU, self._on_show_tool_labels_menu, id=self.ID_SHOW_TOOL_LABELS)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=self.ID_EXIT)
        self.Bind(wx.EVT_TOOL, lambda _e: self.open_directory(), id=self.ID_OPEN_DIRECTORY)
        self.Bind(wx.EVT_TOOL, lambda _e: self.open_chat_session(), id=self.ID_OPEN_SESSION)
        self.Bind(wx.EVT_TOOL, lambda _e: self.import_from_phone(), id=self.ID_IMPORT_PHONE)
        self.Bind(wx.EVT_TOOL, self._on_directory_tree_menu, id=self.ID_SHOW_DIRECTORY)
        self.Bind(wx.EVT_TOOL, self._on_show_log_menu, id=self.ID_SHOW_LOG)
        self.Bind(wx.EVT_TOOL, lambda _e: self.open_settings(), id=self.ID_SETTINGS)
        self.Bind(wx.EVT_TOOL, lambda _e: self.convert_pending(), id=self.ID_CONVERT)
        for code, item_id in self._lang_menu_ids.items():
            self.Bind(
                wx.EVT_MENU,
                lambda event, locale=code: self.set_language(locale),
                id=item_id,
            )

        self._dir_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_dir_tree_sel_changed)
        self._dir_tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._on_dir_tree_expanding)
        self._spin_min_speakers.BindValueChanged(self._on_min_speakers_changed)
        self._spin_max_speakers.BindValueChanged(self._on_max_speakers_changed)
        self._main_splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_log_splitter_changed)
        self._browser_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGING,
            self._on_browser_splitter_changing,
        )
        self._browser_splitter.Bind(
            wx.EVT_SPLITTER_SASH_POS_CHANGED,
            self._on_browser_splitter_changed,
        )
        self._splitter_main.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGING, self._on_splitter_main_changing)
        self._splitter_main.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_splitter_main_changed)
        self._file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_file_selected)
        self._file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_file_deselected)
        self._file_list.Bind(wx.EVT_LEFT_DOWN, self._on_file_list_left_down)
        self._file_list.Bind(wx.EVT_MOTION, self._on_file_list_motion)
        self._file_list.Bind(wx.EVT_LEAVE_WINDOW, self._on_file_list_leave)
        self._file_list.Bind(wx.EVT_KEY_DOWN, self._on_file_list_key_down)
        self._file_list.Bind(wx.EVT_SIZE, self._on_file_list_size)
        self._search_box.Bind(wx.EVT_TEXT, self._on_search_changed)
        self._search_box.Bind(wx.EVT_TEXT_ENTER, self._on_search_submit)
        self._search_box.Bind(wx.EVT_SET_FOCUS, self._on_search_focus)
        self._search_box.Bind(wx.EVT_KILL_FOCUS, self._on_search_kill_focus)
        self._rb_list.Bind(wx.EVT_RADIOBUTTON, self._on_view_changed)
        self._rb_bubbles.Bind(wx.EVT_RADIOBUTTON, self._on_view_changed)
        self._list_panel.Bind(wx.EVT_SIZE, self._on_list_panel_size)
        self._bubble_panel.Bind(wx.EVT_SIZE, self._on_bubble_panel_size)

        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_SIZE, self._on_frame_size)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self._accel_table = wx.AcceleratorTable(
            [
                (wx.ACCEL_CTRL, ord("L"), self.ID_OPEN_DIRECTORY),
                (wx.ACCEL_CTRL, ord("O"), self.ID_OPEN_SESSION),
                (wx.ACCEL_CTRL, ord("I"), self.ID_IMPORT_PHONE),
                (wx.ACCEL_CTRL, ord("R"), self.ID_REFRESH_BROWSER),
                (wx.ACCEL_NORMAL, wx.WXK_F7, self.ID_SETTINGS),
                (wx.ACCEL_CTRL, ord("Q"), self.ID_EXIT),
            ]
        )
        self.SetAcceleratorTable(self._accel_table)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.HasAnyModifiers():
            event.Skip()
            return
        key = event.GetKeyCode()
        if key == wx.WXK_F2:
            self._apply_directory_tree_visibility(not self._directory_tree_visible)
            return
        if key == wx.WXK_F4:
            self._apply_log_panel_visibility(not self._log_panel_visible)
            return
        if key == wx.WXK_F6:
            self._apply_toolbar_visibility(not self._toolbar_visible)
            return
        if key == wx.WXK_F7:
            self.open_settings()
            return
        event.Skip()

    def _on_frame_size(self, event: wx.SizeEvent) -> None:
        if not self._log_panel_visible:
            self._expand_content_to_main_splitter()
        if self._splitter_main.IsSplit():
            sash = self._splitter_main.GetSashPosition()
            clamped = self._clamp_file_splitter_sash(sash)
            if clamped != sash:
                self._splitter_main.SetSashPosition(clamped)
        if (
            self._directory_tree_visible
            and hasattr(self, "_browser_splitter")
            and self._browser_splitter.IsSplit()
        ):
            sash = self._browser_splitter.GetSashPosition()
            clamped = self._clamp_browser_splitter_sash(sash)
            if clamped != sash:
                self._browser_splitter.SetSashPosition(clamped)
        event.Skip()

    def _set_status(self, key: str, **kwargs: object) -> None:
        self._status_key = key
        self._status_kwargs = kwargs
        statusbar = self.GetStatusBar()
        if statusbar is not None:
            statusbar.SetStatusText(t(key, **kwargs), 0)

    def _set_status_text(self, text: str) -> None:
        statusbar = self.GetStatusBar()
        if statusbar is not None:
            statusbar.SetStatusText(text, 0)

    def _report_conversion_progress(
        self,
        *,
        file_index: int,
        file_total: int,
        name: str,
        phase: str,
        file_percent: int | None = None,
    ) -> None:
        kwargs: dict[str, object] = {
            "current": file_index + 1,
            "total": file_total,
            "name": name,
            "phase": t(f"phase.{phase}"),
        }
        if file_percent is not None:
            overall = int(((file_index * 100) + file_percent) / file_total)
            kwargs["percent"] = max(0, min(100, overall))
            self._set_status("status.progress_pct", **kwargs)
            self._set_progress(int(kwargs["percent"]))
            log_key = "status.progress_pct"
        else:
            self._set_status("status.progress", **kwargs)
            log_key = "status.progress"

        should_log = (
            phase != self._last_progress_log_phase
            or file_percent is None
            or self._last_progress_log_percent is None
            or file_percent - self._last_progress_log_percent >= 5
            or file_percent >= 95
        )
        if should_log:
            self._append_log(logging.INFO, t(log_key, **kwargs))
            self._last_progress_log_phase = phase
            if file_percent is not None:
                self._last_progress_log_percent = file_percent

    def _on_log_splitter_changed(self, event: wx.SplitterEvent) -> None:
        if self._log_panel_visible and self._main_splitter.IsSplit():
            sash = self._main_splitter.GetSashPosition()
            height = self._main_splitter.GetClientSize().height
            self._log_sash_height = max(LOG_PANEL_MIN_HEIGHT, height - sash)
        event.Skip()

    def _apply_log_panel_visibility(self, visible: bool) -> None:
        if visible == self._log_panel_visible:
            self._view_menu.Check(self.ID_SHOW_LOG, visible)
            self._sync_toolbar_toggles()
            return
        self._log_panel_visible = visible
        self._view_menu.Check(self.ID_SHOW_LOG, visible)

        total_height = self._main_splitter.GetClientSize().height
        if total_height <= 0:
            total_height = max(1, self.GetClientSize().height - 40)

        if visible:
            self._log_wrap.Show()
            self._main_splitter.SetMinimumPaneSize(LOG_PANEL_MIN_HEIGHT)
            log_height = self._clamped_log_height(total_height)
            if not self._main_splitter.IsSplit():
                self._main_splitter.SplitHorizontally(
                    self._content_wrap,
                    self._log_wrap,
                    -log_height,
                )
            elif total_height > log_height + LOG_PANEL_MIN_HEIGHT:
                self._main_splitter.SetSashPosition(self._top_pane_height(total_height))
        else:
            if self._main_splitter.IsSplit():
                height = self._main_splitter.GetClientSize().height
                if height > 0:
                    sash = self._main_splitter.GetSashPosition()
                    self._log_sash_height = max(LOG_PANEL_MIN_HEIGHT, height - sash)
                self._main_splitter.Unsplit(self._log_wrap)
            self._main_splitter.SetMinimumPaneSize(0)

        self._content_wrap.Show()
        self._sync_toolbar_toggles()
        if visible:
            self._refresh_workspace_layout()
        else:
            wx.CallAfter(self._expand_content_to_main_splitter)

    def _make_conversion_progress(
        self,
        file_index: int,
        file_total: int,
        name: str,
    ):
        def report(phase: str, file_percent: int | None = None) -> None:
            self._ui_queue.put(
                (
                    "progress",
                    {
                        "file_index": file_index,
                        "file_total": file_total,
                        "name": name,
                        "phase": phase,
                        "file_percent": file_percent,
                    },
                )
            )

        return report

    def set_language(self, locale: str) -> None:
        set_locale(locale)
        self.settings.ui_lang = locale
        self.app_settings.ui_lang = locale
        save_app_settings(self.app_settings)
        self._apply_locale()

    def _apply_locale(self) -> None:
        self.SetTitle(t("app.window_title"))
        menubar = self.GetMenuBar()
        if menubar:
            menubar.SetMenuLabel(0, t("menu.file"))
            menubar.SetMenuLabel(1, t("menu.edit"))
            menubar.SetMenuLabel(2, t("menu.view"))
            menubar.SetMenuLabel(3, t("menu.language"))

        self._file_menu.SetLabel(self.ID_OPEN_DIRECTORY, t("menu.open_directory"))
        self._file_menu.SetLabel(self.ID_OPEN_SESSION, t("menu.open_chat_session"))
        self._file_menu.SetLabel(self.ID_IMPORT_PHONE, t("menu.import_from_phone"))
        self._file_menu.SetLabel(self.ID_REFRESH_MODELS, t("menu.refresh_models"))
        self._file_menu.SetLabel(self.ID_EXIT, t("menu.exit") + "\tCtrl+Q")
        self._edit_menu.SetLabel(self.ID_SETTINGS, t("menu.settings"))
        self._view_menu.SetLabel(self.ID_REFRESH_BROWSER, t("menu.refresh_browser"))
        self._view_menu.SetLabel(self.ID_SHOW_DIRECTORY, t("menu.show_directory"))
        self._view_menu.SetLabel(self.ID_SHOW_LOG, t("menu.show_loggings"))
        self._view_menu.SetLabel(self.ID_SHOW_TOOLBAR, t("menu.show_toolbar"))
        self._view_menu.SetLabel(self.ID_LARGE_TOOLS, t("menu.large_tools"))
        self._view_menu.SetLabel(self.ID_SHOW_TOOL_LABELS, t("menu.show_tool_labels"))
        for code, item_id in self._lang_menu_ids.items():
            self._lang_menu.SetLabel(item_id, t(f"lang.{code}"))

        self._label_files.SetLabel(t("label.files"))
        try:
            if not self._search_box.HasFocus():
                self._search_box.SetHint(t("hint.search"))
        except AttributeError:
            pass
        self._label_speaker_count.SetLabel(t("label.speaker_count"))
        self._label_speaker_to.SetLabel(t("label.speaker_count_to"))
        self._label_speaker_unit.SetLabel(t("label.speaker_count_unit"))
        self._update_toolbar_labels()
        self._update_home_nav_button()
        if self._current_directory is not None:
            self._set_breadcrumbs(self._current_directory)
        self._chk_auto_convert.SetLabel(t("button.auto_convert"))
        if hasattr(self, "_btn_convert"):
            self._btn_convert.SetLabel(t("button.convert"))
            play_bitmap = _play_stock_bitmap()
            if play_bitmap.IsOk():
                self._btn_convert.SetBitmap(play_bitmap)
                self._btn_convert.SetBitmapPosition(wx.LEFT)
        self._label_view.SetLabel(t("label.view"))
        self._rb_list.SetLabel(t("view.list"))
        self._rb_bubbles.SetLabel(t("view.bubbles"))
        col = self._file_list.GetColumn(NAME_COL)
        col.SetText(t("label.file_column"))
        self._file_list.SetColumn(NAME_COL, col)
        self._set_status(self._status_key, **self._status_kwargs)

        if self._phone_import_dialog is not None:
            self._phone_import_dialog.apply_locale()

        if self.focus_index is not None:
            entry = self._entry_at(self.focus_index)
            if entry:
                self._show_entry(entry)
        else:
            self._title_label.SetLabel(t("status.no_session"))
            self._title_label.SetFont(self._ui_font_bold)
            self._meta_label.SetLabel(t("status.select_or_convert"))

        self.Layout()

    def _on_view_changed(self, _event: wx.CommandEvent) -> None:
        self.view_mode = "bubbles" if self._rb_bubbles.GetValue() else "list"
        self._refresh_chat_view()

    def _refresh_chat_view(self) -> None:
        show_bubbles = self.view_mode == "bubbles"
        self._list_panel.Show(not show_bubbles)
        self._bubble_panel.Show(show_bubbles)
        self.Layout()
        entry = self._entry_at(self.focus_index) if self.focus_index is not None else None
        if entry and entry.transcript:
            self._render_transcript(entry)
        else:
            self._clear_chat_view()
        self._fit_chat_panels()

    def _rebuild_visible_entries(self) -> None:
        query = self._search_box.GetValue()
        self._search_keywords = _parse_search_keywords(query)
        if not self._search_keywords:
            self._visible_entry_indices = list(range(len(self.entries)))
        else:
            self._visible_entry_indices = [
                index
                for index, entry in enumerate(self.entries)
                if _entry_matches_keywords(entry, self._search_keywords)
            ]

    def _list_row_for_entry(self, entry_index: int) -> int | None:
        try:
            return self._visible_entry_indices.index(entry_index)
        except ValueError:
            return None

    def _entry_index_at_list_row(self, list_row: int) -> int | None:
        if list_row < 0 or list_row >= len(self._visible_entry_indices):
            return None
        return self._visible_entry_indices[list_row]

    def _list_selected_rows(self) -> list[int]:
        rows: list[int] = []
        item = self._file_list.GetFirstSelected()
        while item != -1:
            rows.append(item)
            item = self._file_list.GetNextSelected(item)
        return rows

    def _on_search_changed(self, _event: wx.CommandEvent) -> None:
        # Do not touch other widgets while typing — rebuilding the file list
        # or handling KillFocus breaks GTK IME composition.
        pass

    def _on_search_focus(self, event: wx.FocusEvent) -> None:
        # Frame accelerators run before child key events and can block IME
        # shortcuts such as Ctrl+` on Linux.
        self.SetAcceleratorTable(wx.AcceleratorTable())
        event.Skip()

    def _on_search_submit(self, _event: wx.CommandEvent) -> None:
        self._search_blur_generation += 1
        self._apply_search_filter(preserve_search_focus=True)

    def _on_search_kill_focus(self, event: wx.FocusEvent) -> None:
        self.SetAcceleratorTable(self._accel_table)
        event.Skip()
        self._search_blur_generation += 1
        generation = self._search_blur_generation
        wx.CallLater(250, lambda: self._commit_search_if_blurred(generation))

    def _commit_search_if_blurred(self, generation: int) -> None:
        if generation != self._search_blur_generation:
            return
        if self._search_box.HasFocus():
            return
        self._apply_search_filter(preserve_search_focus=False)

    def _deselect_all_file_rows(self) -> None:
        for list_row in range(self._file_list.GetItemCount()):
            self._file_list.SetItemState(list_row, 0, wx.LIST_STATE_SELECTED)

    def _convert_target_entry_indices(self) -> list[int]:
        selected = self._selected_entry_indices()
        if selected:
            return selected
        return list(self._visible_entry_indices)

    def _set_file_list_selection(
        self,
        selected_entries: set[int],
        *,
        focus_entry: int | None,
        preserve_search_focus: bool,
    ) -> None:
        if self._selection_explicit_empty:
            selected_entries = set()
            focus_entry = None

        if preserve_search_focus and self._search_box.HasFocus():
            for list_row in range(self._file_list.GetItemCount()):
                self._file_list.SetItemState(list_row, 0, wx.LIST_STATE_SELECTED)
            for entry_index in selected_entries:
                list_row = self._list_row_for_entry(entry_index)
                if list_row is not None:
                    self._file_list.SetItemState(
                        list_row,
                        wx.LIST_STATE_SELECTED,
                        wx.LIST_STATE_SELECTED,
                    )
            if focus_entry is not None:
                list_row = self._list_row_for_entry(focus_entry)
                if list_row is not None:
                    self._file_list.SetItemState(
                        list_row,
                        wx.LIST_STATE_SELECTED,
                        wx.LIST_STATE_SELECTED,
                    )
                    self._file_list.EnsureVisible(list_row)
            return

        for entry_index in selected_entries:
            list_row = self._list_row_for_entry(entry_index)
            if list_row is not None:
                self._file_list.Select(list_row)

        if focus_entry is not None:
            list_row = self._list_row_for_entry(focus_entry)
            if list_row is not None:
                self._file_list.Select(list_row)
                self._file_list.EnsureVisible(list_row)

    def _apply_search_filter(self, *, preserve_search_focus: bool = False) -> None:
        previous_focus = self.focus_index
        selected_entries = set(self._selected_entry_indices())
        self._sync_file_list(
            restore_selection=selected_entries,
            preserve_search_focus=preserve_search_focus,
        )

        if (
            previous_focus is not None
            and previous_focus in self._visible_entry_indices
        ):
            entry = self._entry_at(previous_focus)
            if entry and entry.transcript:
                self._render_transcript(entry)
            return

        if self._visible_entry_indices:
            self.focus_index = self._visible_entry_indices[0]
            if not (preserve_search_focus and self._search_box.HasFocus()):
                self._selection_explicit_empty = False
                self._file_list.Select(0)
            entry = self._entry_at(self.focus_index)
            if entry:
                self._show_entry(entry)
            return

        self.focus_index = None
        self._title_label.SetLabel(t("status.no_session"))
        self._title_label.SetFont(self._ui_font_bold)
        self._meta_label.SetLabel(t("status.select_or_convert"))
        self._clear_chat_view()

    def _clear_session_view(self) -> None:
        self.focus_index = None
        self._title_label.SetLabel(t("status.no_session"))
        self._title_label.SetFont(self._ui_font_bold)
        self._meta_label.SetLabel(t("status.select_or_convert"))
        self._clear_chat_view()

    def _scroll_window_to_child(
        self,
        scrolled: wx.ScrolledWindow,
        child: wx.Window,
    ) -> None:
        y = 0
        current: wx.Window | None = child
        while current is not None and current is not scrolled:
            y += current.GetPosition().y
            current = current.GetParent()

        _, unit_y = scrolled.GetScrollPixelsPerUnit()
        if unit_y <= 0:
            unit_y = 10
        _, view_y = scrolled.GetViewStart()
        scroll_y = view_y * unit_y
        client_h = scrolled.GetClientSize().height
        child_h = child.GetSize().height
        target_y = max(0, y - max(0, (client_h - child_h) // 2))
        if abs(target_y - scroll_y) > 2:
            scrolled.Scroll(-1, int(target_y / unit_y))

    def _scroll_to_segment(self, segment_index: int) -> None:
        target = self._segment_scroll_targets.get(segment_index)
        if target is None:
            return
        panel = self._list_panel if self.view_mode == "list" else self._bubble_panel
        if not panel.IsShown():
            return
        self._scroll_window_to_child(panel, target)

    def _segment_display_colour(
        self,
        *,
        is_search_match: bool,
        is_me_speaker: bool,
        list_mode: bool,
    ) -> wx.Colour:
        if is_search_match:
            if list_mode:
                return _rgb_colour(*SEARCH_MATCH_RGB)
            return _rgb_colour(*SEARCH_BUBBLE_RGB)
        if is_me_speaker:
            return _rgb_colour(*BUBBLE_RIGHT_RGB)
        return _rgb_colour(*BUBBLE_LEFT_RGB)

    def _chat_panel_width(self, panel: wx.ScrolledWindow) -> int:
        width = panel.GetClientSize().width
        if width > 0:
            return width
        parent = panel.GetParent()
        if parent is not None:
            parent_width = parent.GetClientSize().width
            if parent_width > 0:
                return parent_width
        return 480

    def _bubble_message_max_width(self) -> int:
        panel_width = self._chat_panel_width(self._bubble_panel)
        return max(80, panel_width - BUBBLE_SIDE_CHROME)

    def _list_message_max_width(self) -> int:
        panel_width = self._chat_panel_width(self._list_panel)
        return max(160, panel_width - LIST_SIDE_CHROME)

    def _wrap_text_lines(self, dc: wx.ClientDC, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            line = ""
            for char in paragraph:
                trial = line + char
                if dc.GetTextExtent(trial)[0] > width and line:
                    lines.append(line)
                    line = char
                else:
                    line = trial
            if line:
                lines.append(line)
        return lines or [""]

    def _wrapped_text_size(
        self,
        parent: wx.Window,
        text: str,
        width: int,
    ) -> wx.Size:
        dc = wx.ClientDC(parent)
        dc.SetFont(self._ui_font)
        line_height = dc.GetCharHeight()
        line_count = len(self._wrap_text_lines(dc, text, width))
        height = max(line_height, line_count * line_height) + 4
        return wx.Size(width, height)

    def _measure_message_text(
        self,
        parent: wx.Window,
        text: str,
        max_width: int,
        *,
        fill_width: bool = False,
    ) -> wx.Size:
        dc = wx.ClientDC(parent)
        dc.SetFont(self._ui_font)
        if fill_width:
            return self._wrapped_text_size(parent, text, max_width)

        line_widths = [dc.GetTextExtent(line)[0] for line in text.split("\n")] or [0]
        widest_line = max(line_widths)
        single_line = "\n" not in text and (widest_line + BUBBLE_TEXT_WIDTH_PAD) <= max_width
        if single_line:
            width = max(40, widest_line + BUBBLE_TEXT_WIDTH_PAD)
            _, height = dc.GetTextExtent(text)
            height = max(height, dc.GetCharHeight())
            return wx.Size(width, height)

        return self._wrapped_text_size(parent, text, max_width)

    def _create_message_ctrl(
        self,
        parent: wx.Window,
        text: str,
        max_width: int,
        bg: wx.Colour,
        *,
        fill_width: bool = False,
    ) -> tuple[wx.TextCtrl, wx.Size]:
        content_size = self._measure_message_text(
            parent,
            text,
            max_width,
            fill_width=fill_width,
        )
        style = (
            wx.TE_MULTILINE
            | wx.TE_READONLY
            | wx.TE_WORDWRAP
            | wx.BORDER_NONE
            | wx.TE_NO_VSCROLL
        )
        message = wx.TextCtrl(parent, value=text, style=style)
        message.SetBackgroundColour(bg)
        message.SetForegroundColour(_rgb_colour(*MESSAGE_TEXT_RGB))
        message.SetFont(self._ui_font)
        message.SetInitialSize(content_size)
        message.SetMinSize(content_size)
        message.SetMaxSize(content_size)
        return message, content_size

    def _create_bubble_message(
        self,
        parent: wx.Window,
        text: str,
        max_width: int,
        bg: wx.Colour,
    ) -> tuple[wx.TextCtrl, wx.Size]:
        return self._create_message_ctrl(parent, text, max_width, bg, fill_width=False)

    def _create_list_message(
        self,
        parent: wx.Window,
        text: str,
        max_width: int,
        bg: wx.Colour,
    ) -> tuple[wx.TextCtrl, wx.Size]:
        return self._create_message_ctrl(parent, text, max_width, bg, fill_width=True)

    def _bubble_first_line_top_pad(self, parent: wx.Window) -> int:
        dc = wx.ClientDC(parent)
        dc.SetFont(self._ui_font)
        line_height = dc.GetCharHeight()
        return max(0, int(AVATAR_SIZE / 2 - BUBBLE_INNER_PAD - line_height / 2))

    def _make_avatar_indent(self, parent: wx.Window, chat_bg: wx.Colour) -> wx.Panel:
        indent = wx.Panel(parent, style=wx.BORDER_NONE)
        indent.SetBackgroundColour(chat_bg)
        indent.SetMinSize((AVATAR_COL_WIDTH, AVATAR_SIZE))
        return indent

    def _make_avatar_widget(
        self,
        parent: wx.Window,
        speaker_index: int,
        chat_bg: wx.Colour,
        *,
        bubble_menu: bool = False,
    ) -> wx.Panel:
        holder = wx.Panel(parent, style=wx.BORDER_NONE)
        holder.SetBackgroundColour(chat_bg)
        holder.SetMinSize((AVATAR_COL_WIDTH, AVATAR_SIZE))
        holder_sizer = wx.BoxSizer(wx.VERTICAL)

        def get_speaker() -> Speaker:
            entry = self._entry_at(self.focus_index)
            if entry is None or entry.transcript is None:
                return Speaker(name=f"spk{speaker_index}")
            return entry.transcript.speaker_at(speaker_index)

        def is_me() -> bool:
            entry = self._entry_at(self.focus_index)
            if entry is None or entry.transcript is None:
                return False
            return entry.transcript.is_me_speaker(speaker_index)

        avatar = RoundedAvatarPanel(
            holder,
            speaker_index=speaker_index,
            get_speaker=get_speaker,
            on_open_profile=self._open_speaker_profile,
            chat_bg=chat_bg,
            colour_palette=SPEAKER_AVATAR_RGBS,
            size=AVATAR_SIZE,
            on_set_primary=self._set_primary_speaker if bubble_menu else None,
            is_primary_speaker=is_me if bubble_menu else None,
        )
        self._avatar_panels[speaker_index] = avatar
        holder_sizer.Add(avatar, 0, wx.ALIGN_CENTER_HORIZONTAL)
        holder.SetSizer(holder_sizer)
        return holder

    def _set_primary_speaker(self, speaker_index: int) -> None:
        entry = self._entry_at(self.focus_index)
        if entry is None or entry.transcript is None:
            return
        if speaker_index < 0 or speaker_index >= len(entry.transcript.speakers):
            return
        entry.transcript.primary_speaker = speaker_index
        self._save_entry_transcript(entry)
        self._render_transcript(entry, relayout=False)

    def _open_speaker_profile(self, speaker_index: int) -> None:
        entry = self._entry_at(self.focus_index)
        if entry is None or entry.transcript is None:
            return
        if speaker_index < 0 or speaker_index >= len(entry.transcript.speakers):
            return
        dialog = SpeakerProfileDialog(
            self,
            entry.transcript.speakers[speaker_index],
            speaker_index=speaker_index,
        )
        dialog.ShowModal()
        entry.transcript.speakers[speaker_index] = dialog.get_speaker()
        dialog.Destroy()
        self._save_entry_transcript(entry)
        self._render_transcript(entry, relayout=True)

    def _save_entry_transcript(self, entry: FileEntry) -> None:
        if entry.transcript is None:
            return
        json_path = _entry_json_path(entry)
        write_transcript_outputs(entry.transcript, json_path=json_path, quiet=True)

    def _list_message_width(self) -> int:
        return self._list_message_max_width()

    def _fit_chat_panels(self) -> None:
        if self.view_mode == "list" and self._list_panel.IsShown():
            self._list_panel.Layout()
            self._list_panel.FitInside()
            return
        if self.view_mode != "bubbles" or not self._bubble_panel.IsShown():
            return
        self._bubble_sizer.Layout()
        min_size = self._bubble_sizer.GetMinSize()
        client_width = max(min_size.width, self._bubble_panel.GetClientSize().width)
        virtual_height = min_size.height + 24
        current = self._bubble_panel.GetVirtualSize()
        if current.width != client_width or current.height != virtual_height:
            self._bubble_panel.SetVirtualSize((client_width, virtual_height))
        self._bubble_panel.Layout()
        self._bubble_panel.FitInside()

    def _schedule_transcript_relayout(self) -> None:
        if not self._relayout_timer.IsRunning():
            self._relayout_timer.Start(200, oneShot=True)

    def _on_relayout_timer(self, _event: wx.TimerEvent) -> None:
        entry = self._entry_at(self.focus_index)
        if entry and entry.transcript:
            self._render_transcript(entry, relayout=True)

    def _on_list_panel_size(self, event: wx.SizeEvent) -> None:
        if self.view_mode != "list":
            event.Skip()
            return
        width = event.GetSize().width
        if width <= 0:
            event.Skip()
            return
        if abs(width - self._last_list_layout_width) >= 16:
            self._last_list_layout_width = width
            self._schedule_transcript_relayout()
        else:
            wx.CallAfter(self._fit_chat_panels)
        event.Skip()

    def _on_bubble_panel_size(self, event: wx.SizeEvent) -> None:
        if self.view_mode != "bubbles":
            event.Skip()
            return
        width = event.GetSize().width
        if width <= 0:
            event.Skip()
            return
        if abs(width - self._last_bubble_layout_width) >= 16:
            self._last_bubble_layout_width = width
            self._schedule_transcript_relayout()
        else:
            wx.CallAfter(self._fit_chat_panels)
        event.Skip()

    def _clear_chat_view(self) -> None:
        self._segment_player.stop()
        self._playing_segment_index = None
        self._segment_rows.clear()
        self._speaker_icons.clear()
        self._avatar_panels.clear()
        self._stop_speaker_animation()
        self._list_sizer.Clear(True)
        self._bubble_sizer.Clear(True)

    def _make_speaker_icon(self, parent: wx.Window) -> wx.StaticText:
        icon = wx.StaticText(parent, label=SPEAKER_EMOJI_FRAMES[0])
        icon.SetFont(self._emoji_font)
        icon.Hide()
        return icon

    def _start_speaker_animation(self) -> None:
        if not self._speaker_timer.IsRunning():
            self._speaker_timer.Start(200)

    def _stop_speaker_animation(self) -> None:
        self._speaker_timer.Stop()
        self._speaker_emoji_frame = 0

    def _hide_playing_speaker(self) -> None:
        for icon in self._speaker_icons.values():
            icon.Hide()
        self._stop_speaker_animation()

    def _show_playing_speaker(self, segment_index: int) -> None:
        self._hide_playing_speaker()
        icon = self._speaker_icons.get(segment_index)
        if icon is None:
            return
        icon.SetLabel(SPEAKER_EMOJI_FRAMES[0])
        icon.Show()
        parent = icon.GetParent()
        if parent is not None:
            parent.Layout()
        self._bubble_panel.Layout()
        self._list_panel.Layout()
        self._start_speaker_animation()

    def _on_speaker_timer(self, _event: wx.TimerEvent) -> None:
        if self._playing_segment_index is None:
            self._stop_speaker_animation()
            return
        icon = self._speaker_icons.get(self._playing_segment_index)
        if icon is None:
            self._stop_speaker_animation()
            return
        self._speaker_emoji_frame = (self._speaker_emoji_frame + 1) % len(SPEAKER_EMOJI_FRAMES)
        icon.SetLabel(SPEAKER_EMOJI_FRAMES[self._speaker_emoji_frame])
        icon.Refresh()

    def _segment_line_text(self, entry: FileEntry, segment: Segment) -> str:
        start = format_timestamp(segment.start)
        end = format_timestamp(segment.end)
        name = display_name(entry.transcript, segment) if entry.transcript else f"spk{segment.speaker}"
        return f"[{start} - {end}] {name}: {segment.text}"

    def _bind_segment_play(
        self,
        window: wx.Window,
        segment_index: int,
        *,
        playable: bool,
    ) -> None:
        if not playable:
            return

        def on_click(event: wx.MouseEvent) -> None:
            self._on_segment_clicked(segment_index)

        window.Bind(wx.EVT_LEFT_DOWN, on_click)
        window.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        for child in window.GetChildren():
            self._bind_segment_play(child, segment_index, playable=playable)

    def _register_segment_row(
        self,
        panel: wx.Panel,
        base_colour: wx.Colour,
        segment_index: int,
    ) -> None:
        self._segment_rows.append((panel, base_colour, segment_index))

    def _update_segment_highlights(self) -> None:
        for panel, base_colour, segment_index in self._segment_rows:
            colour = (
                _rgb_colour(*PLAYING_SEGMENT_RGB)
                if segment_index == self._playing_segment_index
                else base_colour
            )
            if isinstance(panel, _RoundedBubblePanel):
                panel.set_colour(colour)
            else:
                panel.SetBackgroundColour(colour)
            for child in panel.GetChildren():
                if isinstance(child, (wx.StaticText, wx.TextCtrl)):
                    child.SetBackgroundColour(colour)
            panel.Refresh()

    def _on_playback_finished(self) -> None:
        self._playing_segment_index = None
        self._hide_playing_speaker()
        self._set_status("status.ready")

    def _on_segment_clicked(self, segment_index: int) -> None:
        entry = self._entry_at(self.focus_index)
        if entry is None or entry.transcript is None or not _entry_has_playable_audio(entry):
            return
        segments = entry.transcript.segments
        if segment_index < 0 or segment_index >= len(segments):
            return

        segment = segments[segment_index]
        start, end = segment_play_range(segment, entry.transcript.duration)
        self._playing_segment_index = segment_index
        self._show_playing_speaker(segment_index)
        self._set_status(
            "status.playing_segment",
            start=format_timestamp(start),
            end=format_timestamp(end),
        )

        def on_done() -> None:
            wx.CallAfter(self._on_playback_finished)

        try:
            self._segment_player.play(entry.path, start, end, on_done=on_done)
        except (Wav2ChatError, OSError, FileNotFoundError) as exc:
            self._playing_segment_index = None
            self._hide_playing_speaker()
            self._set_status("status.playback_failed", error=exc)
            wx.MessageBox(
                t("status.playback_failed", error=exc),
                t("dialog.error_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._render_chunk_timer.Stop()
        self._segment_player.stop()
        self._stop_speaker_animation()
        self._save_layout_settings()
        event.Skip()

    def _entry_at(self, index: int | None) -> FileEntry | None:
        if index is None or index < 0 or index >= len(self.entries):
            return None
        return self.entries[index]

    def _selected_indices(self) -> list[int]:
        return self._selected_entry_indices()

    def _selected_entry_indices(self) -> list[int]:
        indices: list[int] = []
        for list_row in self._list_selected_rows():
            entry_index = self._entry_index_at_list_row(list_row)
            if entry_index is not None:
                indices.append(entry_index)
        return indices

    def _show_entry(self, entry: FileEntry) -> None:
        if entry.transcript:
            self._render_transcript(entry)
        else:
            self._title_label.SetLabel(_entry_title(entry.path))
            self._title_label.SetFont(self._ui_font_bold)
            self._meta_label.SetLabel(_entry_meta(entry.path, None))
            self._clear_chat_view()

    def _select_all_visible_files(self) -> None:
        count = self._file_list.GetItemCount()
        if count == 0:
            return
        self._selection_explicit_empty = False
        for list_row in range(count):
            self._file_list.SetItemState(
                list_row,
                wx.LIST_STATE_SELECTED,
                wx.LIST_STATE_SELECTED,
            )

    def _file_name_truncated(self, list_row: int) -> bool:
        label = self._file_list.GetItemText(list_row, NAME_COL)
        if not label:
            return False
        col_width = self._file_list.GetColumnWidth(NAME_COL)
        if col_width <= 8:
            return False
        text_width, _ = self._file_list.GetTextExtent(label)
        return text_width >= col_width - 8

    def _set_file_list_name_tooltip(self, text: str) -> None:
        if text:
            self._file_list.SetToolTip(text)
        else:
            self._file_list.UnsetToolTip()

    def _on_file_list_motion(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        list_row, flags = self._file_list.HitTest(pos)
        tooltip = ""
        if list_row != wx.NOT_FOUND and (flags & wx.LIST_HITTEST_ONITEMLABEL):
            if self._file_name_truncated(list_row):
                tooltip = self._file_list.GetItemText(list_row, NAME_COL)
        self._set_file_list_name_tooltip(tooltip)
        event.Skip()

    def _on_file_list_leave(self, _event: wx.MouseEvent) -> None:
        self._set_file_list_name_tooltip("")

    def _on_file_list_left_down(self, event: wx.MouseEvent) -> None:
        list_row, _flags = self._file_list.HitTest(event.GetPosition())
        if list_row != wx.NOT_FOUND:
            selected_rows = self._list_selected_rows()
            if len(selected_rows) == 1 and selected_rows[0] == list_row:
                self._suppress_file_select = True
                self._selection_explicit_empty = True
                self._deselect_all_file_rows()
                return
        event.Skip()

    def _on_file_list_key_down(self, event: wx.KeyEvent) -> None:
        if event.ControlDown() and event.GetKeyCode() in (ord("A"), ord("a")):
            self._select_all_visible_files()
            return
        if event.GetKeyCode() in (wx.WXK_DELETE, wx.WXK_NUMPAD_DELETE):
            self._delete_selected_entries()
            return
        event.Skip()

    def _delete_selected_entries(self) -> None:
        if self._converting_active or self._import_active:
            return
        if self._selection_explicit_empty:
            return

        selected = sorted(set(self._selected_entry_indices()))
        if not selected:
            return

        self._segment_player.stop()
        self._playing_segment_index = None
        self._stop_speaker_animation()

        old_focus = self.focus_index
        remove_count = len(selected)
        for index in reversed(selected):
            if 0 <= index < len(self.entries):
                del self.entries[index]

        if not self.entries:
            self.focus_index = None
            self._selection_explicit_empty = True
            self._clear_session_view()
        else:
            if old_focus is not None and old_focus in selected:
                new_focus = min(min(selected), len(self.entries) - 1)
            elif old_focus is not None:
                removed_before = sum(1 for index in selected if index < old_focus)
                new_focus = old_focus - removed_before
                new_focus = max(0, min(new_focus, len(self.entries) - 1))
            else:
                new_focus = 0
            self.focus_index = new_focus
            self._selection_explicit_empty = False

        restore = {self.focus_index} if self.focus_index is not None else set()
        self._sync_file_list(restore_selection=restore)
        if self.focus_index is not None:
            self._show_entry(self.entries[self.focus_index])

        self._append_log(logging.INFO, t("log.removed_files", count=remove_count))
        self._set_status("status.removed_files", count=remove_count)

    def _on_file_selected(self, event: wx.ListEvent) -> None:
        if self._suppress_file_select:
            self._suppress_file_select = False
            return
        self._selection_explicit_empty = False
        entry_index = self._entry_index_at_list_row(event.GetIndex())
        entry = self._entry_at(entry_index)
        if entry is None:
            return
        self.focus_index = entry_index
        wx.CallAfter(self._show_entry, entry)

    def _on_file_deselected(self, _event: wx.ListEvent) -> None:
        if self._file_list.GetSelectedItemCount() == 0:
            self._selection_explicit_empty = True

    def _set_file_row_status_image(self, list_row: int, entry: FileEntry) -> None:
        if list_row < 0 or list_row >= self._file_list.GetItemCount():
            return
        image = _status_image_index(entry)
        if image < 0 or image >= self._status_images.GetImageCount():
            return
        self._file_list.SetItemColumnImage(list_row, STATUS_COL, image)

    def _render_transcript(self, entry: FileEntry, relayout: bool = False) -> None:
        transcript = entry.transcript
        if transcript is None:
            return

        self._render_chunk_timer.Stop()
        self._thaw_transcript_panels()
        self._render_generation += 1
        render_generation = self._render_generation

        self._title_label.SetLabel(_entry_title(entry.path))
        self._title_label.SetFont(self._ui_font_bold)
        self._meta_label.SetLabel(_entry_meta(entry.path, transcript.duration))

        playing_index = self._playing_segment_index if relayout else None
        if not relayout:
            self._segment_player.stop()
            self._playing_segment_index = None
            self._stop_speaker_animation()
        else:
            self._stop_speaker_animation()

        self._segment_rows.clear()
        self._speaker_icons.clear()
        self._avatar_panels.clear()
        self._segment_scroll_targets.clear()
        self._list_sizer.Clear(True)
        self._bubble_sizer.Clear(True)

        if not transcript.segments:
            self._render_in_progress = False
            self._render_state = None
            self._fit_chat_panels()
            return

        self._render_in_progress = True
        state: dict = {
            "entry": entry,
            "render_generation": render_generation,
            "playing_index": playing_index,
            "keywords": self._search_keywords,
            "next_index": 0,
            "prev_speaker": None,
            "first_match_index": None,
        }

        if self.view_mode == "list":
            if self._list_panel.IsShown():
                self._list_panel.GetParent().Layout()
            state["list_max_width"] = self._list_message_max_width()
            self._last_list_layout_width = self._chat_panel_width(self._list_panel)
            self._list_panel.Freeze()
        else:
            if self._bubble_panel.IsShown():
                self._bubble_panel.GetParent().Layout()
            state["bubble_max_width"] = self._bubble_message_max_width()
            self._last_bubble_layout_width = self._chat_panel_width(self._bubble_panel)
            state["chat_bg"] = _rgb_colour(*CHAT_BG_RGB)
            state["first_line_top_pad"] = self._bubble_first_line_top_pad(self._bubble_panel)
            self._bubble_panel.Freeze()

        self._render_state = state
        self._render_chunk_timer.Start(1, oneShot=True)

    def _thaw_transcript_panels(self) -> None:
        if self._list_panel.IsFrozen():
            self._list_panel.Thaw()
        if self._bubble_panel.IsFrozen():
            self._bubble_panel.Thaw()

    def _on_render_chunk_timer(self, _event: wx.TimerEvent) -> None:
        state = self._render_state
        if state is None:
            return
        if state["render_generation"] != self._render_generation:
            self._cancel_transcript_render()
            return

        entry: FileEntry = state["entry"]
        transcript = entry.transcript
        if transcript is None:
            self._finish_transcript_render(state)
            return

        start = int(state["next_index"])
        end = min(start + RENDER_CHUNK_SIZE, len(transcript.segments))
        for segment_index in range(start, end):
            segment = transcript.segments[segment_index]
            if self.view_mode == "list":
                self._append_list_segment_row(
                    entry,
                    segment_index,
                    segment,
                    list_max_width=int(state["list_max_width"]),
                    keywords=state["keywords"],
                    state=state,
                )
            else:
                self._append_bubble_segment_row(
                    entry,
                    segment_index,
                    segment,
                    bubble_max_width=int(state["bubble_max_width"]),
                    chat_bg=state["chat_bg"],
                    first_line_top_pad=int(state["first_line_top_pad"]),
                    keywords=state["keywords"],
                    state=state,
                )

        state["next_index"] = end
        if end >= len(transcript.segments):
            self._finish_transcript_render(state)
        else:
            self._render_chunk_timer.Start(10, oneShot=True)

    def _cancel_transcript_render(self) -> None:
        self._render_state = None
        self._render_in_progress = False
        self._thaw_transcript_panels()

    def _finish_transcript_render(self, state: dict) -> None:
        if self.view_mode == "bubbles":
            self._bubble_sizer.AddSpacer(20)
            self._bubble_sizer.Layout()
            if self._bubble_panel.IsFrozen():
                self._bubble_panel.Thaw()
        else:
            self._list_panel.Layout()
            if self._list_panel.IsFrozen():
                self._list_panel.Thaw()

        render_generation = int(state["render_generation"])
        playing_index = state["playing_index"]
        keywords = state["keywords"]
        first_match_index = state["first_match_index"]
        self._render_state = None
        self._fit_chat_panels()

        def finish_layout() -> None:
            self._render_in_progress = False
            if render_generation != self._render_generation:
                return
            if playing_index is not None:
                self._playing_segment_index = int(playing_index)
                self._show_playing_speaker(int(playing_index))
            elif keywords and first_match_index is not None:
                self._scroll_to_segment(int(first_match_index))
            self._update_segment_highlights()

        wx.CallAfter(finish_layout)

    def _append_list_segment_row(
        self,
        entry: FileEntry,
        segment_index: int,
        segment: Segment,
        *,
        list_max_width: int,
        keywords: list[str],
        state: dict,
    ) -> None:
        is_me = entry.transcript.is_me_speaker(segment.speaker)  # type: ignore[union-attr]
        is_search_match = _segment_matches_keywords(segment, keywords)
        if is_search_match and state["first_match_index"] is None:
            state["first_match_index"] = segment_index
        row_colour = self._segment_display_colour(
            is_search_match=is_search_match,
            is_me_speaker=is_me,
            list_mode=True,
        )
        row = wx.Panel(self._list_panel)
        row.SetBackgroundColour(row_colour)
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        message_ctrl, _content_size = self._create_list_message(
            row,
            self._segment_line_text(entry, segment),
            list_max_width,
            row_colour,
        )
        row_sizer.Add(message_ctrl, 0, wx.ALL, 8)
        playable = _entry_has_playable_audio(entry)
        if playable:
            speaker_icon = self._make_speaker_icon(row)
            speaker_icon.SetBackgroundColour(row_colour)
            row_sizer.Add(speaker_icon, 0, wx.ALIGN_TOP | wx.RIGHT, 6)
            self._speaker_icons[segment_index] = speaker_icon
        row.SetSizer(row_sizer)
        self._list_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
        self._register_segment_row(row, row_colour, segment_index)
        self._segment_scroll_targets[segment_index] = row
        self._bind_segment_play(row, segment_index, playable=playable)

    def _append_bubble_segment_row(
        self,
        entry: FileEntry,
        segment_index: int,
        segment: Segment,
        *,
        bubble_max_width: int,
        chat_bg: wx.Colour,
        first_line_top_pad: int,
        keywords: list[str],
        state: dict,
    ) -> None:
        transcript = entry.transcript
        assert transcript is not None
        is_me = transcript.is_me_speaker(segment.speaker)
        is_search_match = _segment_matches_keywords(segment, keywords)
        if is_search_match and state["first_match_index"] is None:
            state["first_match_index"] = segment_index
        prev_speaker: int | None = state["prev_speaker"]
        show_avatar = segment.speaker != prev_speaker
        state["prev_speaker"] = segment.speaker

        row_panel = wx.Panel(self._bubble_panel)
        row_panel.SetBackgroundColour(chat_bg)
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        row_gap = 6 if show_avatar else 3

        avatar_widget: wx.Panel | None = None
        if show_avatar:
            avatar_widget = self._make_avatar_widget(
                row_panel,
                segment.speaker,
                chat_bg,
                bubble_menu=True,
            )

        bubble_colour = self._segment_display_colour(
            is_search_match=is_search_match,
            is_me_speaker=is_me,
            list_mode=False,
        )
        bubble = _RoundedBubblePanel(row_panel, bubble_colour, BUBBLE_RADIUS)
        bubble_sizer = wx.BoxSizer(wx.VERTICAL)
        message_ctrl, _content_size = self._create_bubble_message(
            bubble,
            segment.text,
            bubble_max_width,
            bubble_colour,
        )
        bubble_sizer.Add(message_ctrl, 0, wx.ALL, BUBBLE_INNER_PAD)
        bubble.SetSizer(bubble_sizer)

        playable = _entry_has_playable_audio(entry)
        speaker_icon: wx.StaticText | None = None
        if playable:
            speaker_icon = self._make_speaker_icon(row_panel)
            self._speaker_icons[segment_index] = speaker_icon
            speaker_icon.SetBackgroundColour(chat_bg)

        bubble_top_flag = wx.ALIGN_TOP | wx.TOP
        bubble_top_border = first_line_top_pad if show_avatar else 0
        avatar_sizer_flags = wx.ALIGN_TOP | wx.LEFT | wx.RIGHT
        avatar_sizer_border = BUBBLE_AVATAR_H_MARGIN

        if is_me:
            row_sizer.AddStretchSpacer(1)
            if speaker_icon is not None:
                row_sizer.Add(speaker_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
            row_sizer.Add(
                bubble,
                0,
                bubble_top_flag,
                bubble_top_border if show_avatar else row_gap,
            )
            if show_avatar and avatar_widget is not None:
                row_sizer.Add(
                    avatar_widget,
                    0,
                    avatar_sizer_flags,
                    avatar_sizer_border,
                )
            else:
                row_sizer.Add(
                    self._make_avatar_indent(row_panel, chat_bg),
                    0,
                    avatar_sizer_flags,
                    avatar_sizer_border,
                )
        else:
            if show_avatar and avatar_widget is not None:
                row_sizer.Add(
                    avatar_widget,
                    0,
                    avatar_sizer_flags,
                    avatar_sizer_border,
                )
            else:
                row_sizer.Add(
                    self._make_avatar_indent(row_panel, chat_bg),
                    0,
                    avatar_sizer_flags,
                    avatar_sizer_border,
                )
            row_sizer.Add(
                bubble,
                0,
                bubble_top_flag,
                bubble_top_border if show_avatar else row_gap,
            )
            if speaker_icon is not None:
                row_sizer.Add(speaker_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
            row_sizer.AddStretchSpacer(1)

        row_panel.SetSizer(row_sizer)
        self._bubble_sizer.Add(row_panel, 0, wx.EXPAND | wx.TOP, row_gap)
        self._register_segment_row(bubble, bubble_colour, segment_index)
        self._segment_scroll_targets[segment_index] = row_panel
        self._bind_segment_play(row_panel, segment_index, playable=playable)

    def _resize_file_list_columns(self) -> None:
        client_size = self._file_list.GetClientSize()
        if client_size.width <= STATUS_COL_WIDTH:
            return
        name_width = client_size.width - STATUS_COL_WIDTH
        self._file_list.SetColumnWidth(NAME_COL, name_width)
        self._file_list.SetColumnWidth(STATUS_COL, STATUS_COL_WIDTH)

    def _on_file_list_size(self, event: wx.SizeEvent) -> None:
        self._resize_file_list_columns()
        event.Skip()

    def _sync_file_list(
        self,
        *,
        restore_selection: set[int] | None = None,
        preserve_search_focus: bool = False,
        force: bool = False,
    ) -> None:
        if not force and not self._file_list.IsShown():
            self._file_list_needs_sync = True
            return
        self._file_list_needs_sync = False
        if restore_selection is None:
            restore_selection = set(self._selected_entry_indices())
        self._rebuild_visible_entries()

        self._file_list.Freeze()
        self._file_list.DeleteAllItems()
        for list_row, entry_index in enumerate(self._visible_entry_indices):
            entry = self.entries[entry_index]
            label = _entry_label(entry.path)
            self._file_list.InsertItem(list_row, label)

        self._set_file_list_selection(
            restore_selection,
            focus_entry=self.focus_index,
            preserve_search_focus=preserve_search_focus,
        )

        self._file_list.Thaw()
        for list_row, entry_index in enumerate(self._visible_entry_indices):
            self._set_file_row_status_image(list_row, self.entries[entry_index])
        self._resize_file_list_columns()

    def _update_row_status(self, entry_index: int) -> None:
        if entry_index < 0 or entry_index >= len(self.entries):
            return
        if not self._file_list.IsShown():
            self._file_list_needs_sync = True
            return
        if self._search_keywords:
            selected_entries = set(self._selected_entry_indices())
            self._sync_file_list(
                restore_selection=selected_entries,
                preserve_search_focus=self._search_box.HasFocus(),
            )
            return
        list_row = self._list_row_for_entry(entry_index)
        if list_row is None:
            return
        entry = self.entries[entry_index]
        self._set_file_row_status_image(list_row, entry)

    def _collect_import_paths(self, paths: list[Path]) -> list[Path]:
        return collect_supported_audio_paths(paths)

    def _refresh_entry_metadata(self, entry: FileEntry) -> bool:
        changed = False
        if entry.session_only:
            transcript = _try_load_transcript_json(entry.path)
            if transcript is None:
                if not entry.json_invalid or entry.transcript is not None:
                    entry.json_invalid = True
                    entry.transcript = None
                    entry.status = "error"
                    changed = True
            elif entry.transcript != transcript or entry.json_invalid:
                entry.transcript = transcript
                entry.status = "converted"
                entry.json_invalid = False
                entry.error = None
                changed = True
            return changed

        if not entry.has_audio:
            return False

        transcript_path = find_transcript_path(entry.path)
        if transcript_path is not None:
            transcript = _try_load_transcript_json(transcript_path)
            if transcript is not None:
                if entry.transcript != transcript or entry.status != "converted" or entry.json_invalid:
                    entry.transcript = transcript
                    entry.status = "converted"
                    entry.json_invalid = False
                    entry.error = None
                    changed = True
            elif not entry.json_invalid or entry.transcript is not None:
                entry.transcript = None
                entry.status = "unconverted"
                entry.json_invalid = True
                changed = True
        elif entry.json_invalid:
            entry.json_invalid = False
            changed = True
        return changed

    def _try_load_json_for_entry(self, entry: FileEntry) -> bool:
        if entry.status == "converted" and entry.transcript is not None and not entry.json_invalid:
            return False
        return self._refresh_entry_metadata(entry)

    def _append_audio_entry(self, path: Path) -> int:
        entry = FileEntry(path=path, has_audio=True)
        transcript_path = find_transcript_path(path)
        if transcript_path is not None:
            transcript = _try_load_transcript_json(transcript_path)
            if transcript is not None:
                entry.transcript = transcript
                entry.status = "converted"
            else:
                entry.json_invalid = True
        self.entries.append(entry)
        return len(self.entries) - 1

    def _append_json_entry(self, path: Path) -> int:
        transcript = _try_load_transcript_json(path)
        if transcript is None:
            self.entries.append(
                FileEntry(
                    path=path,
                    has_audio=False,
                    json_invalid=True,
                    status="error",
                )
            )
            return len(self.entries) - 1

        audio = _find_audio_for_stem(path.with_suffix(""))
        if audio is not None:
            entry = FileEntry(
                path=audio,
                has_audio=True,
                transcript=transcript,
                status="converted",
            )
        else:
            entry = FileEntry(
                path=path,
                has_audio=False,
                session_only=True,
                transcript=transcript,
                status="converted",
            )
        self.entries.append(entry)
        return len(self.entries) - 1

    def _append_entry(self, path: Path) -> int | None:
        """Add or refresh an entry. Returns its index, or None if unchanged."""
        for index, entry in enumerate(self.entries):
            if entry.path == path:
                if self._refresh_entry_metadata(entry):
                    return index
                return None

        if is_transcript_path(path):
            return self._append_json_entry(path)
        if is_supported_audio(path):
            return self._append_audio_entry(path)
        return None

    def _after_paths_added(self, added_indices: list[int]) -> None:
        if not added_indices:
            return

        self._sync_file_list()
        if self.focus_index is None:
            self.focus_index = added_indices[0]
        elif self.focus_index not in added_indices:
            self.focus_index = added_indices[0]

        if self._chk_auto_convert.GetValue():
            self._selection_explicit_empty = True
            self._deselect_all_file_rows()
            if self.focus_index is not None:
                self._show_entry(self.entries[self.focus_index])
            wx.CallAfter(self._convert_entry_indices, added_indices)
        elif self.focus_index is not None:
            self._selection_explicit_empty = False
            list_row = self._list_row_for_entry(self.focus_index)
            if list_row is not None:
                self._file_list.Select(list_row)
            self._show_entry(self.entries[self.focus_index])

    def _add_paths(self, paths: list[Path]) -> None:
        added_indices: list[int] = []
        for path in self._collect_import_paths(paths):
            index = self._append_entry(path)
            if index is not None:
                added_indices.append(index)
        self._after_paths_added(added_indices)

    def _open_import_dialog(self) -> None:
        self._close_import_dialog()
        self._import_dialog = _ImportDialog(self)
        self._import_dialog.Show()
        self._import_dialog.Raise()

    def _import_dropped_paths(self, paths: list[Path]) -> None:
        if self._import_active:
            logging.info(t("log.import_busy"))
            self._append_log(logging.INFO, t("log.import_busy"))
            return

        self._import_active = True
        self._open_import_dialog()
        logging.info(t("log.import_start"))
        self._append_log(logging.INFO, t("log.import_start"))
        self._set_status_text(t("dialog.import_scanning"))
        wx.CallAfter(self._start_import_drop_worker, list(paths))

    def _start_import_drop_worker(self, paths: list[Path]) -> None:
        if not self._import_active or self._import_dialog is None:
            return
        if self._import_thread and self._import_thread.is_alive():
            return
        self._import_thread = threading.Thread(
            target=self._import_drop_worker,
            args=(paths,),
            daemon=True,
        )
        self._import_thread.start()

    def _import_drop_worker(self, paths: list[Path]) -> None:
        try:
            self._ui_queue.put(("import_status", t("dialog.import_scanning")))
            collected = self._collect_import_paths(paths)
            total = len(collected)
            self._ui_queue.put(("import_status", t("log.import_found", count=total)))
            if total == 0:
                self._ui_queue.put(("import_done", []))
                return

            added_indices: list[int] = []
            for index, path in enumerate(collected, start=1):
                self._ui_queue.put(("import_file", (index, total, path.name)))
                entry_index = self._append_entry(path)
                if entry_index is not None:
                    added_indices.append(entry_index)
            self._ui_queue.put(("import_done", added_indices))
        except Exception as exc:
            self._ui_queue.put(
                ("log", (logging.ERROR, t("log.import_failed", error=exc))),
            )
            self._ui_queue.put(("import_done", []))

    def _close_import_dialog(self) -> None:
        if self._import_dialog is not None:
            self._import_dialog.Destroy()
            self._import_dialog = None

    def _finish_import(self, added_indices: list[int]) -> None:
        if not added_indices:
            logging.info(t("log.import_none"))
            self._append_log(logging.INFO, t("log.import_none"))
            self._close_import_dialog()
            self._import_active = False
            self._set_status("status.ready")
            return
        self._import_added_indices = list(added_indices)
        if self._import_dialog is not None:
            self._import_dialog.set_refreshing()
        logging.info(t("log.import_refreshing"))
        self._append_log(logging.INFO, t("log.import_refreshing"))
        wx.CallAfter(self._complete_import_ui)

    def _complete_import_ui(self) -> None:
        added_indices = self._import_added_indices
        self._import_added_indices = []
        self._sync_file_list()
        if added_indices:
            self.focus_index = added_indices[0]

        if self._chk_auto_convert.GetValue():
            self._selection_explicit_empty = True
            self._deselect_all_file_rows()
        elif self.focus_index is not None:
            self._selection_explicit_empty = False
            list_row = self._list_row_for_entry(self.focus_index)
            if list_row is not None:
                self._file_list.Select(list_row)

        self._close_import_dialog()
        self._import_active = False
        self._append_log(logging.INFO, t("log.import_done"))
        logging.info(t("log.import_done"))
        self._set_status("status.ready")

        if self.focus_index is not None:
            wx.CallAfter(self._show_entry, self.entries[self.focus_index])
        if self._chk_auto_convert.GetValue():
            wx.CallAfter(self._convert_entry_indices, added_indices)

    def open_directory(self) -> None:
        default = str(self._current_directory or Path.home())
        dialog = wx.DirDialog(
            self,
            message=t("dialog.open_directory"),
            defaultPath=default,
            style=wx.DD_DEFAULT_STYLE,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        selected = dialog.GetPath()
        dialog.Destroy()
        path = Path(selected)
        self._select_tree_directory(path)
        self._load_directory_files(path)

    def _persist_browser_directory(self, directory: Path) -> None:
        self.app_settings.last_browser_directory = directory
        save_app_settings(self.app_settings)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self, self.app_settings)
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        self.app_settings = dialog.result
        self.app_settings.recordings_location.mkdir(parents=True, exist_ok=True)
        save_app_settings(self.app_settings)
        dialog.Destroy()

    def import_from_phone(self) -> None:
        if self._import_active:
            wx.MessageBox(
                t("log.import_busy"),
                t("dialog.import_from_phone"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        if self._phone_import_dialog is not None:
            self._phone_import_dialog.Raise()
            return
        dialog = PhoneImportDialog(
            self,
            self.app_settings,
            on_complete=self._on_phone_import_complete,
            on_closed=self._on_phone_import_dialog_closed,
            on_status=self._set_status_text,
        )
        self._phone_import_dialog = dialog
        dialog.Show()

    def _on_phone_import_dialog_closed(self) -> None:
        self._phone_import_dialog = None
        self._set_status("status.ready")

    def _on_phone_import_complete(self, result: PhoneImportResult) -> None:
        save_app_settings(self.app_settings)
        target = result.first_destination_dir or result.last_destination_dir
        if target is None:
            return
        if self._converting_active:
            self._pending_browser_directory = target
            return
        self._select_tree_directory(target)
        self._load_directory_files(target)

    def open_chat_session(self) -> None:
        dialog = wx.FileDialog(
            self,
            message=t("dialog.open_chat_session"),
            wildcard=f"{t('filetype.json')}|{CHATLOG_WILDCARD}|{t('filetype.all')}|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        selected = dialog.GetPath()
        dialog.Destroy()
        path = Path(selected)
        try:
            transcript = Transcript.load_json(path)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            wx.MessageBox(
                t("dialog.load_json_failed", error=exc),
                t("dialog.load_json_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return

        audio = _find_audio_for_stem(path.with_suffix(""))
        if audio is not None:
            entry = FileEntry(
                path=audio,
                status="converted",
                transcript=transcript,
                has_audio=True,
            )
        else:
            entry = FileEntry(
                path=path,
                status="converted",
                transcript=transcript,
                has_audio=False,
                session_only=True,
            )
        self.entries.insert(0, entry)
        self.focus_index = 0
        self._selection_explicit_empty = False
        self._sync_file_list()
        list_row = self._list_row_for_entry(0)
        if list_row is not None:
            self._file_list.Select(list_row)
        self._show_entry(entry)
        self._set_status("status.loaded_session", name=path.name)

    def _get_backend(self) -> FunASRBackend:
        if self._backend is None:
            if self.settings.refresh_models:
                log_key = "log.refreshing_models"
            else:
                log_key = "log.loading_models_cache"
            self._ui_queue.put(("status_text", ("status.loading_models", {})))
            self._ui_queue.put(
                (
                    "log",
                    (logging.INFO, t(log_key)),
                )
            )
            backend = FunASRBackend(
                min_speakers=self.settings.min_speakers,
                max_speakers=self.settings.max_speakers,
                refresh_models=self.settings.refresh_models,
            )
            backend.load()
            self._backend = backend
            if self.settings.refresh_models:
                wx.CallAfter(self._file_menu.Check, self.ID_REFRESH_MODELS, False)
                self.settings.refresh_models = False
        return self._backend

    def _speaker_count_defaults(self) -> tuple[int, int]:
        min_s = self.settings.min_speakers if self.settings.min_speakers is not None else 2
        max_s = self.settings.max_speakers if self.settings.max_speakers is not None else 2
        if max_s < min_s:
            max_s = min_s
        return min_s, max_s

    def _apply_convert_settings_from_ui(self) -> None:
        min_spk = self._spin_min_speakers.GetValue()
        max_spk = self._spin_max_speakers.GetValue()
        if max_spk < min_spk:
            self._spin_max_speakers.SetValue(min_spk)
            max_spk = min_spk
        refresh = self._file_menu.IsChecked(self.ID_REFRESH_MODELS)
        settings_changed = (
            min_spk != self.settings.min_speakers
            or max_spk != self.settings.max_speakers
            or refresh != self.settings.refresh_models
        )
        self.settings.min_speakers = min_spk
        self.settings.max_speakers = max_spk
        self.settings.refresh_models = refresh
        if settings_changed or refresh:
            if self._backend is not None:
                self._backend.unload()
            self._backend = None

    def _on_min_speakers_changed(self) -> None:
        if self._spin_max_speakers.GetValue() < self._spin_min_speakers.GetValue():
            self._spin_max_speakers.SetValue(self._spin_min_speakers.GetValue())

    def _on_max_speakers_changed(self) -> None:
        if self._spin_max_speakers.GetValue() < self._spin_min_speakers.GetValue():
            self._spin_min_speakers.SetValue(self._spin_max_speakers.GetValue())

    def convert_pending(self) -> None:
        self._convert_entry_indices(self._convert_target_entry_indices())

    def _convert_entry_indices(self, indices: list[int]) -> None:
        if self._convert_thread and self._convert_thread.is_alive():
            return

        pending = [
            index
            for index in indices
            if 0 <= index < len(self.entries)
            and self.entries[index].has_audio
            and is_supported_audio(self.entries[index].path)
            and self.entries[index].status in {"unconverted", "error"}
            and not self.entries[index].json_invalid
        ]

        if not pending:
            skipped = [
                index
                for index in indices
                if 0 <= index < len(self.entries)
                and self.entries[index].status == "converted"
            ]
            if skipped:
                logging.info(t("log.import_skip_convert", count=len(skipped)))
                self._append_log(
                    logging.INFO,
                    t("log.import_skip_convert", count=len(skipped)),
                )
            else:
                self._set_status("status.nothing_to_convert")
            return

        self._apply_convert_settings_from_ui()

        self._converting_active = True
        self._last_progress_log_phase = None
        self._last_progress_log_percent = None
        self._set_progress(0)
        self._append_log(
            logging.INFO,
            t("log.start_batch", count=len(pending)),
        )

        self._sync_convert_controls(False)
        self._spin_min_speakers.Disable()
        self._spin_max_speakers.Disable()
        self._file_menu.Enable(self.ID_REFRESH_MODELS, False)
        self._stop_convert.clear()
        self._convert_thread = threading.Thread(
            target=self._convert_worker,
            args=(pending,),
            daemon=True,
        )
        self._convert_thread.start()

    def _convert_worker(self, indices: list[int]) -> None:
        try:
            try:
                backend = self._get_backend()
            except Wav2ChatError as exc:
                self._ui_queue.put(("error", str(exc)))
                return

            for file_index, index in enumerate(indices):
                if self._stop_convert.is_set():
                    entry = self.entries[index]
                    if entry.status == "converting":
                        entry.status = "unconverted"
                        self._ui_queue.put(("row", index))
                    break

                entry = self.entries[index]
                entry.status = "converting"
                entry.error = None
                self._ui_queue.put(("row", index))

                name = _entry_label(entry.path)
                report = self._make_conversion_progress(file_index, len(indices), name)
                report("normalizing", 0)

                try:
                    transcript = convert_file(
                        entry.path,
                        backend,
                        self.settings.roles,
                        keep_temp=self.settings.keep_temp,
                        verbose=self.settings.verbose,
                        disable_progress=True,
                        progress_callback=report,
                    )
                    report("saving", 95)
                    json_path = default_json_path(entry.path)
                    write_transcript_outputs(transcript, json_path=json_path, quiet=True)
                    report("saving", 100)
                    entry.transcript = transcript
                    entry.status = "converted"
                except FunASREmptyResultError:
                    report("saving", 95)
                    transcript = Transcript(
                        source=entry.path.name,
                        duration=None,
                        speakers=[],
                        segments=[],
                    )
                    json_path = default_json_path(entry.path)
                    write_transcript_outputs(transcript, json_path=json_path, quiet=True)
                    report("saving", 100)
                    entry.transcript = transcript
                    entry.status = "converted"
                except Wav2ChatError as exc:
                    entry.status = "error"
                    entry.error = str(exc)
                    self._ui_queue.put(("error", f"{entry.path.name}: {exc}"))
                except Exception as exc:
                    entry.status = "error"
                    entry.error = str(exc)
                    self._ui_queue.put(("error", f"{entry.path.name}: {exc}"))
                finally:
                    self._ui_queue.put(("row", index))
        finally:
            self._ui_queue.put(("status_text", ("status.ready", {})))
            self._ui_queue.put(("done", None))

    def _on_queue_timer(self, _event: wx.TimerEvent) -> None:
        batch_limit = 30
        processed = 0
        while processed < batch_limit:
            try:
                kind, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1
            if self._handle_ui_queue_event(kind, payload):
                break

    def _handle_ui_queue_event(self, kind: str, payload: object) -> bool:
        """Handle one UI queue event. Return True to stop batch processing."""
        if kind == "row":
            index = int(payload)
            self._update_row_status(index)
            if self.focus_index == index:
                entry = self._entry_at(index)
                if entry and entry.transcript:
                    self._render_transcript(entry)
        elif kind == "sync":
            if self._file_list.IsShown():
                self._sync_file_list()
            else:
                self._file_list_needs_sync = True
        elif kind == "progress":
            payload_dict = dict(payload)  # type: ignore[arg-type]
            self._report_conversion_progress(
                file_index=int(payload_dict["file_index"]),
                file_total=int(payload_dict["file_total"]),
                name=str(payload_dict["name"]),
                phase=str(payload_dict["phase"]),
                file_percent=(
                    None
                    if payload_dict.get("file_percent") is None
                    else int(payload_dict["file_percent"])
                ),
            )
        elif kind == "import_status":
            message = str(payload)
            if self._import_dialog is not None:
                self._import_dialog.set_message(message)
            self._set_status_text(message)
            logging.info(message)
        elif kind == "import_file":
            current, total, name = payload  # type: ignore[misc]
            if self._import_dialog is not None:
                self._import_dialog.set_progress(int(current), int(total), str(name))
        elif kind == "import_done":
            indices = list(payload) if isinstance(payload, list) else []
            self._finish_import([int(index) for index in indices])
            return True
        elif kind == "status_text":
            key, kwargs = payload  # type: ignore[misc]
            self._set_status(str(key), **dict(kwargs))
        elif kind == "log":
            levelno, message = payload  # type: ignore[misc]
            self._append_log(int(levelno), str(message))
        elif kind == "error":
            message = str(payload)
            self._append_log(logging.ERROR, message)
            self._set_status_text(message)
            if not self._converting_active:
                wx.MessageBox(
                    message,
                    t("dialog.error_title"),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
        elif kind == "done":
            self._converting_active = False
            self._set_progress(None)
            self._sync_convert_controls(True)
            self._spin_min_speakers.Enable()
            self._spin_max_speakers.Enable()
            self._file_menu.Enable(self.ID_REFRESH_MODELS, True)
            if self._file_list_needs_sync and self._file_list.IsShown():
                self._file_list_needs_sync = False
                self._sync_file_list(force=True)
            if self._pending_browser_directory is not None:
                target = self._pending_browser_directory
                self._pending_browser_directory = None
                self._load_directory_files(target)
                self._select_tree_directory(target)
        return False


def main(args: argparse.Namespace) -> int:
    try:
        app = wx.App(False)
    except Exception as exc:
        logging.error("Failed to start wx GUI: %s", exc)
        return 1

    settings = GuiSettings(
        backend=args.backend,
        lang=args.lang,
        ui_lang=args.ui_lang,
        min_speakers=args.min_speakers,
        max_speakers=args.max_speakers,
        roles=getattr(args, "_roles", {}),
        keep_temp=args.keep_temp,
        verbose=args.verbose,
        quiet=args.quiet,
        refresh_models=getattr(args, "refresh_models", False),
    )

    initial_paths: list[Path] = []
    if args.input is not None:
        initial_paths.append(args.input)

    frame = Wav2ChatFrame(settings, initial_paths=initial_paths or None)
    frame.Show()
    app.MainLoop()
    return 0
