"""Recording file list widget with load progress bar."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

import wx

from wav2chat.gui.constants import (
    NAME_COL,
    OCCUR_COL,
    OCCUR_COL_WIDTH,
    STATUS_COL,
    STATUS_COL_WIDTH,
    TIMESTAMP_COL,
    TIMESTAMP_COL_WIDTH,
)
from wav2chat.gui.entry_helpers import entry_label, entry_timestamp_label
from wav2chat.gui.models import FileEntry
from wav2chat.gui.status_icons import status_image_index
from wav2chat.gui.widgets.common import FileListLoadBar
from wav2chat.i18n import t


class RecordingListHost(Protocol):
    entries: list[FileEntry]
    focus_index: int | None
    _visible_entry_indices: list[int]
    _entry_occur_counts: list[int]
    _occur_column_visible: bool
    _selection_explicit_empty: bool
    _search_keywords: list[str]
    _file_list_needs_sync: bool
    _suppress_file_select: bool
    _list_sort_column: int
    _list_sort_ascending: bool

    def _search_box(self) -> wx.TextCtrl: ...


class RecordingList:
    """File list control with load bar, columns, sync, and selection helpers."""

    def __init__(
        self,
        parent: wx.Window,
        status_images: wx.ImageList,
        *,
        on_selected: Callable[[int], None],
        on_deselected: Callable[[], None],
        on_left_down: Callable[[wx.MouseEvent], None],
        on_motion: Callable[[wx.MouseEvent], None],
        on_leave: Callable[[], None],
        on_key_down: Callable[[wx.KeyEvent], None],
        on_column_sort: Callable[[int], None],
    ) -> None:
        self._status_images = status_images
        self._on_selected = on_selected
        self._on_deselected = on_deselected
        self._on_left_down = on_left_down
        self._on_motion = on_motion
        self._on_leave = on_leave
        self._on_key_down = on_key_down
        self._on_column_sort = on_column_sort
        self._host: RecordingListHost | None = None

        self._wrap = wx.Panel(parent)
        wrap_sizer = wx.BoxSizer(wx.VERTICAL)
        self._load_bar = FileListLoadBar(self._wrap)
        self._load_bar.Hide()
        self.list_ctrl = wx.ListCtrl(
            self._wrap,
            style=wx.LC_REPORT | wx.BORDER_SUNKEN,
        )
        self.list_ctrl.SetWindowStyleFlag(
            self.list_ctrl.GetWindowStyleFlag() & ~wx.LC_SINGLE_SEL
        )
        self.list_ctrl.SetImageList(status_images, wx.IMAGE_LIST_SMALL)
        self.list_ctrl.InsertColumn(
            NAME_COL,
            t("label.file_column"),
            format=wx.LIST_FORMAT_LEFT,
            width=200,
        )
        self.list_ctrl.InsertColumn(
            TIMESTAMP_COL,
            t("label.file_column_timestamp"),
            format=wx.LIST_FORMAT_LEFT,
            width=TIMESTAMP_COL_WIDTH,
        )
        self.list_ctrl.InsertColumn(
            OCCUR_COL,
            t("label.file_column_occur"),
            format=wx.LIST_FORMAT_RIGHT,
            width=0,
        )
        self.list_ctrl.InsertColumn(
            STATUS_COL,
            "",
            format=wx.LIST_FORMAT_CENTRE,
            width=STATUS_COL_WIDTH,
        )
        wrap_sizer.Add(self._load_bar, 0, wx.EXPAND)
        wrap_sizer.Add(self.list_ctrl, 1, wx.EXPAND)
        self._wrap.SetSizer(wrap_sizer)

        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._handle_selected)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_DESELECTED, self._handle_deselected)
        self.list_ctrl.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.list_ctrl.Bind(wx.EVT_MOTION, self._on_motion)
        self.list_ctrl.Bind(wx.EVT_LEAVE_WINDOW, lambda _e: self._on_leave())
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.list_ctrl.Bind(wx.EVT_SIZE, self._on_size)
        self.list_ctrl.Bind(wx.EVT_LIST_COL_CLICK, self._on_column_click)

    _SORT_ASC_MARK = " \u2191"
    _SORT_DESC_MARK = " \u2193"

    def _sortable_column_labels(self) -> dict[int, str]:
        return {
            NAME_COL: t("label.file_column"),
            TIMESTAMP_COL: t("label.file_column_timestamp"),
            OCCUR_COL: t("label.file_column_occur"),
        }

    def refresh_sort_headers(self) -> None:
        if self._host is None:
            return
        sort_column = self._host._list_sort_column
        ascending = self._host._list_sort_ascending
        mark = self._SORT_ASC_MARK if ascending else self._SORT_DESC_MARK
        for column, base_label in self._sortable_column_labels().items():
            label = base_label + (mark if column == sort_column else "")
            col = self.list_ctrl.GetColumn(column)
            col.SetText(label)
            self.list_ctrl.SetColumn(column, col)

    def _on_column_click(self, event: wx.ListEvent) -> None:
        column = event.GetColumn()
        if column in (NAME_COL, TIMESTAMP_COL, OCCUR_COL):
            self._on_column_sort(column)
        event.Skip()

    def attach_host(self, host: RecordingListHost) -> None:
        self._host = host

    @property
    def wrap_panel(self) -> wx.Panel:
        return self._wrap

    def bind_host(self, host: Any) -> None:
        self._host = host

    def _handle_selected(self, event: wx.ListEvent) -> None:
        if self._host is not None and self._host._suppress_file_select:
            self._host._suppress_file_select = False
            return
        self._on_selected(event.GetIndex())

    def _handle_deselected(self, _event: wx.ListEvent) -> None:
        self._on_deselected()

    def _on_size(self, event: wx.SizeEvent) -> None:
        self.resize_columns()
        event.Skip()

    def show_load_bar(self, fraction: float) -> None:
        if not self._load_bar.IsShown():
            self._load_bar.Show()
            self._wrap.Layout()
        self._load_bar.set_fraction(fraction)

    def hide_load_bar(self) -> None:
        if self._load_bar.IsShown():
            self._load_bar.Hide()
            self._wrap.Layout()

    def set_occur_column_visible(self, visible: bool) -> None:
        if self._host is None:
            return
        self._host._occur_column_visible = visible
        width = OCCUR_COL_WIDTH if visible else 0
        self.list_ctrl.SetColumnWidth(OCCUR_COL, width)
        self.resize_columns()

    def resize_columns(self) -> None:
        client_size = self.list_ctrl.GetClientSize()
        occur_visible = self._host._occur_column_visible if self._host else False
        occur_width = OCCUR_COL_WIDTH if occur_visible else 0
        fixed_width = TIMESTAMP_COL_WIDTH + occur_width + STATUS_COL_WIDTH
        if client_size.width <= fixed_width:
            return
        name_width = client_size.width - fixed_width
        self.list_ctrl.SetColumnWidth(NAME_COL, name_width)
        self.list_ctrl.SetColumnWidth(TIMESTAMP_COL, TIMESTAMP_COL_WIDTH)
        self.list_ctrl.SetColumnWidth(OCCUR_COL, occur_width)
        self.list_ctrl.SetColumnWidth(STATUS_COL, STATUS_COL_WIDTH)
        self.refresh_sort_headers()

    def apply_locale(self) -> None:
        if self._host is not None:
            self.set_occur_column_visible(self._host._occur_column_visible)
        self.refresh_sort_headers()

    def list_row_for_entry(self, entry_index: int) -> int | None:
        if self._host is None:
            return None
        try:
            return self._host._visible_entry_indices.index(entry_index)
        except ValueError:
            return None

    def entry_index_at_list_row(self, list_row: int) -> int | None:
        if self._host is None:
            return None
        indices = self._host._visible_entry_indices
        if list_row < 0 or list_row >= len(indices):
            return None
        return indices[list_row]

    def list_selected_rows(self) -> list[int]:
        rows: list[int] = []
        item = self.list_ctrl.GetFirstSelected()
        while item != -1:
            rows.append(item)
            item = self.list_ctrl.GetNextSelected(item)
        return rows

    def selected_entry_indices(self) -> list[int]:
        indices: list[int] = []
        for list_row in self.list_selected_rows():
            entry_index = self.entry_index_at_list_row(list_row)
            if entry_index is not None:
                indices.append(entry_index)
        return indices

    def deselect_all_rows(self) -> None:
        for list_row in range(self.list_ctrl.GetItemCount()):
            self.list_ctrl.SetItemState(list_row, 0, wx.LIST_STATE_SELECTED)

    def select_all_visible(self) -> None:
        if self._host is None:
            return
        count = self.list_ctrl.GetItemCount()
        if count == 0:
            return
        self._host._selection_explicit_empty = False
        for list_row in range(count):
            self.list_ctrl.SetItemState(
                list_row,
                wx.LIST_STATE_SELECTED,
                wx.LIST_STATE_SELECTED,
            )

    def set_row_status_image(self, list_row: int, entry: FileEntry) -> None:
        if list_row < 0 or list_row >= self.list_ctrl.GetItemCount():
            return
        image = status_image_index(entry)
        if image < 0 or image >= self._status_images.GetImageCount():
            return
        self.list_ctrl.SetItemColumnImage(list_row, STATUS_COL, image)

    def set_selection(
        self,
        selected_entries: set[int],
        *,
        focus_entry: int | None,
        preserve_search_focus: bool,
        search_box: wx.TextCtrl,
    ) -> None:
        if self._host is None:
            return
        if self._host._selection_explicit_empty:
            selected_entries = set()
            focus_entry = None

        if preserve_search_focus and search_box.HasFocus():
            for list_row in range(self.list_ctrl.GetItemCount()):
                self.list_ctrl.SetItemState(list_row, 0, wx.LIST_STATE_SELECTED)
            for entry_index in selected_entries:
                list_row = self.list_row_for_entry(entry_index)
                if list_row is not None:
                    self.list_ctrl.SetItemState(
                        list_row,
                        wx.LIST_STATE_SELECTED,
                        wx.LIST_STATE_SELECTED,
                    )
            if focus_entry is not None:
                list_row = self.list_row_for_entry(focus_entry)
                if list_row is not None:
                    self.list_ctrl.SetItemState(
                        list_row,
                        wx.LIST_STATE_SELECTED,
                        wx.LIST_STATE_SELECTED,
                    )
                    self.list_ctrl.EnsureVisible(list_row)
            return

        for entry_index in selected_entries:
            list_row = self.list_row_for_entry(entry_index)
            if list_row is not None:
                self.list_ctrl.Select(list_row)

        if focus_entry is not None:
            list_row = self.list_row_for_entry(focus_entry)
            if list_row is not None:
                self.list_ctrl.Select(list_row)
                self.list_ctrl.EnsureVisible(list_row)

    def sync(
        self,
        *,
        restore_selection: set[int] | None = None,
        preserve_search_focus: bool = False,
        force: bool = False,
        search_box: wx.TextCtrl,
        rebuild_visible: Callable[[], None],
    ) -> None:
        if self._host is None:
            return
        if not force and not self.list_ctrl.IsShown():
            self._host._file_list_needs_sync = True
            return
        self._host._file_list_needs_sync = False
        if restore_selection is None:
            restore_selection = set(self.selected_entry_indices())
        rebuild_visible()

        self.list_ctrl.Freeze()
        self.list_ctrl.DeleteAllItems()
        for list_row, entry_index in enumerate(self._host._visible_entry_indices):
            entry = self._host.entries[entry_index]
            self.list_ctrl.InsertItem(list_row, entry_label(entry.path))
            self.list_ctrl.SetItem(
                list_row,
                TIMESTAMP_COL,
                entry_timestamp_label(entry.path),
            )
            if self._host._occur_column_visible:
                count = (
                    self._host._entry_occur_counts[entry_index]
                    if entry_index < len(self._host._entry_occur_counts)
                    else 0
                )
                if count:
                    self.list_ctrl.SetItem(list_row, OCCUR_COL, str(count))

        self.set_selection(
            restore_selection,
            focus_entry=self._host.focus_index,
            preserve_search_focus=preserve_search_focus,
            search_box=search_box,
        )

        self.list_ctrl.Thaw()
        for list_row, entry_index in enumerate(self._host._visible_entry_indices):
            self.set_row_status_image(list_row, self._host.entries[entry_index])
        self.resize_columns()

    def update_row_status(self, entry_index: int) -> None:
        if self._host is None:
            return
        if entry_index < 0 or entry_index >= len(self._host.entries):
            return
        if not self.list_ctrl.IsShown():
            self._host._file_list_needs_sync = True
            return
        if self._host._search_keywords:
            list_row = self.list_row_for_entry(entry_index)
            if list_row is not None:
                entry = self._host.entries[entry_index]
                self.set_row_status_image(list_row, entry)
                if self._host._occur_column_visible:
                    count = (
                        self._host._entry_occur_counts[entry_index]
                        if entry_index < len(self._host._entry_occur_counts)
                        else 0
                    )
                    self.list_ctrl.SetItem(
                        list_row,
                        OCCUR_COL,
                        str(count) if count else "",
                    )
            return
        list_row = self.list_row_for_entry(entry_index)
        if list_row is None:
            return
        entry = self._host.entries[entry_index]
        self.set_row_status_image(list_row, entry)

    def insert_row(
        self,
        list_row: int,
        entry: FileEntry,
        *,
        occur_count: int = 0,
    ) -> None:
        self.list_ctrl.InsertItem(list_row, entry_label(entry.path))
        self.list_ctrl.SetItem(list_row, TIMESTAMP_COL, entry_timestamp_label(entry.path))
        if self._host is not None and self._host._occur_column_visible and occur_count:
            self.list_ctrl.SetItem(list_row, OCCUR_COL, str(occur_count))
        self.set_row_status_image(list_row, entry)
        self.resize_columns()

    def update_search_counts(self, counts: list[int], *, resort: bool) -> None:
        if self._host is None:
            return
        if not self.list_ctrl.IsShown():
            self._host._file_list_needs_sync = True
            return
        if resort:
            return
        for list_row, entry_index in enumerate(self._host._visible_entry_indices):
            count = (
                counts[entry_index]
                if entry_index < len(counts)
                else 0
            )
            self.list_ctrl.SetItem(
                list_row,
                OCCUR_COL,
                str(count) if count else "",
            )

    def name_truncated(self, list_row: int) -> bool:
        label = self.list_ctrl.GetItemText(list_row, NAME_COL)
        if not label:
            return False
        col_width = self.list_ctrl.GetColumnWidth(NAME_COL)
        if col_width <= 8:
            return False
        text_width, _ = self.list_ctrl.GetTextExtent(label)
        return text_width >= col_width - 8

    def set_name_tooltip(self, text: str) -> None:
        if text:
            self.list_ctrl.SetToolTip(text)
        else:
            self.list_ctrl.UnsetToolTip()
