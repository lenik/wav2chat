"""Background-thread to UI main-thread event dispatch."""

from __future__ import annotations

import logging
import queue
from pathlib import Path

import wx

from wav2chat.i18n import t


class UiQueueMixin:
    """Process UI queue events from worker threads."""

    _ui_queue: queue.Queue
    _load_generation: int
    _search_generation: int
    _converting_active: bool
    _file_list_needs_sync: bool
    _pending_browser_directory: Path | None
    focus_index: int | None
    _import_dialog: object | None
    _import_active: bool

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
        elif kind == "load_item":
            gen, path, index, total = payload  # type: ignore[misc]
            if gen != self._load_generation:
                return False
            self._handle_load_item(int(gen), Path(path), int(index), int(total))
        elif kind == "load_done":
            gen, total = payload  # type: ignore[misc]
            self._handle_load_done(int(gen), int(total))
        elif kind == "load_error":
            gen, message = payload  # type: ignore[misc]
            if gen == self._load_generation:
                self._append_log(logging.ERROR, str(message))
        elif kind == "search_progress":
            gen, partial_counts = payload  # type: ignore[misc]
            if gen != self._search_generation:
                return False
            self._apply_search_counts(list(partial_counts), resort=False)
        elif kind == "search_done":
            gen, counts = payload  # type: ignore[misc]
            if gen != self._search_generation:
                return False
            self._apply_search_counts(list(counts), resort=True)
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
