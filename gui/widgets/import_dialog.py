"""Import progress dialog for the wx GUI."""

from __future__ import annotations

import wx

from wav2chat.gui.dialog_utils import bind_dialog_escape_close, setup_dialog_fonts
from wav2chat.i18n import t


class ImportDialog(wx.Dialog):
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
