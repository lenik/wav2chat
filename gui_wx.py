"""Desktop GUI for wav2chat (wxPython)."""

from __future__ import annotations

import argparse
import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

import wx

from wav2chat.audio_playback import SegmentPlayer, segment_play_range
from wav2chat.errors import FunASREmptyResultError, Wav2ChatError
from wav2chat.filename_meta import entry_timestamp, parse_audio_filename
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.i18n import SUPPORTED_LOCALES, set_locale, t
from wav2chat.models import Segment, Speaker, Transcript
from wav2chat.pipeline import (
    SUPPORTED_EXTENSIONS,
    convert_file,
    default_json_path,
    is_supported_audio,
    write_transcript_outputs,
)
from wav2chat.render import display_name, format_timestamp
from wav2chat.speaker_ui import RoundedAvatarPanel, SpeakerProfileDialog

AUDIO_WILDCARD = "*.wav;*.mp3;*.m4a;*.amr;*.aac;*.flac;*.ogg"
JSON_WILDCARD = "*.json"

IMG_UNCONVERTED = 0
IMG_CONVERTED = 1
IMG_EMPTY = 2
IMG_ERROR = 3
IMG_CONVERTING = 4
STATUS_DOT_RGB = {
    IMG_UNCONVERTED: (198, 40, 40),
    IMG_CONVERTED: (46, 125, 50),
    IMG_EMPTY: (173, 216, 230),
    IMG_ERROR: (198, 40, 40),
    IMG_CONVERTING: (21, 101, 192),
}
STATUS_ICON_SIZE = 14
PANEL_PADDING = 10
LOG_PANEL_DEFAULT_HEIGHT = 120
LOG_PANEL_MIN_HEIGHT = 48
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

# Fonts with broad Unicode / CJK coverage (first match on the system wins).
_UNICODE_FONT_FACES = (
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Noto Sans CJK TC",
    "Noto Sans CJK HK",
    "Noto Sans",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "Source Han Sans",
    "WenQuanYi Micro Hei",
    "Droid Sans Fallback",
    "Arial Unicode MS",
    "PingFang SC",
    "Hiragino Sans GB",
    "Malgun Gothic",
    "Segoe UI",
    "Noto Color Emoji",
    "Segoe UI Emoji",
    "DejaVu Sans",
)

_installed_font_faces: set[str] | None = None


def _collect_installed_font_faces() -> set[str]:
    global _installed_font_faces
    if _installed_font_faces is not None:
        return _installed_font_faces

    faces: set[str] = set()

    def _remember(face: str, *_args: object) -> None:
        faces.add(face)

    try:
        wx.FontEnumerator(_remember)
    except Exception:
        pass

    _installed_font_faces = faces
    return faces


def _pick_unicode_font(
    point_size: int | None = None,
    weight: int = wx.FONTWEIGHT_NORMAL,
) -> wx.Font:
    """Return a GUI font that covers Latin, CJK, and other UI locales."""
    default = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    if point_size is None:
        point_size = default.GetPointSize()

    installed = _collect_installed_font_faces()
    for face in _UNICODE_FONT_FACES:
        if installed and face not in installed:
            continue
        font = wx.Font(wx.FontInfo(point_size).FaceName(face).Weight(weight))
        if font.IsOk():
            return font

    fallback = wx.Font(default)
    fallback.SetWeight(weight)
    return fallback


def _apply_ui_font(window: wx.Window, font: wx.Font) -> None:
    window.SetFont(font)
    for child in window.GetChildren():
        _apply_ui_font(child, font)


@dataclass
class FileEntry:
    path: Path
    status: str = "unconverted"
    transcript: Transcript | None = None
    error: str | None = None


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
    return parse_audio_filename(path).title


def _entry_title(path: Path) -> str:
    return parse_audio_filename(path).title


def _entry_meta(path: Path, duration: float | None) -> str:
    timestamp = entry_timestamp(path).strftime("%Y-%m-%d %H:%M")
    return f"{timestamp}  {t('meta.duration', duration=_format_duration(duration))}"


