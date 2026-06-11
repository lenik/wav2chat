"""Main application frame for the wav2chat wx GUI."""

from __future__ import annotations

import logging
import queue
import threading
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
from wav2chat.errors import Wav2ChatError
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.i18n import SUPPORTED_LOCALES, set_locale, t
from wav2chat.models import Transcript
from wav2chat.pipeline import write_transcript_outputs
from wav2chat.phone_import import PhoneImportResult
from wav2chat.gui.phone_import_dialog import PhoneImportDialog
from wav2chat.gui.settings_dialog import SettingsDialog
from wav2chat.gui.speaker_ui import SpeakerProfileDialog
from wav2chat.ui_fonts import apply_ui_font, pick_unicode_font

from wav2chat.gui.constants import (
    AUDIO_WILDCARD,
    CHATLOG_WILDCARD,
    FILE_PANEL_DEFAULT_WIDTH,
    LOG_PANEL_DEFAULT_HEIGHT,
    LOG_PANEL_MIN_HEIGHT,
    MIN_CHAT_PANEL_WIDTH,
    MIN_FILE_PANEL_WIDTH,
    MIN_TREE_PANEL_WIDTH,
    NAME_COL,
    OCCUR_COL,
    OCCUR_COL_WIDTH,
    TIMESTAMP_COL,
    PANEL_PADDING,
    SPLITTER_GUTTER,
    STATUS_COL,
    STATUS_PROGRESS_WIDTH,
    TOOLBAR_BITMAP_LARGE,
    TOOLBAR_BITMAP_MEDIUM,
    rgb_colour,
)
from wav2chat.gui.entry_helpers import (
    entry_has_playable_audio,
    entry_json_path,
    entry_meta,
    entry_title,
    find_audio_for_stem,
)
from wav2chat.gui.log_handler import GuiLogHandler
from wav2chat.gui.models import FileEntry, GuiSettings
from wav2chat.gui.status_icons import build_status_image_list
from wav2chat.gui.browser_mixin import BrowserMixin
from wav2chat.gui.conversion_mixin import ConversionMixin
from wav2chat.gui.entry_store_mixin import EntryStoreMixin
from wav2chat.gui.ui_queue_mixin import UiQueueMixin
from wav2chat.gui.widgets.transcript_chat_view import TranscriptChatView
from wav2chat.gui.widgets.common import (
    IntSpinRow,
    append_menu_item,
    play_stock_bitmap,
)
from wav2chat.gui.widgets.dir_tree import DirTree
from wav2chat.gui.widgets.drop_target import PathDropTarget
from wav2chat.gui.widgets.import_dialog import ImportDialog
from wav2chat.gui.widgets.path_breadcrumb import PathBreadcrumb
from wav2chat.gui.widgets.recording_list import RecordingList

