"""Recording entry list management."""

from __future__ import annotations

from pathlib import Path

import wx

from wav2chat.gui.entry_helpers import find_audio_for_stem, try_load_transcript_json
from wav2chat.gui.models import FileEntry
from wav2chat.i18n import t
from wav2chat.pipeline import (
    collect_supported_audio_paths,
    find_transcript_path,
    is_supported_audio,
    is_transcript_path,
)


class EntryStoreMixin:
    """Add, refresh, and remove file entries in the browser list."""

    entries: list[FileEntry]
    focus_index: int | None

    def _collect_import_paths(self, paths: list[Path]) -> list[Path]:
        return collect_supported_audio_paths(paths)

    def _refresh_entry_metadata(self, entry: FileEntry) -> bool:
        changed = False
        if entry.session_only:
            transcript = try_load_transcript_json(entry.path)
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
            transcript = try_load_transcript_json(transcript_path)
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
            transcript = try_load_transcript_json(transcript_path)
            if transcript is not None:
                entry.transcript = transcript
                entry.status = "converted"
            else:
                entry.json_invalid = True
        self.entries.append(entry)
        return len(self.entries) - 1

    def _append_json_entry(self, path: Path) -> int:
        transcript = try_load_transcript_json(path)
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

        audio = find_audio_for_stem(path.with_suffix(""))
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

        self._refresh_base_sort()
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

    def _delete_selected_entries(self) -> None:
        import logging

        if self._converting_active or self._load_in_progress:
            return
        if self._selection_explicit_empty:
            return

        selected = sorted(set(self._selected_entry_indices()))
        if not selected:
            return

        self._segment_player.stop()
        if self._chat_view is not None:
            self._chat_view.playing_segment_index = None
            self._chat_view.stop_speaker_animation()

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
