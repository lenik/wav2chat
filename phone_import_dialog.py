"""Import call recordings from a connected phone."""

from __future__ import annotations

import logging
import threading

import wx

from wav2chat.app_settings import AppSettings
from wav2chat.dialog_utils import bind_dialog_escape_close, setup_dialog_fonts
from wav2chat.i18n import t
from wav2chat.phone_import import (
    PhoneDeviceInfo,
    PhoneImportPlan,
    PhoneImportResult,
    PhoneScanStatusCallback,
    discover_phone_mounts,
    plan_phone_import,
    rescan_device_recordings,
    run_phone_import,
    scan_device_recordings,
)


class PhoneImportDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        settings: AppSettings,
        *,
        on_complete=None,
        on_closed=None,
        on_status=None,
    ) -> None:
        super().__init__(
            parent,
            title=t("dialog.import_from_phone"),
            size=wx.Size(640, 420),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetMinSize(wx.Size(560, 420))
        self._settings = settings
        self._on_complete = on_complete
        self._on_closed = on_closed
        self._on_status = on_status
        self._devices: list[PhoneDeviceInfo] = []
        self._selected_device: PhoneDeviceInfo | None = None
        self._plan: PhoneImportPlan | None = None
        self._scan_thread: threading.Thread | None = None
        self._import_thread: threading.Thread | None = None
        self._import_running = False
        self._closing = False

        self._status = wx.StaticText(self, label=t("dialog.phone_scanning"))
        self._device_choice = wx.Choice(self, choices=[])
        self._device_choice.Bind(wx.EVT_CHOICE, self._on_device_changed)
        self._model_label = wx.StaticText(self, label=t("dialog.phone_model", model="—"))
        self._vendor_label = wx.StaticText(self, label=t("dialog.phone_vendor", vendor="—"))
        self._counts_label = wx.StaticText(
            self,
            label=t("dialog.phone_counts", new=0, total=0),
        )
        self._delete_row = wx.Panel(self)
        self._delete_checkbox = wx.CheckBox(
            self._delete_row,
            label=t("dialog.phone_delete_after"),
        )
        self._delete_checkbox.SetValue(settings.phone_delete_after_import)
        delete_row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        delete_row_sizer.Add(self._delete_checkbox, 0, wx.ALL, 2)
        self._delete_row.SetSizer(delete_row_sizer)
        self._delete_row.SetMinSize(wx.Size(-1, 28))
        self._progress_panel = wx.Panel(self)
        self._progress_label = wx.StaticText(self._progress_panel, label="")
        self._progress = wx.Gauge(
            self._progress_panel,
            range=100,
            size=(-1, 22),
            style=wx.GA_HORIZONTAL,
        )
        progress_sizer = wx.BoxSizer(wx.VERTICAL)
        progress_sizer.Add(self._progress_label, 0, wx.BOTTOM, 4)
        progress_sizer.Add(self._progress, 0, wx.EXPAND)
        self._progress_panel.SetSizer(progress_sizer)
        self._progress_panel.Hide()

        self._btn_rescan = wx.Button(self, label=t("button.rescan"))
        self._btn_rescan.Bind(wx.EVT_BUTTON, self._on_rescan)
        self._btn_import = wx.Button(self, label=t("button.import"))
        self._btn_import.Disable()
        self._btn_import.Bind(wx.EVT_BUTTON, self._on_import)
        close_btn = wx.Button(self, wx.ID_CLOSE, label=t("button.close"))
        close_btn.Bind(wx.EVT_BUTTON, self._on_close_button)

        form = wx.BoxSizer(wx.VERTICAL)
        form.Add(self._status, 0, wx.BOTTOM, 8)
        form.Add(self._label_row(t("label.phone_device"), self._device_choice), 0, wx.EXPAND | wx.BOTTOM, 6)
        form.Add(self._model_label, 0, wx.BOTTOM, 4)
        form.Add(self._vendor_label, 0, wx.BOTTOM, 4)
        form.Add(self._counts_label, 0, wx.BOTTOM, 8)
        form.Add(self._delete_row, 0, wx.EXPAND | wx.BOTTOM, 10)
        form.Add(self._progress_panel, 0, wx.EXPAND | wx.BOTTOM, 8)

        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(self._btn_rescan, 0, wx.RIGHT, 8)
        btn_row.AddStretchSpacer()
        btn_row.Add(self._btn_import, 0, wx.RIGHT, 8)
        btn_row.Add(close_btn, 0)

        self._statusbar_panel = wx.Panel(self, style=wx.BORDER_SUNKEN)
        self._statusbar_text = wx.StaticText(
            self._statusbar_panel,
            label=t("dialog.phone_scanning"),
        )
        statusbar_sizer = wx.BoxSizer(wx.VERTICAL)
        statusbar_sizer.Add(self._statusbar_text, 1, wx.EXPAND | wx.ALL, 6)
        self._statusbar_panel.SetSizer(statusbar_sizer)
        self._statusbar_panel.SetMinSize(wx.Size(-1, 36))

        body = wx.BoxSizer(wx.VERTICAL)
        body.Add(form, 0, wx.EXPAND)
        body.Add(btn_row, 0, wx.EXPAND | wx.TOP, 12)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(body, 1, wx.EXPAND | wx.ALL, 12)
        outer.Add(self._statusbar_panel, 0, wx.EXPAND)
        self.SetSizer(outer)

        setup_dialog_fonts(self)
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_SIZE, self._on_dialog_size)
        bind_dialog_escape_close(self)
        self.Layout()
        self.CentreOnParent()
        wx.CallAfter(self._start_scan)

    def _set_statusbar_text(self, text: str) -> None:
        self._statusbar_text.SetLabel(text)
        self._statusbar_text.Wrap(max(200, self._statusbar_panel.GetClientSize().width - 12))
        self._statusbar_panel.Layout()

    def _on_dialog_size(self, event: wx.SizeEvent) -> None:
        self._statusbar_text.Wrap(max(200, self._statusbar_panel.GetClientSize().width - 12))
        self._statusbar_panel.Layout()
        event.Skip()

    def _scan_status_callback(self, key: str, kwargs: dict[str, object]) -> None:
        wx.CallAfter(self._apply_scan_status, key, kwargs)

    def _apply_scan_status(self, key: str, kwargs: dict[str, object]) -> None:
        if self._closing:
            return
        try:
            detail = t(key, **kwargs)
        except (KeyError, TypeError):
            detail = key
        self._set_statusbar_text(detail)
        if key == "dialog.phone_status_scan_device":
            name = str(kwargs.get("name", ""))
            self._status.SetLabel(
                t("dialog.phone_scanning_device", name=name, current=1, total=1)
            )
        elif key in {
            "dialog.phone_status_scanning_mounts",
            "dialog.phone_status_mount_candidates",
            "dialog.phone_status_checking_mount",
        }:
            self._status.SetLabel(t("dialog.phone_scanning"))
        elif key == "dialog.phone_status_device_done":
            pass

    def _show_progress_panel(self, *, pulse: bool = False) -> None:
        if self._closing:
            return
        self._progress_panel.Show()
        if pulse:
            self._progress.SetRange(100)
            self._progress.Pulse()
        self._progress_panel.GetParent().Layout()

    def _hide_progress_panel(self) -> None:
        if self._closing:
            return
        self._progress_panel.Hide()
        self._progress_label.Hide()
        self._progress_panel.GetParent().Layout()

    def _label_row(self, label: str, control: wx.Window) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        label_ctrl = wx.StaticText(self, label=label, size=wx.Size(120, -1))
        row.Add(label_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND)
        return row

    def _start_scan(self) -> None:
        if self._closing or (self._scan_thread and self._scan_thread.is_alive()):
            return
        self._set_busy(True, t("dialog.phone_scanning"))
        self._apply_scan_status("dialog.phone_status_scanning_mounts", {})
        self._show_progress_panel(pulse=True)
        callback: PhoneScanStatusCallback = self._scan_status_callback
        self._scan_thread = threading.Thread(
            target=self._scan_worker,
            args=(callback,),
            daemon=True,
        )
        self._scan_thread.start()

    def _scan_worker(self, status_callback: PhoneScanStatusCallback) -> None:
        try:
            devices = discover_phone_mounts(status_callback=status_callback)
            if self._closing:
                return
            if not devices:
                wx.CallAfter(self._apply_scan_result, [])
                return

            wx.CallAfter(self._apply_mount_list, devices)
            total = len(devices)
            for index, device in enumerate(devices, start=1):
                if self._closing:
                    return
                wx.CallAfter(
                    self._set_scan_status,
                    t(
                        "dialog.phone_scanning_device",
                        name=device.display_name,
                        current=index,
                        total=total,
                    ),
                    index,
                    total,
                )
                scan_device_recordings(
                    device,
                    deep_scan=False,
                    status_callback=status_callback,
                )
            wx.CallAfter(self._apply_scan_result, devices)
        except Exception as exc:
            logging.exception("Phone scan failed")
            wx.CallAfter(self._apply_scan_status, "dialog.phone_scan_failed", {"error": exc})
            wx.CallAfter(self._apply_scan_result, [])

    def _set_scan_status(self, message: str, current: int, total: int) -> None:
        if self._closing:
            return
        self._status.SetLabel(message)
        self._progress.SetRange(max(total, 1))
        self._progress.SetValue(current)

    def _apply_mount_list(self, devices: list[PhoneDeviceInfo]) -> None:
        if self._closing:
            return
        self._devices = devices
        self._device_choice.Clear()
        labels = [device.display_name for device in devices]
        self._device_choice.AppendItems(labels)
        if labels:
            self._device_choice.SetSelection(0)
            self._selected_device = devices[0]
            self._model_label.SetLabel(t("dialog.phone_model", model=devices[0].display_name))
            self._vendor_label.SetLabel(
                t("dialog.phone_vendor", vendor=t(devices[0].vendor_label_key))
            )
        self._status.SetLabel(t("dialog.phone_found", count=len(devices)))

    def _apply_scan_result(self, devices: list[PhoneDeviceInfo]) -> None:
        if self._closing:
            return
        self._devices = devices
        self._device_choice.Clear()
        self._hide_progress_panel()
        if not devices:
            message = t("dialog.phone_not_found")
            self._status.SetLabel(message)
            self._set_statusbar_text(message)
            self._model_label.SetLabel(t("dialog.phone_model", model="—"))
            self._vendor_label.SetLabel(t("dialog.phone_vendor", vendor="—"))
            self._counts_label.SetLabel(t("dialog.phone_counts", new=0, total=0))
            self._btn_import.Disable()
            self._set_busy(False)
            return

        labels = [
            f"{device.display_name} ({len(device.recordings)})"
            for device in devices
        ]
        self._device_choice.AppendItems(labels)
        self._device_choice.SetSelection(0)
        summary = t("dialog.phone_found", count=len(devices))
        self._status.SetLabel(summary)
        self._set_statusbar_text(summary)
        self._select_device(devices[0])
        self._set_busy(False)

    def _on_device_changed(self, _event: wx.CommandEvent) -> None:
        index = self._device_choice.GetSelection()
        if 0 <= index < len(self._devices):
            self._select_device(self._devices[index])

    def _select_device(self, device: PhoneDeviceInfo) -> None:
        self._selected_device = device
        self._plan = plan_phone_import(device, self._settings.recordings_location)
        new_count = len(self._plan.to_import)
        total = self._plan.total_on_phone
        self._model_label.SetLabel(t("dialog.phone_model", model=device.display_name))
        self._vendor_label.SetLabel(t("dialog.phone_vendor", vendor=t(device.vendor_label_key)))
        self._counts_label.SetLabel(t("dialog.phone_counts", new=new_count, total=total))
        if self._import_running:
            self._btn_import.Disable()
        elif new_count > 0:
            self._btn_import.Enable()
        else:
            self._btn_import.Disable()
            if total > 0:
                message = t("dialog.phone_all_imported")
            else:
                message = t("dialog.phone_no_recordings")
            self._status.SetLabel(message)
            self._set_statusbar_text(message)

    def _on_rescan(self, _event: wx.CommandEvent) -> None:
        if self._import_running:
            return
        self._start_scan()

    def _on_import(self, _event: wx.CommandEvent) -> None:
        if self._import_running or self._plan is None or not self._plan.to_import:
            return
        self._import_running = True
        self._settings.phone_delete_after_import = self._delete_checkbox.GetValue()
        self._btn_import.Disable()
        self._btn_rescan.Disable()
        self._device_choice.Disable()
        self._delete_checkbox.Disable()
        self._progress_label.Show()
        self._progress_label.SetLabel("")
        self._progress.SetValue(0)
        self._progress.SetRange(max(len(self._plan.to_import), 1))
        self._show_progress_panel(pulse=False)
        message = t("dialog.phone_importing")
        self._status.SetLabel(message)
        self._set_statusbar_text(message)
        if self._on_status is not None:
            self._on_status(message)
        self._import_thread = threading.Thread(
            target=self._import_worker,
            args=(self._plan, self._delete_checkbox.GetValue()),
            daemon=True,
        )
        self._import_thread.start()

    def _import_worker(self, plan: PhoneImportPlan, delete_from_phone: bool) -> None:
        def progress(current: int, total: int, name: str, *, skipped: bool) -> None:
            wx.CallAfter(self._update_import_progress, current, total, name, skipped)

        try:
            result = run_phone_import(
                plan,
                delete_from_phone=delete_from_phone,
                progress_callback=progress,
            )
            wx.CallAfter(self._finish_import, result, None)
        except Exception as exc:
            wx.CallAfter(self._finish_import, None, exc)

    def _update_import_progress(
        self,
        current: int,
        total: int,
        name: str,
        skipped: bool,
    ) -> None:
        if self._closing:
            return
        self._progress.SetRange(max(total, 1))
        self._progress.SetValue(current)
        if skipped:
            detail = t("dialog.phone_import_skip", name=name)
        else:
            detail = t("dialog.phone_import_progress", current=current, total=total, name=name)
        self._progress_label.SetLabel(detail)
        self._set_statusbar_text(detail)
        if self._on_status is not None:
            self._on_status(detail)
        self._progress_panel.GetParent().Layout()

    def _finish_import(self, result: PhoneImportResult | None, error: Exception | None) -> None:
        if self._closing:
            return
        self._import_running = False
        self._hide_progress_panel()
        self._btn_rescan.Enable()
        self._device_choice.Enable()
        self._delete_checkbox.Enable()
        if error is not None:
            logging.exception("Phone import failed")
            message = t("dialog.phone_import_failed", error=error)
            self._status.SetLabel(message)
            self._set_statusbar_text(message)
            self._btn_import.Enable()
            return
        assert result is not None
        message = t(
            "dialog.phone_import_done",
            imported=result.imported,
            skipped=result.skipped,
            failed=result.failed,
        )
        self._status.SetLabel(message)
        self._set_statusbar_text(message)
        if self._on_complete is not None and (
            result.first_destination_dir is not None or result.last_destination_dir is not None
        ):
            self._on_complete(result)
        if self._selected_device is not None:
            self._start_post_import_rescan(self._selected_device)
        logging.info(
            t(
                "log.phone_import_done",
                imported=result.imported,
                skipped=result.skipped,
                failed=result.failed,
            )
        )

    def _start_post_import_rescan(self, device: PhoneDeviceInfo) -> None:
        def worker() -> None:
            try:
                rescan_device_recordings(device)
            except Exception:
                logging.exception("Post-import phone rescan failed")
            wx.CallAfter(self._apply_post_import_rescan, device)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_post_import_rescan(self, device: PhoneDeviceInfo) -> None:
        if self._closing or self._selected_device is not device:
            return
        self._select_device(device)

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        if self._closing:
            return
        if message is not None:
            self._status.SetLabel(message)
        self._btn_rescan.Enable(not busy and not self._import_running)
        self._device_choice.Enable(not busy and not self._import_running)
        if busy:
            self._btn_import.Disable()

    def _on_close_button(self, _event: wx.CommandEvent) -> None:
        self.Close()

    def _on_close(self, event: wx.CloseEvent) -> None:
        if self._import_running:
            wx.MessageBox(
                t("dialog.phone_import_busy"),
                t("dialog.import_from_phone"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            event.Veto()
            return
        if not self._closing:
            self._closing = True
            if self._on_closed is not None:
                self._on_closed()
        self.Destroy()

    def apply_locale(self) -> None:
        if self._closing:
            return
        self.SetTitle(t("dialog.import_from_phone"))
        if not self._import_running:
            if not self._devices:
                self._status.SetLabel(t("dialog.phone_not_found"))
            elif self._plan and self._plan.to_import:
                self._status.SetLabel(t("dialog.phone_found", count=len(self._devices)))
        self._delete_checkbox.SetLabel(t("dialog.phone_delete_after"))
        self._btn_rescan.SetLabel(t("button.rescan"))
        self._btn_import.SetLabel(t("button.import"))
        if self._selected_device is not None:
            self._select_device(self._selected_device)
