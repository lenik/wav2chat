"""Batch audio-to-transcript conversion."""

from __future__ import annotations

import logging
import threading

import wx

from wav2chat.errors import FunASREmptyResultError, Wav2ChatError
from wav2chat.funasr_backend import FunASRBackend
from wav2chat.gui.entry_helpers import entry_label
from wav2chat.gui.models import FileEntry, GuiSettings
from wav2chat.i18n import t
from wav2chat.models import Transcript
from wav2chat.pipeline import (
    convert_file,
    default_json_path,
    is_supported_audio,
    write_transcript_outputs,
)


class ConversionMixin:
    """FunASR conversion worker and backend lifecycle."""

    settings: GuiSettings
    entries: list[FileEntry]
    _backend: FunASRBackend | None
    _convert_thread: threading.Thread | None
    _converting_active: bool
    _stop_convert: threading.Event
    _ui_queue: object

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

    def _get_backend(self) -> FunASRBackend:
        if self._backend is None:
            if self.settings.refresh_models:
                log_key = "log.refreshing_models"
            else:
                log_key = "log.loading_models_cache"
            self._ui_queue.put(("status_text", ("status.loading_models", {})))
            self._ui_queue.put(("log", (logging.INFO, t(log_key))))
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

    def _convert_target_entry_indices(self) -> list[int]:
        selected = self._selected_entry_indices()
        if selected:
            return selected
        return list(self._visible_entry_indices)

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
        self._append_log(logging.INFO, t("log.start_batch", count=len(pending)))

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

                name = entry_label(entry.path)
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