def _transcript_is_empty(transcript: Transcript | None) -> bool:
    if transcript is None:
        return False
    return not any(segment.text.strip() for segment in transcript.segments)


def _create_dot_bitmap(colour: wx.Colour, size: int = STATUS_ICON_SIZE) -> wx.Bitmap:
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
    dc.SetPen(wx.Pen(colour))
    radius = max(2, size // 2 - 2)
    dc.DrawCircle(size // 2, size // 2, radius)
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def _build_status_image_list() -> wx.ImageList:
    images = wx.ImageList(STATUS_ICON_SIZE, STATUS_ICON_SIZE, True)
    mask = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    for index in range(IMG_CONVERTING + 1):
        red, green, blue = STATUS_DOT_RGB[index]
        bitmap = _create_dot_bitmap(wx.Colour(red, green, blue))
        images.Add(bitmap, mask)
    return images


def _status_image_index(entry: FileEntry) -> int:
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
    ID_OPEN_WAVEFORM = wx.NewIdRef()
    ID_OPEN_SESSION = wx.NewIdRef()
    ID_EXIT = wx.NewIdRef()
    ID_CONVERT = wx.NewIdRef()

    def __init__(
        self,
        settings: GuiSettings,
        initial_paths: list[Path] | None = None,
    ) -> None:
        set_locale(settings.ui_lang)

        super().__init__(None, title=t("app.window_title"), size=wx.Size(980, 640))
        self.settings = settings

        self.entries: list[FileEntry] = []
        self.focus_index: int | None = None
        self.view_mode = "bubbles"
        self._status_key = "status.ready"
        self._status_kwargs: dict[str, object] = {}
        self._backend: FunASRBackend | None = None
        self._convert_thread: threading.Thread | None = None
        self._import_thread: threading.Thread | None = None
        self._import_dialog: _ImportDialog | None = None
        self._import_active = False
        self._import_added_indices: list[int] = []
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
        self._render_in_progress = False
        self._render_state: dict | None = None
        self._log_handler: _GuiLogHandler | None = None
        self._log_sash_height = LOG_PANEL_DEFAULT_HEIGHT
        self._log_panel_visible = True
        self._avatar_panels: dict[int, RoundedAvatarPanel] = {}

        self._build_ui()
        self._setup_ui_fonts()
        self._setup_logging()
        self._bind_events()
        self.Centre()

        self._queue_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_queue_timer, self._queue_timer)
        self._queue_timer.Start(100)

        self._speaker_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_speaker_timer, self._speaker_timer)

        self._relayout_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_relayout_timer, self._relayout_timer)

        self._render_chunk_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_render_chunk_timer, self._render_chunk_timer)

        if initial_paths:
            self._add_paths(initial_paths)

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
        splitter = wx.SplitterWindow(self._content_wrap, style=wx.SP_LIVE_UPDATE)
        left = wx.Panel(splitter)
        right = wx.Panel(splitter)
        splitter.SplitVertically(left, right, 360)
        splitter.SetMinimumPaneSize(300)

        left_sizer = wx.BoxSizer(wx.VERTICAL)
        self._label_audio_file = wx.StaticText(left, label=t("label.audio_file"))
        path_row = wx.BoxSizer(wx.HORIZONTAL)
        self._audio_path = wx.TextCtrl(left, style=wx.TE_READONLY)
        self._btn_select = wx.Button(left, label=t("button.select"))
        path_row.Add(self._audio_path, 1, wx.EXPAND | wx.RIGHT, 8)
        path_row.Add(self._btn_select, 0)

        self._label_files = wx.StaticText(left, label=t("label.files"))
        self._search_box = wx.TextCtrl(left, style=wx.TE_PROCESS_ENTER)
        try:
            self._search_box.SetHint(t("hint.search"))
        except AttributeError:
            pass

        self._file_list = wx.ListCtrl(
            left,
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

        control_row = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_convert = wx.Button(left, label=t("button.convert"))
        self._chk_auto_convert = wx.CheckBox(left, label=t("button.auto_convert"))
        self._chk_show_log = wx.CheckBox(left, label=t("button.show_log"))
        self._chk_show_log.SetValue(True)
        control_row.Add(self._btn_convert, 0, wx.RIGHT, 12)
        control_row.Add(self._chk_auto_convert, 0, wx.RIGHT, 12)
        control_row.Add(self._chk_show_log, 0)

        left_sizer.Add(self._label_audio_file, 0, wx.BOTTOM, 4)
        left_sizer.Add(path_row, 0, wx.EXPAND | wx.BOTTOM, 8)
        left_sizer.Add(self._label_files, 0, wx.BOTTOM, 4)
        left_sizer.Add(self._search_box, 0, wx.EXPAND | wx.BOTTOM, 4)
        left_sizer.Add(self._file_list, 1, wx.EXPAND | wx.BOTTOM, 8)
        left_sizer.Add(control_row, 0)
        left.SetSizer(left_sizer)

        right_sizer = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self._title_label = wx.StaticText(right, label=t("status.no_session"))

        view_row = wx.BoxSizer(wx.HORIZONTAL)
        self._label_view = wx.StaticText(right, label=t("label.view"))
        self._rb_list = wx.RadioButton(right, label=t("view.list"), style=wx.RB_GROUP)
        self._rb_bubbles = wx.RadioButton(right, label=t("view.bubbles"))
        self._rb_bubbles.SetValue(True)
        view_row.Add(self._label_view, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        view_row.Add(self._rb_bubbles, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        view_row.Add(self._rb_list, 0, wx.ALIGN_CENTER_VERTICAL)
        header.Add(self._title_label, 1, wx.ALIGN_CENTER_VERTICAL)
        header.Add(view_row, 0, wx.ALIGN_CENTER_VERTICAL)

        self._meta_label = wx.StaticText(right, label=t("status.select_or_convert"))
        self._list_panel = wx.ScrolledWindow(right, style=wx.VSCROLL | wx.BORDER_NONE)
        self._list_panel.SetScrollRate(0, 10)
        self._list_sizer = wx.BoxSizer(wx.VERTICAL)
        self._list_panel.SetSizer(self._list_sizer)
        self._bubble_panel = wx.ScrolledWindow(right, style=wx.VSCROLL | wx.BORDER_NONE)
        self._bubble_panel.SetBackgroundColour(_rgb_colour(*CHAT_BG_RGB))
        self._bubble_panel.SetScrollRate(0, 10)
        self._bubble_sizer = wx.BoxSizer(wx.VERTICAL)
        self._bubble_panel.SetSizer(self._bubble_sizer)
        self._list_panel.Hide()

        right_sizer.Add(header, 0, wx.EXPAND | wx.BOTTOM, 4)
        right_sizer.Add(self._meta_label, 0, wx.EXPAND | wx.BOTTOM, 8)
        right_sizer.Add(self._list_panel, 1, wx.EXPAND)
        right_sizer.Add(self._bubble_panel, 1, wx.EXPAND)
        right.SetSizer(right_sizer)

        content_sizer.Add(splitter, 1, wx.EXPAND)
        self._content_wrap.SetSizer(content_sizer)

        self._log_wrap = wx.Panel(self._main_splitter)
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        self._label_log = wx.StaticText(self._log_wrap, label=t("label.log"))
        self._log_panel = wx.TextCtrl(
            self._log_wrap,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        log_sizer.Add(self._label_log, 0, wx.BOTTOM, 4)
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

    def _setup_ui_fonts(self) -> None:
        self._ui_font = _pick_unicode_font()
        self._ui_font_bold = _pick_unicode_font(weight=wx.FONTWEIGHT_BOLD)
        self._caption_font = wx.Font(self._ui_font)
        self._caption_font.SetPointSize(max(8, self._ui_font.GetPointSize() - 2))
        self._emoji_font = wx.Font(self._ui_font)
        self._emoji_font.SetPointSize(self._ui_font.GetPointSize() + 2)
        _apply_ui_font(self, self._ui_font)
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
        file_menu.Append(self.ID_OPEN_WAVEFORM, t("menu.open_waveform"))
        file_menu.Append(self.ID_OPEN_SESSION, t("menu.open_chat_session"))
        file_menu.AppendSeparator()
        file_menu.Append(self.ID_EXIT, t("menu.exit") + "\tCtrl+Q")

        lang_menu = wx.Menu()
        self._lang_menu_ids: dict[str, int] = {}
        for code in SUPPORTED_LOCALES:
            item_id = wx.NewIdRef()
            self._lang_menu_ids[code] = int(item_id)
            lang_menu.Append(item_id, t(f"lang.{code}"))

        menubar.Append(file_menu, t("menu.file"))
        menubar.Append(lang_menu, t("menu.language"))
        self.SetMenuBar(menubar)
        self._file_menu = file_menu
        self._lang_menu = lang_menu

    def _register_drop_targets(self) -> None:
        drop = _PathDropTarget(self._import_dropped_paths)
        self.SetDropTarget(drop)
        self._audio_path.SetDropTarget(_PathDropTarget(self._import_dropped_paths))
        self._file_list.SetDropTarget(_PathDropTarget(self._import_dropped_paths))

    def _bind_events(self) -> None:
        self.Bind(wx.EVT_MENU, lambda _e: self.open_waveform(), id=self.ID_OPEN_WAVEFORM)
        self.Bind(wx.EVT_MENU, lambda _e: self.open_chat_session(), id=self.ID_OPEN_SESSION)
        self.Bind(wx.EVT_MENU, lambda _e: self.Close(), id=self.ID_EXIT)
        for code, item_id in self._lang_menu_ids.items():
            self.Bind(
                wx.EVT_MENU,
                lambda event, locale=code: self.set_language(locale),
                id=item_id,
            )

        self._btn_select.Bind(wx.EVT_BUTTON, lambda _e: self.open_waveform())
        self._btn_convert.Bind(wx.EVT_BUTTON, lambda _e: self.convert_pending())
        self._chk_show_log.Bind(wx.EVT_CHECKBOX, self._on_show_log_toggled)
        self._main_splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_log_splitter_changed)
        self._file_list.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_file_selected)
        self._file_list.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._on_file_deselected)
        self._file_list.Bind(wx.EVT_LEFT_DOWN, self._on_file_list_left_down)
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

        self._accel_table = wx.AcceleratorTable(
            [
                (wx.ACCEL_CTRL, ord("O"), self.ID_OPEN_WAVEFORM),
                (wx.ACCEL_CTRL, ord("Q"), self.ID_EXIT),
            ]
        )
        self.SetAcceleratorTable(self._accel_table)

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
        self._append_log(logging.INFO, t(log_key, **kwargs))

    def _on_show_log_toggled(self, event: wx.CommandEvent) -> None:
        self._apply_log_panel_visibility(event.IsChecked())

    def _on_log_splitter_changed(self, event: wx.SplitterEvent) -> None:
        if self._log_panel_visible and self._main_splitter.IsSplit():
            sash = self._main_splitter.GetSashPosition()
            height = self._main_splitter.GetClientSize().height
            self._log_sash_height = max(LOG_PANEL_MIN_HEIGHT, height - sash)
        event.Skip()

    def _apply_log_panel_visibility(self, visible: bool) -> None:
        if visible == self._log_panel_visible:
            return
        self._log_panel_visible = visible
        if visible:
            self._log_wrap.Show()
            if not self._main_splitter.IsSplit():
                self._main_splitter.SplitHorizontally(
                    self._content_wrap,
                    self._log_wrap,
                    -self._log_sash_height,
                )
            else:
                height = self._main_splitter.GetClientSize().height
                self._main_splitter.SetSashPosition(
                    max(LOG_PANEL_MIN_HEIGHT, height - self._log_sash_height)
                )
        else:
            if self._main_splitter.IsSplit():
                sash = self._main_splitter.GetSashPosition()
                height = self._main_splitter.GetClientSize().height
                self._log_sash_height = max(LOG_PANEL_MIN_HEIGHT, height - sash)
                self._main_splitter.Unsplit(self._content_wrap)
            self._log_wrap.Hide()
        self._main_splitter.Layout()
        self.Layout()

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
        self._apply_locale()

    def _apply_locale(self) -> None:
        self.SetTitle(t("app.window_title"))
        menubar = self.GetMenuBar()
        if menubar:
            menubar.SetMenuLabel(0, t("menu.file"))
            menubar.SetMenuLabel(1, t("menu.language"))

        self._file_menu.SetLabel(self.ID_OPEN_WAVEFORM, t("menu.open_waveform"))
        self._file_menu.SetLabel(self.ID_OPEN_SESSION, t("menu.open_chat_session"))
        self._file_menu.SetLabel(self.ID_EXIT, t("menu.exit") + "\tCtrl+Q")
        for code, item_id in self._lang_menu_ids.items():
            self._lang_menu.SetLabel(item_id, t(f"lang.{code}"))

        self._label_audio_file.SetLabel(t("label.audio_file"))
        self._label_files.SetLabel(t("label.files"))
        try:
            if not self._search_box.HasFocus():
                self._search_box.SetHint(t("hint.search"))
        except AttributeError:
            pass
        self._btn_select.SetLabel(t("button.select"))
        self._btn_convert.SetLabel(t("button.convert"))
        self._chk_auto_convert.SetLabel(t("button.auto_convert"))
        self._chk_show_log.SetLabel(t("button.show_log"))
        self._label_view.SetLabel(t("label.view"))
        self._rb_list.SetLabel(t("view.list"))
        self._rb_bubbles.SetLabel(t("view.bubbles"))
        self._label_log.SetLabel(t("label.log"))
        col = self._file_list.GetColumn(NAME_COL)
        col.SetText(t("label.file_column"))
        self._file_list.SetColumn(NAME_COL, col)
        self._set_status(self._status_key, **self._status_kwargs)

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
        self._audio_path.SetValue("")
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
        json_path = default_json_path(entry.path)
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

    def _bind_segment_play(self, window: wx.Window, segment_index: int) -> None:
        def on_click(event: wx.MouseEvent) -> None:
            self._on_segment_clicked(segment_index)

        window.Bind(wx.EVT_LEFT_DOWN, on_click)
        window.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        for child in window.GetChildren():
            self._bind_segment_play(child, segment_index)

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
        if entry is None or entry.transcript is None:
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
        self._audio_path.SetValue(str(entry.path))
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
        event.Skip()

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
        speaker_icon = self._make_speaker_icon(row)
        row_sizer.Add(message_ctrl, 0, wx.ALL, 8)
        speaker_icon.SetBackgroundColour(row_colour)
        row_sizer.Add(speaker_icon, 0, wx.ALIGN_TOP | wx.RIGHT, 6)
        row.SetSizer(row_sizer)
        self._list_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
        self._register_segment_row(row, row_colour, segment_index)
        self._segment_scroll_targets[segment_index] = row
        self._speaker_icons[segment_index] = speaker_icon
        self._bind_segment_play(row, segment_index)

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

        speaker_icon = self._make_speaker_icon(row_panel)
        self._speaker_icons[segment_index] = speaker_icon
        speaker_icon.SetBackgroundColour(chat_bg)

        bubble_top_flag = wx.ALIGN_TOP | wx.TOP
        bubble_top_border = first_line_top_pad if show_avatar else 0
        avatar_sizer_flags = wx.ALIGN_TOP | wx.LEFT | wx.RIGHT
        avatar_sizer_border = BUBBLE_AVATAR_H_MARGIN

        if is_me:
            row_sizer.AddStretchSpacer(1)
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
            row_sizer.Add(speaker_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
            row_sizer.AddStretchSpacer(1)

        row_panel.SetSizer(row_sizer)
        self._bubble_sizer.Add(row_panel, 0, wx.EXPAND | wx.TOP, row_gap)
        self._register_segment_row(bubble, bubble_colour, segment_index)
        self._segment_scroll_targets[segment_index] = row_panel
        self._bind_segment_play(row_panel, segment_index)

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
    ) -> None:
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
        collected: list[Path] = []
        seen: set[Path] = set()
        for raw in paths:
            path = raw.expanduser().resolve()
            if path.is_dir():
                try:
                    children = sorted(path.iterdir())
                except OSError:
                    continue
                for child in children:
                    if is_supported_audio(child) and child not in seen:
                        seen.add(child)
                        collected.append(child)
                continue
            if is_supported_audio(path) and path not in seen:
                seen.add(path)
                collected.append(path)
        return collected

    def _try_load_json_for_entry(self, entry: FileEntry) -> bool:
        if entry.status == "converted" and entry.transcript is not None:
            return False
        json_path = default_json_path(entry.path)
        if not json_path.is_file():
            return False
        try:
            entry.transcript = Transcript.load_json(json_path)
            entry.status = "converted"
            entry.error = None
            return True
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _append_entry(self, path: Path) -> int | None:
        """Add or refresh an entry. Returns its index, or None if unchanged."""
        for index, entry in enumerate(self.entries):
            if entry.path == path:
                if self._try_load_json_for_entry(entry):
                    return index
                return None
        json_path = default_json_path(path)
        if json_path.is_file():
            try:
                transcript = Transcript.load_json(json_path)
                self.entries.append(
                    FileEntry(path=path, status="converted", transcript=transcript)
                )
                return len(self.entries) - 1
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.entries.append(FileEntry(path=path))
        return len(self.entries) - 1

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

    def open_waveform(self) -> None:
        dialog = wx.FileDialog(
            self,
            message=t("dialog.open_waveform"),
            wildcard=f"{t('filetype.audio')}|{AUDIO_WILDCARD}|{t('filetype.all')}|*.*",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        paths = dialog.GetPaths()
        dialog.Destroy()
        if paths:
            self._add_paths([Path(path) for path in paths])

    def open_chat_session(self) -> None:
        dialog = wx.FileDialog(
            self,
            message=t("dialog.open_chat_session"),
            wildcard=f"{t('filetype.json')}|{JSON_WILDCARD}|{t('filetype.all')}|*.*",
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

        source_path = path.with_suffix("")
        for ext in SUPPORTED_EXTENSIONS:
            candidate = source_path.with_suffix(ext)
            if candidate.is_file():
                source_path = candidate
                break

        entry = FileEntry(path=source_path, status="converted", transcript=transcript)
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
            self._ui_queue.put(("status_text", ("status.loading_models", {})))
            self._backend = FunASRBackend(
                min_speakers=self.settings.min_speakers,
                max_speakers=self.settings.max_speakers,
            )
        return self._backend

    def convert_pending(self) -> None:
        self._convert_entry_indices(self._convert_target_entry_indices())

    def _convert_entry_indices(self, indices: list[int]) -> None:
        if self._convert_thread and self._convert_thread.is_alive():
            return

        pending = [
            index
            for index in indices
            if 0 <= index < len(self.entries)
            and self.entries[index].status in {"unconverted", "error"}
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

        self._converting_active = True
        self._set_progress(0)
        self._append_log(
            logging.INFO,
            t("log.start_batch", count=len(pending)),
        )

        self._btn_convert.Disable()
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
            self._sync_file_list()
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
            self._btn_convert.Enable()
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
    )

    initial_paths: list[Path] = []
    if args.input is not None:
        initial_paths.append(args.input)

    frame = Wav2ChatFrame(settings, initial_paths=initial_paths or None)
    frame.Show()
    app.MainLoop()
    return 0
