"""Application settings dialog."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import wx

from wav2chat.app_settings import AppSettings, default_recordings_location
from wav2chat.gui.dialog_utils import bind_dialog_escape_close, setup_dialog_fonts
from wav2chat.i18n import t


class SettingsDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, settings: AppSettings) -> None:
        super().__init__(
            parent,
            title=t("dialog.settings"),
            size=wx.Size(640, 320),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.SetMinSize(wx.Size(520, 280))
        self._settings = settings
        self._default_path = default_recordings_location()
        self._result = settings

        form = wx.BoxSizer(wx.VERTICAL)
        form.Add(
            wx.StaticText(self, label=t("label.recordings_location")),
            0,
            wx.BOTTOM,
            8,
        )

        self._use_default = wx.CheckBox(self, label=t("label.use_default_recordings"))
        self._use_default.SetValue(settings.use_default_recordings_location)
        self._use_default.Bind(wx.EVT_CHECKBOX, self._on_use_default_changed)
        form.Add(self._use_default, 0, wx.BOTTOM, 4)

        self._default_path_label = wx.StaticText(self, label=str(self._default_path))
        form.Add(self._default_path_label, 0, wx.LEFT, 20)
        form.AddSpacer(6)

        self._or_label = wx.StaticText(self, label=t("label.or_specified_recordings"))
        form.Add(self._or_label, 0, wx.BOTTOM, 4)

        specified_row = wx.BoxSizer(wx.HORIZONTAL)
        initial_custom = settings.custom_recordings_location or self._default_path
        self._recordings_path = wx.TextCtrl(self, value=str(initial_custom))
        self._browse_btn = wx.Button(self, label=t("button.browse"))
        self._browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_recordings)
        specified_row.Add(self._recordings_path, 1, wx.EXPAND | wx.RIGHT, 8)
        specified_row.Add(self._browse_btn, 0)
        form.Add(specified_row, 0, wx.EXPAND)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(self, wx.ID_OK, label=t("button.ok"))
        cancel_btn = wx.Button(self, wx.ID_CANCEL, label=t("button.cancel"))
        btn_sizer.AddStretchSpacer()
        btn_sizer.Add(ok_btn, 0, wx.RIGHT, 8)
        btn_sizer.Add(cancel_btn, 0)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(form, 1, wx.EXPAND | wx.ALL, 12)
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)
        setup_dialog_fonts(self)
        self.Bind(wx.EVT_BUTTON, self._on_ok, ok_btn)
        self._sync_recordings_controls()
        bind_dialog_escape_close(self, modal_cancel=True)
        self.CentreOnParent()

    def _sync_recordings_controls(self) -> None:
        use_default = self._use_default.GetValue()
        self._or_label.Enable(not use_default)
        self._recordings_path.Enable(not use_default)
        self._browse_btn.Enable(not use_default)
        gray = wx.SystemSettings.GetColour(wx.SYS_COLOUR_GRAYTEXT)
        normal = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        self._default_path_label.SetForegroundColour(gray)
        self._recordings_path.SetForegroundColour(gray if use_default else normal)

    def _on_use_default_changed(self, _event: wx.CommandEvent) -> None:
        self._sync_recordings_controls()

    def _on_browse_recordings(self, _event: wx.CommandEvent) -> None:
        current = self._recordings_path.GetValue().strip() or str(self._default_path)
        dialog = wx.DirDialog(
            self,
            message=t("dialog.choose_recordings_location"),
            defaultPath=current,
            style=wx.DD_DEFAULT_STYLE,
        )
        if dialog.ShowModal() != wx.ID_OK:
            dialog.Destroy()
            return
        selected = dialog.GetPath()
        dialog.Destroy()
        self._recordings_path.SetValue(selected)

    def _on_ok(self, _event: wx.CommandEvent) -> None:
        use_default = self._use_default.GetValue()
        custom: Path | None = self._settings.custom_recordings_location
        if not use_default:
            raw = self._recordings_path.GetValue().strip()
            if not raw:
                wx.MessageBox(
                    t("dialog.recordings_location_required"),
                    t("dialog.settings"),
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
                return
            custom = Path(raw).expanduser()

        self._result = replace(
            self._settings,
            use_default_recordings_location=use_default,
            custom_recordings_location=custom,
        )
        self.EndModal(wx.ID_OK)

    @property
    def result(self) -> AppSettings:
        return self._result