class Wav2ChatFrame(
    wx.Frame,
    BrowserMixin,
    EntryStoreMixin,
    ConversionMixin,
    UiQueueMixin,
):
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
        self.view_mode = "bubbles"
        self._status_key = "status.ready"
        self._status_kwargs: dict[str, object] = {}
        self._backend: FunASRBackend | None = None
        self._convert_thread: threading.Thread | None = None
        self._import_thread: threading.Thread | None = None
        self._import_dialog: ImportDialog | None = None
        self._import_active = False
        self._import_added_indices: list[int] = []
        self._load_generation = 0
        self._load_thread: threading.Thread | None = None
        self._load_in_progress = False
        self._load_append_mode = False
        self._load_added_indices: list[int] = []
        self._search_generation = 0
        self._search_thread: threading.Thread | None = None
        self._entry_occur_counts: list[int] = []
        self._list_sort_column = TIMESTAMP_COL
        self._list_sort_ascending = False
        self._occur_column_visible = False
        self._phone_import_dialog: PhoneImportDialog | None = None
        self._pending_browser_directory: Path | None = None
        self._stop_convert = threading.Event()
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._status_images = build_status_image_list()
        self._segment_player = SegmentPlayer()
        self._search_keywords: list[str] = []
        self._visible_entry_indices: list[int] = []
        self._search_debounce_generation = 0
        self._selection_explicit_empty = False
        self._suppress_file_select = False
        self._converting_active = False
        self._last_progress_log_phase: str | None = None
        self._last_progress_log_percent: int | None = None
        self._log_handler: GuiLogHandler | None = None
        self._log_sash_height = self.app_settings.log_sash_height or LOG_PANEL_DEFAULT_HEIGHT
        self._log_panel_visible = True
        self._directory_tree_visible = True
        self._toolbar_visible = self.app_settings.toolbar_visible
        self._splitter_browser_pos = self.app_settings.splitter_browser_pos or 240
        self._splitter_file_pos = self.app_settings.splitter_main_pos or FILE_PANEL_DEFAULT_WIDTH
        self._file_list_needs_sync = False

        self._build_ui()
        self._setup_ui_fonts()
        self._setup_logging()
        self._bind_events()

        self._queue_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_queue_timer, self._queue_timer)
        self._queue_timer.Start(100)

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
        self._path_breadcrumb = PathBreadcrumb(
            self._breadcrumb_bar,
            on_navigate=self._navigate_from_breadcrumb,
            get_background=lambda: self._content_wrap.GetBackgroundColour(),
        )
        breadcrumb_row = wx.BoxSizer(wx.HORIZONTAL)
        breadcrumb_row.Add(self._build_home_nav_button(self._breadcrumb_bar), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        breadcrumb_row.Add(self._path_breadcrumb.panel, 1, wx.EXPAND)
        breadcrumb_sizer.Add(breadcrumb_row, 0, wx.EXPAND)
        self._breadcrumb_bar.SetSizer(breadcrumb_sizer)
        self._path_breadcrumb.apply_colours()

        self._browser_splitter = wx.SplitterWindow(self._content_wrap, style=wx.SP_LIVE_UPDATE)
        self._dir_tree_widget = DirTree(
            self._browser_splitter,
            on_directory_selected=self._load_directory_files,
        )
        self._tree_panel = self._dir_tree_widget.panel
        self._work_panel = wx.Panel(self._browser_splitter)
        self._chk_recursive = self._dir_tree_widget.recursive_checkbox
        self._dir_tree_widget.set_recursive_label(t("label.recursive"))

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

        self._dir_tree = self._dir_tree_widget.tree

        file_sizer = wx.BoxSizer(wx.VERTICAL)
        files_header = wx.BoxSizer(wx.HORIZONTAL)
        self._label_files = wx.StaticText(self._file_panel, label=t("label.files"))
        self._label_max_items = wx.StaticText(self._file_panel, label=t("label.max_items"))
        self._max_items_ctrl = wx.TextCtrl(
            self._file_panel,
            value="",
            size=wx.Size(44, -1),
            style=wx.TE_CENTRE,
        )
        self._label_max_items_unit = wx.StaticText(
            self._file_panel,
            label=t("label.max_items_unit"),
        )
        files_header.Add(self._label_files, 0, wx.ALIGN_CENTER_VERTICAL)
        files_header.AddStretchSpacer(1)
        files_header.Add(self._label_max_items, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        files_header.Add(self._max_items_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        files_header.Add(self._label_max_items_unit, 0, wx.ALIGN_CENTER_VERTICAL)
        self._search_box = wx.TextCtrl(self._file_panel, style=wx.TE_PROCESS_ENTER)
        try:
            self._search_box.SetHint(t("hint.search"))
        except AttributeError:
            pass

        self._recording_list = RecordingList(
            self._file_panel,
            self._status_images,
            on_selected=self._on_recording_list_selected,
            on_deselected=self._on_recording_list_deselected,
            on_left_down=self._on_file_list_left_down,
            on_motion=self._on_file_list_motion,
            on_leave=self._on_file_list_leave,
            on_key_down=self._on_file_list_key_down,
            on_column_sort=self._on_file_list_column_sort,
        )
        self._recording_list.bind_host(self)
        self._file_list = self._recording_list.list_ctrl
        self._file_list_wrap = self._recording_list.wrap_panel

        min_speakers, max_speakers = self._speaker_count_defaults()
        speaker_row = wx.BoxSizer(wx.HORIZONTAL)
        self._label_speaker_count = wx.StaticText(self._file_panel, label=t("label.speaker_count"))
        self._spin_min_speakers = IntSpinRow(self._file_panel, min_speakers)
        self._label_speaker_to = wx.StaticText(self._file_panel, label=t("label.speaker_count_to"))
        self._spin_max_speakers = IntSpinRow(self._file_panel, max_speakers)
        self._label_speaker_unit = wx.StaticText(self._file_panel, label=t("label.speaker_count_unit"))
        speaker_row.Add(self._label_speaker_count, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        speaker_row.Add(self._spin_min_speakers, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        speaker_row.Add(self._label_speaker_to, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        speaker_row.Add(self._spin_max_speakers, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        speaker_row.Add(self._label_speaker_unit, 0, wx.ALIGN_CENTER_VERTICAL)

        control_row = wx.BoxSizer(wx.HORIZONTAL)
        self._btn_convert = wx.Button(self._file_panel, label=t("button.convert"))
        play_bitmap = play_stock_bitmap()
        if play_bitmap.IsOk():
            self._btn_convert.SetBitmap(play_bitmap)
            self._btn_convert.SetBitmapPosition(wx.LEFT)
        self._btn_convert.Bind(wx.EVT_BUTTON, self._on_convert_clicked)
        self._chk_auto_convert = wx.CheckBox(self._file_panel, label=t("button.auto_convert"))
        control_row.Add(self._btn_convert, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 12)
        control_row.AddStretchSpacer(1)
        control_row.Add(self._chk_auto_convert, 0, wx.ALIGN_CENTER_VERTICAL)

        file_sizer.Add(files_header, 0, wx.EXPAND | wx.BOTTOM, 4)
        file_sizer.Add(self._search_box, 0, wx.EXPAND | wx.BOTTOM, 4)
        file_sizer.Add(self._file_list_wrap, 1, wx.EXPAND | wx.BOTTOM, 8)
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
        self._chat_panel = chat_panel
        self._chat_view: TranscriptChatView | None = None

        right_sizer.Add(header, 0, wx.EXPAND | wx.BOTTOM, 4)
        right_sizer.Add(self._meta_label, 0, wx.EXPAND | wx.BOTTOM, 8)
        self._chat_right_sizer = right_sizer
        chat_outer = wx.BoxSizer(wx.HORIZONTAL)
        chat_outer.Add(right_sizer, 1, wx.EXPAND | wx.LEFT, SPLITTER_GUTTER)
        chat_panel.SetSizer(chat_outer)

        content_sizer.Add(self._breadcrumb_bar, 0, wx.EXPAND | wx.BOTTOM, 4)
        content_sizer.Add(self._browser_splitter, 1, wx.EXPAND)
        self._content_wrap.SetSizer(content_sizer)
        self._splitter_main = splitter_main

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
        self._init_chat_view()

    def _init_chat_view(self) -> None:
        if self._chat_view is not None:
            return
        self._chat_view = TranscriptChatView(
            self._chat_panel,
            get_focus_entry=self._get_focus_entry,
            get_search_keywords=lambda: self._search_keywords,
            get_view_mode=lambda: self.view_mode,
            on_segment_click=self._on_segment_clicked,
            on_speaker_profile=self._open_speaker_profile,
            on_set_primary_speaker=self._set_primary_speaker,
            save_entry_transcript=self._save_entry_transcript,
            segment_player=self._segment_player,
            title_label=self._title_label,
            meta_label=self._meta_label,
            ui_font=self._ui_font,
            ui_font_bold=self._ui_font_bold,
            emoji_font=self._emoji_font,
        )
        self._list_panel = self._chat_view.list_panel
        self._bubble_panel = self._chat_view.bubble_panel
        self._rb_list.Bind(wx.EVT_RADIOBUTTON, self._on_view_changed)
        self._rb_bubbles.Bind(wx.EVT_RADIOBUTTON, self._on_view_changed)
        self._chat_right_sizer.Add(self._list_panel, 1, wx.EXPAND)
        self._chat_right_sizer.Add(self._bubble_panel, 1, wx.EXPAND)
        self._chat_panel.Layout()

    def _effective_log_level(self) -> int:
        if self.settings.quiet and not self.settings.verbose:
            return logging.ERROR
        if self.settings.verbose:
            return logging.DEBUG
        return logging.INFO

    def _setup_logging(self) -> None:
        level = self._effective_log_level()
        self._log_handler = GuiLogHandler(
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
        append_menu_item(
            file_menu,
            self.ID_OPEN_DIRECTORY,
            t("menu.open_directory"),
            art_id=wx.ART_FOLDER_OPEN,
        )
        append_menu_item(
            file_menu,
            self.ID_OPEN_SESSION,
            t("menu.open_chat_session"),
            art_id=wx.ART_FILE_OPEN,
        )
        append_menu_item(
            file_menu,
            self.ID_IMPORT_PHONE,
            t("menu.import_from_phone"),
            art_id=wx.ART_GO_DOWN,
        )
        file_menu.AppendSeparator()
        append_menu_item(
            file_menu,
            self.ID_REFRESH_MODELS,
            t("menu.refresh_models"),
            kind=wx.ITEM_CHECK,
        )
        file_menu.Check(self.ID_REFRESH_MODELS, self.settings.refresh_models)
        file_menu.AppendSeparator()
        append_menu_item(
            file_menu,
            self.ID_EXIT,
            t("menu.exit") + "\tCtrl+Q",
            art_id=wx.ART_QUIT,
        )

        edit_menu = wx.Menu()
        append_menu_item(
            edit_menu,
            self.ID_SETTINGS,
            t("menu.settings"),
            art_id=wx.ART_HELP_SETTINGS,
        )

        view_menu = wx.Menu()
        append_menu_item(
            view_menu,
            self.ID_REFRESH_BROWSER,
            t("menu.refresh_browser"),
            art_id=wx.ART_REDO,
        )
        view_menu.AppendSeparator()
        append_menu_item(
            view_menu,
            self.ID_SHOW_DIRECTORY,
            t("menu.show_directory"),
            kind=wx.ITEM_CHECK,
        )
        append_menu_item(
            view_menu,
            self.ID_SHOW_LOG,
            t("menu.show_loggings"),
            kind=wx.ITEM_CHECK,
        )
        view_menu.AppendSeparator()
        append_menu_item(
            view_menu,
            self.ID_SHOW_TOOLBAR,
            t("menu.show_toolbar"),
            kind=wx.ITEM_CHECK,
        )
        append_menu_item(
            view_menu,
            self.ID_LARGE_TOOLS,
            t("menu.large_tools"),
            kind=wx.ITEM_CHECK,
        )
        append_menu_item(
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
        drop = PathDropTarget(self._import_dropped_paths)
        self.SetDropTarget(drop)
        self._file_list.SetDropTarget(PathDropTarget(self._import_dropped_paths))

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
            _from_toggle=False,
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
        wx.CallAfter(self._focus_directory_tree_on_startup)

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

    def _focus_directory_tree_on_startup(self) -> None:
        if not self._directory_tree_ui_active():
            return
        self._dir_tree_widget.focus_selected(self._current_directory)

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
        _from_toggle: bool = True,
    ) -> None:
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

    def refresh_browser(self) -> None:
        if self._converting_active:
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
            self._dir_tree_widget.mark_needs_init()
            self._dir_tree_widget.defer_directory(directory)
        self._load_directory_files(directory)

    def _entry_at(self, index: int | None) -> FileEntry | None:
        if index is None or index < 0 or index >= len(self.entries):
            return None
        return self.entries[index]

    def _get_focus_entry(self) -> FileEntry | None:
        return self._entry_at(self.focus_index)

    def _set_breadcrumbs(self, directory: Path) -> None:
        self._path_breadcrumb.set_directory(directory)

    def _apply_breadcrumb_nav_colours(self) -> None:
        self._path_breadcrumb.apply_colours()

    def _navigate_from_breadcrumb(self, directory: Path) -> None:
        if self._converting_active:
            return
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            return
        self._dir_tree_widget.select_directory(directory, ui_active=self._directory_tree_ui_active())
        self._load_directory_files(directory)

    def _init_directory_tree(self) -> None:
        if not self._directory_tree_ui_active():
            self._dir_tree_widget.mark_needs_init()
            return
        self._dir_tree_widget.init()

    def _select_tree_directory(self, directory: Path) -> None:
        self._dir_tree_widget.select_directory(directory, ui_active=self._directory_tree_ui_active())

    def _flush_deferred_browser_ui(self) -> None:
        if not self._directory_tree_ui_active():
            return
        self._dir_tree_widget.flush_if_needed(ui_active=True)
        if self._file_list_needs_sync:
            self._file_list_needs_sync = False
            self._sync_file_list(force=True)

    def _list_row_for_entry(self, entry_index: int) -> int | None:
        return self._recording_list.list_row_for_entry(entry_index)

    def _entry_index_at_list_row(self, list_row: int) -> int | None:
        return self._recording_list.entry_index_at_list_row(list_row)

    def _list_selected_rows(self) -> list[int]:
        return self._recording_list.list_selected_rows()

    def _selected_entry_indices(self) -> list[int]:
        return self._recording_list.selected_entry_indices()

    def _deselect_all_file_rows(self) -> None:
        self._recording_list.deselect_all_rows()

    def _select_all_visible_files(self) -> None:
        self._recording_list.select_all_visible()

    def _set_file_list_selection(self, selected_entries, *, focus_entry, preserve_search_focus) -> None:
        self._recording_list.set_selection(
            selected_entries,
            focus_entry=focus_entry,
            preserve_search_focus=preserve_search_focus,
            search_box=self._search_box,
        )

    def _resize_file_list_columns(self) -> None:
        self._recording_list.resize_columns()

    def _set_file_row_status_image(self, list_row: int, entry: FileEntry) -> None:
        self._recording_list.set_row_status_image(list_row, entry)

    def _show_load_bar(self, fraction: float) -> None:
        self._recording_list.show_load_bar(fraction)

    def _hide_load_bar(self) -> None:
        self._recording_list.hide_load_bar()

    def _set_occur_column_visible(self, visible: bool) -> None:
        self._recording_list.set_occur_column_visible(visible)

    def _sync_file_list(self, *, restore_selection=None, preserve_search_focus=False, force=False) -> None:
        self._recording_list.sync(
            restore_selection=restore_selection,
            preserve_search_focus=preserve_search_focus,
            force=force,
            search_box=self._search_box,
            rebuild_visible=self._rebuild_visible_entries,
        )

    def _update_row_status(self, entry_index: int) -> None:
        self._recording_list.update_row_status(entry_index)

    def _file_name_truncated(self, list_row: int) -> bool:
        return self._recording_list.name_truncated(list_row)

    def _set_file_list_name_tooltip(self, text: str) -> None:
        self._recording_list.set_name_tooltip(text)

    def _clear_chat_view(self) -> None:
        if self._chat_view is not None:
            self._chat_view.clear()

    def _fit_chat_panels(self) -> None:
        if self._chat_view is not None:
            self._chat_view.fit_panels()

    def _render_transcript(self, entry: FileEntry, relayout: bool = False) -> None:
        if self._chat_view is not None:
            self._chat_view.render_transcript(entry, relayout=relayout)

    def _refresh_chat_view(self) -> None:
        if self._chat_view is not None:
            self._chat_view.refresh_view(self.view_mode == "bubbles")

    def _save_entry_transcript(self, entry: FileEntry) -> None:
        if entry.transcript is None:
            return
        json_path = entry_json_path(entry)
        write_transcript_outputs(entry.transcript, json_path=json_path, quiet=True)

    def _open_speaker_profile(self, speaker_index: int) -> None:
        entry = self._get_focus_entry()
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

    def _set_primary_speaker(self, speaker_index: int) -> None:
        entry = self._get_focus_entry()
        if entry is None or entry.transcript is None:
            return
        if speaker_index < 0 or speaker_index >= len(entry.transcript.speakers):
            return
        entry.transcript.primary_speaker = speaker_index
        self._save_entry_transcript(entry)
        self._render_transcript(entry, relayout=False)

    def _on_segment_clicked(self, segment_index: int) -> None:
        entry = self._get_focus_entry()
        if entry is None or entry.transcript is None or not entry_has_playable_audio(entry):
            return
        segments = entry.transcript.segments
        if segment_index < 0 or segment_index >= len(segments):
            return
        segment = segments[segment_index]
        start, end = segment_play_range(segment, entry.transcript.duration)
        self._chat_view.playing_segment_index = segment_index
        self._chat_view.show_playing_speaker(segment_index)
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
            self._chat_view.playing_segment_index = None
            self._chat_view.hide_playing_speaker()
            self._set_status("status.playback_failed", error=exc)
            wx.MessageBox(
                t("status.playback_failed", error=exc),
                t("dialog.error_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )

    def _on_playback_finished(self) -> None:
        self._chat_view.playing_segment_index = None
        self._chat_view.hide_playing_speaker()
        self._set_status("status.ready")



    def _on_recording_list_selected(self, list_row: int) -> None:
        self._selection_explicit_empty = False
        entry_index = self._entry_index_at_list_row(list_row)
        entry = self._entry_at(entry_index)
        if entry is None:
            return
        self.focus_index = entry_index
        wx.CallAfter(self._show_entry, entry)

    def _on_recording_list_deselected(self) -> None:
        if self._file_list.GetSelectedItemCount() == 0:
            self._selection_explicit_empty = True

    def _on_view_changed(self, _event: wx.CommandEvent) -> None:
        self.view_mode = "bubbles" if self._rb_bubbles.GetValue() else "list"
        if self._chat_view is not None:
            self._refresh_chat_view()

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
        self._search_box.Bind(wx.EVT_TEXT, self._on_search_changed)
        self._search_box.Bind(wx.EVT_TEXT_ENTER, self._on_search_submit)
        self._search_box.Bind(wx.EVT_SET_FOCUS, self._on_search_focus)
        self._search_box.Bind(wx.EVT_KILL_FOCUS, self._on_search_kill_focus)

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
        self._label_max_items.SetLabel(t("label.max_items"))
        self._label_max_items_unit.SetLabel(t("label.max_items_unit"))
        self._dir_tree_widget.set_recursive_label(t("label.recursive"))
        self._recording_list.apply_locale()
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
            play_bitmap = play_stock_bitmap()
            if play_bitmap.IsOk():
                self._btn_convert.SetBitmap(play_bitmap)
                self._btn_convert.SetBitmapPosition(wx.LEFT)
        self._label_view.SetLabel(t("label.view"))
        self._rb_list.SetLabel(t("view.list"))
        self._rb_bubbles.SetLabel(t("view.bubbles"))
        self._set_occur_column_visible(self._occur_column_visible)
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


    def _on_search_changed(self, _event: wx.CommandEvent) -> None:
        self._search_debounce_generation += 1
        generation = self._search_debounce_generation
        wx.CallLater(200, lambda: self._commit_search_if_current(generation))

    def _commit_search_if_current(self, generation: int) -> None:
        if generation != self._search_debounce_generation:
            return
        self._apply_search_filter(preserve_search_focus=self._search_box.HasFocus())

    def _on_search_focus(self, event: wx.FocusEvent) -> None:
        # Frame accelerators run before child key events and can block IME
        # shortcuts such as Ctrl+` on Linux.
        self.SetAcceleratorTable(wx.AcceleratorTable())
        event.Skip()

    def _on_search_submit(self, _event: wx.CommandEvent) -> None:
        self._search_debounce_generation += 1
        self._apply_search_filter(preserve_search_focus=True)

    def _on_search_kill_focus(self, event: wx.FocusEvent) -> None:
        self.SetAcceleratorTable(self._accel_table)
        event.Skip()



    def _clear_session_view(self) -> None:
        self.focus_index = None
        self._title_label.SetLabel(t("status.no_session"))
        self._title_label.SetFont(self._ui_font_bold)
        self._meta_label.SetLabel(t("status.select_or_convert"))
        self._clear_chat_view()

    def _on_close(self, event: wx.CloseEvent) -> None:
        if self._chat_view is not None:
            self._chat_view.stop_on_close()
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
            self._title_label.SetLabel(entry_title(entry.path))
            self._title_label.SetFont(self._ui_font_bold)
            self._meta_label.SetLabel(entry_meta(entry.path, None))
            self._clear_chat_view()

    def _on_file_list_motion(self, event: wx.MouseEvent) -> None:
        pos = event.GetPosition()
        list_row, flags = self._file_list.HitTest(pos)
        tooltip = ""
        if list_row != wx.NOT_FOUND and (flags & wx.LIST_HITTEST_ONITEMLABEL):
            if self._file_name_truncated(list_row):
                tooltip = self._file_list.GetItemText(list_row, NAME_COL)
        self._set_file_list_name_tooltip(tooltip)
        event.Skip()

    def _on_file_list_leave(self) -> None:
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

    def _open_import_dialog(self) -> None:
        self._close_import_dialog()
        self._import_dialog = ImportDialog(self)
        self._import_dialog.Show()
        self._import_dialog.Raise()


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
        if self._load_in_progress:
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

        audio = find_audio_for_stem(path.with_suffix(""))
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
