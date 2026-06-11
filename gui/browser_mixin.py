"""Async browser directory loading and transcript search."""

from __future__ import annotations

import threading
from pathlib import Path

import wx

from wav2chat.fs_browser import iter_browser_paths
from wav2chat.gui.constants import NAME_COL, OCCUR_COL, TIMESTAMP_COL
from wav2chat.gui.entry_helpers import (
    entry_keyword_occurrence_count,
    entry_label,
    entry_timestamp_sort_key,
    parse_search_keywords,
)
from wav2chat.i18n import t
from wav2chat.pipeline import is_supported_audio, is_transcript_path

class BrowserMixin:
    """Directory load, drop import, and async search for the file browser."""

    _load_generation: int
    _load_thread: threading.Thread | None
    _load_in_progress: bool
    _load_append_mode: bool
    _load_added_indices: list[int]
    _search_generation: int
    _search_thread: threading.Thread | None
    _entry_occur_counts: list[int]
    _search_keywords: list[str]
    _visible_entry_indices: list[int]
    _occur_column_visible: bool
    _list_sort_column: int
    _list_sort_ascending: bool
    _current_directory: Path | None
    entries: list

    def _max_items_limit(self) -> int:
        text = self._max_items_ctrl.GetValue().strip()
        if not text:
            return 0
        try:
            return max(0, int(text))
        except ValueError:
            return 0

    def _effective_load_limit(self, *, for_append: bool) -> int:
        limit = self._max_items_limit()
        if limit <= 0:
            return 0
        if for_append:
            return max(0, limit - len(self.entries))
        return limit

    def _cancel_async_load(self) -> None:
        self._load_generation += 1
        self._load_in_progress = False
        self._hide_load_bar()

    def _cancel_async_search(self) -> None:
        self._search_generation += 1

    def _refresh_base_sort(self) -> None:
        self._rebuild_visible_entries()

    def _entry_sort_key(self, index: int):
        entry = self.entries[index]
        if self._list_sort_column == NAME_COL:
            return entry_label(entry.path).casefold()
        if self._list_sort_column == TIMESTAMP_COL:
            return entry_timestamp_sort_key(entry.path)
        if self._list_sort_column == OCCUR_COL:
            if index < len(self._entry_occur_counts):
                return self._entry_occur_counts[index]
            return 0
        return index

    def _on_file_list_column_sort(self, column: int) -> None:
        if column == self._list_sort_column:
            self._list_sort_ascending = not self._list_sort_ascending
        else:
            self._list_sort_column = column
            self._list_sort_ascending = column != OCCUR_COL
        self._sync_file_list()

    def _load_directory_files(self, directory: Path) -> None:
        if self._converting_active:
            return
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            return

        self._cancel_async_load()
        self._cancel_async_search()

        self._current_directory = directory
        self._set_breadcrumbs(directory)
        self._persist_browser_directory(directory)
        self._search_keywords = parse_search_keywords(self._search_box.GetValue())
        if self._search_keywords:
            self._entry_occur_counts = []
            self._set_occur_column_visible(True)
            self._list_sort_column = OCCUR_COL
            self._list_sort_ascending = False
        else:
            self._entry_occur_counts = []
            self._set_occur_column_visible(False)
            self._list_sort_column = TIMESTAMP_COL
            self._list_sort_ascending = False
        self._selection_explicit_empty = True
        self.entries.clear()
        self._visible_entry_indices = []
        self._load_append_mode = False
        self._load_added_indices = []
        self.focus_index = None

        if self._file_list.IsShown():
            self._file_list.DeleteAllItems()
        else:
            self._file_list_needs_sync = True
        self._clear_session_view()
        self._start_async_directory_load(directory)

    def _start_async_directory_load(self, directory: Path) -> None:
        gen = self._load_generation
        self._load_in_progress = True
        self._show_load_bar(0.0)
        max_items = self._effective_load_limit(for_append=False)
        recursive = self._chk_recursive.GetValue()

        def worker() -> None:
            try:
                paths = iter_browser_paths(
                    directory,
                    recursive=recursive,
                    max_items=max_items,
                )
                total = len(paths)
                for index, path in enumerate(paths, start=1):
                    if gen != self._load_generation:
                        return
                    self._ui_queue.put(("load_item", (gen, path, index, total)))
                if gen == self._load_generation:
                    self._ui_queue.put(("load_done", (gen, total)))
            except Exception as exc:
                self._ui_queue.put(("load_error", (gen, str(exc))))
                if gen == self._load_generation:
                    self._ui_queue.put(("load_done", (gen, 0)))

        self._load_thread = threading.Thread(target=worker, daemon=True)
        self._load_thread.start()

    def _collect_drop_paths(self, paths: list[Path]) -> list[Path]:
        collected: list[Path] = []
        limit = self._effective_load_limit(for_append=True)
        recursive = self._chk_recursive.GetValue()
        seen: set[Path] = set()

        def add(path: Path) -> bool:
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                return True
            seen.add(resolved)
            collected.append(resolved)
            if limit > 0 and len(collected) >= limit:
                return False
            return True

        for raw in paths:
            try:
                path = raw.expanduser().resolve()
            except OSError:
                continue
            if path.is_dir():
                for child in iter_browser_paths(path, recursive=recursive, max_items=0):
                    if not add(child):
                        return collected
            elif is_supported_audio(path) or is_transcript_path(path):
                if not add(path):
                    return collected
        return collected

    def _start_async_drop_load(self, paths: list[Path]) -> None:
        if self._converting_active:
            return
        collected = self._collect_drop_paths(paths)
        if not collected:
            return

        self._cancel_async_load()
        gen = self._load_generation
        self._load_in_progress = True
        self._load_append_mode = True
        self._load_added_indices = []
        self._show_load_bar(0.0)
        total = len(collected)

        def worker() -> None:
            try:
                for index, path in enumerate(collected, start=1):
                    if gen != self._load_generation:
                        return
                    self._ui_queue.put(("load_item", (gen, path, index, total)))
                if gen == self._load_generation:
                    self._ui_queue.put(("load_done", (gen, total)))
            except Exception as exc:
                self._ui_queue.put(("load_error", (gen, str(exc))))
                if gen == self._load_generation:
                    self._ui_queue.put(("load_done", (gen, 0)))

        self._load_thread = threading.Thread(target=worker, daemon=True)
        self._load_thread.start()

    def _handle_load_item(self, gen: int, path: Path, index: int, total: int) -> None:
        if gen != self._load_generation:
            return
        limit = self._max_items_limit()
        if limit > 0 and len(self.entries) >= limit:
            return

        entry_index = self._append_entry(path)
        if entry_index is None:
            if total > 0:
                self._show_load_bar(index / total)
            return

        if self._load_append_mode:
            self._load_added_indices.append(entry_index)

        list_row = self._file_list.GetItemCount()
        self._visible_entry_indices.append(entry_index)
        entry = self.entries[entry_index]
        occur_count = (
            self._entry_occur_counts[entry_index]
            if entry_index < len(self._entry_occur_counts)
            else 0
        )
        self._recording_list.insert_row(list_row, entry, occur_count=occur_count)
        if total > 0:
            self._show_load_bar(index / total)

    def _handle_load_done(self, gen: int, total: int) -> None:
        if gen != self._load_generation:
            return
        self._load_in_progress = False
        self._show_load_bar(1.0)
        self._hide_load_bar()
        self._refresh_base_sort()
        append_mode = self._load_append_mode
        added_indices = list(self._load_added_indices)
        self._load_append_mode = False
        self._load_added_indices = []
        if append_mode and added_indices:
            self._after_paths_added(added_indices)
            if self._search_keywords:
                self._start_async_search()
            return
        if self._search_keywords:
            self._sync_file_list()
            self._start_async_search()
        elif not self._file_list.IsShown():
            self._file_list_needs_sync = True
        else:
            self._sync_file_list()

    def _start_async_search(self) -> None:
        self._cancel_async_search()
        keywords = list(self._search_keywords)
        if not keywords:
            return

        gen = self._search_generation
        entry_count = len(self.entries)
        self._entry_occur_counts = [0] * entry_count

        def worker() -> None:
            counts = [0] * entry_count
            for index, entry in enumerate(self.entries):
                if gen != self._search_generation:
                    return
                counts[index] = entry_keyword_occurrence_count(entry, keywords)
                if index % 3 == 2 or index == entry_count - 1:
                    self._ui_queue.put(
                        ("search_progress", (gen, list(counts[: index + 1]))),
                    )
            if gen == self._search_generation:
                self._ui_queue.put(("search_done", (gen, counts)))

        self._search_thread = threading.Thread(target=worker, daemon=True)
        self._search_thread.start()

    def _apply_search_counts(self, counts: list[int], *, resort: bool) -> None:
        if resort:
            if len(counts) != len(self.entries):
                padded = [0] * len(self.entries)
                for index, value in enumerate(counts):
                    if index < len(padded):
                        padded[index] = value
                counts = padded
            self._entry_occur_counts = counts
        else:
            if len(self._entry_occur_counts) != len(self.entries):
                self._entry_occur_counts = [0] * len(self.entries)
            for index, value in enumerate(counts):
                if index < len(self._entry_occur_counts):
                    self._entry_occur_counts[index] = value
        if not self._file_list.IsShown():
            self._file_list_needs_sync = True
            return
        if resort:
            selected_entries = set(self._selected_entry_indices())
            preserve_focus = self._search_box.HasFocus()
            self._sync_file_list(
                restore_selection=selected_entries,
                preserve_search_focus=preserve_focus,
            )
            return
        for list_row, entry_index in enumerate(self._visible_entry_indices):
            count = (
                self._entry_occur_counts[entry_index]
                if entry_index < len(self._entry_occur_counts)
                else 0
            )
            self._file_list.SetItem(
                list_row,
                OCCUR_COL,
                str(count) if count else "",
            )

    def _rebuild_visible_entries(self) -> None:
        query = self._search_box.GetValue()
        self._search_keywords = parse_search_keywords(query)
        self._visible_entry_indices = list(range(len(self.entries)))
        self._visible_entry_indices.sort(
            key=self._entry_sort_key,
            reverse=not self._list_sort_ascending,
        )

    def _apply_search_filter(self, *, preserve_search_focus: bool = False) -> None:
        previous_focus = self.focus_index
        selected_entries = set(self._selected_entry_indices())
        query = self._search_box.GetValue()
        self._search_keywords = parse_search_keywords(query)

        if not self._search_keywords:
            self._cancel_async_search()
            self._entry_occur_counts = []
            self._set_occur_column_visible(False)
            self._list_sort_column = TIMESTAMP_COL
            self._list_sort_ascending = False
            self._sync_file_list(
                restore_selection=selected_entries,
                preserve_search_focus=preserve_search_focus,
            )
        else:
            self._entry_occur_counts = [0] * len(self.entries)
            self._set_occur_column_visible(True)
            self._list_sort_column = OCCUR_COL
            self._list_sort_ascending = False
            self._sync_file_list(
                restore_selection=selected_entries,
                preserve_search_focus=preserve_search_focus,
            )
            self._start_async_search()

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

    def _import_dropped_paths(self, paths: list[Path]) -> None:
        import logging

        if self._converting_active:
            logging.info(t("log.import_busy"))
            self._append_log(logging.INFO, t("log.import_busy"))
            return
        wx.CallAfter(self._start_async_drop_load, list(paths))
