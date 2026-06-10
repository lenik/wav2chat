"""Shared wx dialog helpers."""

from __future__ import annotations

import wx

from wav2chat.ui_fonts import apply_dialog_fonts


def bind_dialog_escape_close(
    dialog: wx.Dialog,
    *,
    modal_cancel: bool = False,
) -> None:
    """Close the dialog when ESC is pressed."""

    def on_char_hook(event: wx.KeyEvent) -> None:
        if event.GetKeyCode() != wx.WXK_ESCAPE:
            event.Skip()
            return
        if modal_cancel:
            dialog.EndModal(wx.ID_CANCEL)
        else:
            dialog.Close()

    dialog.Bind(wx.EVT_CHAR_HOOK, on_char_hook)


def setup_dialog_fonts(
    dialog: wx.Window,
    *,
    skip: set[int] | None = None,
) -> wx.Font:
    """Apply the application UI font to a dialog."""
    return apply_dialog_fonts(dialog, skip=skip)
