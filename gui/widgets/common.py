"""Shared wx widgets for the wav2chat GUI."""

from __future__ import annotations

from collections.abc import Callable

import wx

from wav2chat.gui.constants import BUBBLE_RADIUS, LOAD_BAR_HEIGHT, MENU_BITMAP_SIZE


def menu_stock_bitmap(art_id: str) -> wx.Bitmap:
    return wx.ArtProvider.GetBitmap(
        art_id,
        wx.ART_MENU,
        wx.Size(MENU_BITMAP_SIZE, MENU_BITMAP_SIZE),
    )


def play_stock_bitmap(size: int = 16) -> wx.Bitmap:
    """Toolbar/button play icon; gtk-media-play on GTK, GO_FORWARD elsewhere."""
    px = wx.Size(size, size)
    play = wx.ArtProvider.GetBitmap("gtk-media-play", wx.ART_BUTTON, px)
    if play.IsOk():
        return play
    return wx.ArtProvider.GetBitmap(wx.ART_GO_FORWARD, wx.ART_BUTTON, px)


def append_menu_item(
    menu: wx.Menu,
    item_id: int,
    label: str,
    *,
    art_id: str | None = None,
    kind: int = wx.ITEM_NORMAL,
) -> wx.MenuItem:
    item = wx.MenuItem(menu, item_id, label, kind=kind)
    if art_id is not None and kind == wx.ITEM_NORMAL:
        bitmap = menu_stock_bitmap(art_id)
        if bitmap.IsOk():
            item.SetBitmap(bitmap)
    menu.Append(item)
    return item


class FlatLinkButton(wx.Panel):
    """Flat breadcrumb segment with hover border."""

    def __init__(self, parent: wx.Window, label: str) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._hover = False
        self._active = False
        self._enabled = True
        self._border = wx.SystemSettings.GetColour(wx.SYS_COLOUR_BTNSHADOW)
        self._label = wx.StaticText(self, label=label)
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(self._label, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
        self.SetSizer(sizer)
        self.SetToolTip(label)
        self._apply_colours()
        self._click_handler: Callable[[], None] | None = None
        self.Bind(wx.EVT_PAINT, self._on_paint)
        for target in (self, self._label):
            target.Bind(wx.EVT_ENTER_WINDOW, self._on_enter)
            target.Bind(wx.EVT_LEAVE_WINDOW, self._on_leave)
            target.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
            target.Bind(wx.EVT_LEFT_UP, self._on_left_up)

    def SetLabel(self, label: str) -> None:
        self._label.SetLabel(label)
        self.SetToolTip(label)

    def GetLabel(self) -> str:
        return self._label.GetLabel()

    def BindClick(self, handler: Callable[[], None]) -> None:
        self._click_handler = handler

    def SetActive(self, active: bool) -> None:
        self._active = active
        self.Refresh()

    def Enable(self, enable: bool = True) -> None:
        self._enabled = enable
        colour = wx.SystemSettings.GetColour(
            wx.SYS_COLOUR_GRAYTEXT if not enable else wx.SYS_COLOUR_WINDOWTEXT
        )
        self._label.SetForegroundColour(colour)
        if not enable:
            self._hover = False
        self._apply_colours()
        self.Refresh()
        super().Enable(enable)

    def _apply_colours(self) -> None:
        bg = self.GetParent().GetBackgroundColour()
        self.SetBackgroundColour(bg)
        self._label.SetBackgroundColour(bg)

    def _on_paint(self, event: wx.PaintEvent) -> None:
        if not self._enabled or not (self._hover or self._active):
            event.Skip()
            return
        dc = wx.PaintDC(self)
        width, height = self.GetSize()
        dc.SetPen(wx.Pen(self._border, 1))
        dc.SetBrush(wx.TRANSPARENT_BRUSH)
        dc.DrawRectangle(0, 0, width - 1, height - 1)
        event.Skip()

    def _on_enter(self, _event: wx.Event) -> None:
        if not self._enabled:
            return
        self._hover = True
        self.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        self.Refresh()

    def _on_leave(self, _event: wx.Event) -> None:
        self._hover = False
        self.SetCursor(wx.NullCursor)
        self.Refresh()

    def _on_left_down(self, event: wx.MouseEvent) -> None:
        event.Skip()

    def _on_left_up(self, event: wx.MouseEvent) -> None:
        handler = self._click_handler
        if not self._enabled or handler is None:
            event.Skip()
            return
        source = event.GetEventObject()
        if not isinstance(source, wx.Window):
            event.Skip()
            return
        pos = self.ScreenToClient(source.ClientToScreen(event.GetPosition()))
        clicked = self.GetClientRect().Contains(pos)
        event.Skip()
        if clicked:
            wx.CallAfter(handler)


class IntSpinRow(wx.Panel):
    """Compact integer field; Up/Down keys adjust the value (no spin buttons)."""

    def __init__(
        self,
        parent: wx.Window,
        value: int,
        *,
        min_value: int = 1,
        max_value: int = 99,
    ) -> None:
        super().__init__(parent)
        self._min_value = min_value
        self._max_value = max_value
        self._value = self._clamp(value)
        self._change_handler: Callable[[], None] | None = None
        self._text = wx.TextCtrl(
            self,
            value=str(self._value),
            style=wx.TE_CENTRE | wx.TE_PROCESS_ENTER,
            size=wx.Size(44, -1),
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(self._text, 0, wx.ALIGN_CENTER_VERTICAL)
        self.SetSizer(row)
        self._text.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self._text.Bind(wx.EVT_KILL_FOCUS, self._on_text_done)
        self._text.Bind(wx.EVT_TEXT_ENTER, self._on_text_done)

    def BindValueChanged(self, handler: Callable[[], None]) -> None:
        self._change_handler = handler

    def _clamp(self, value: int) -> int:
        return max(self._min_value, min(self._max_value, value))

    def GetValue(self) -> int:
        return self._value

    def SetValue(self, value: int) -> None:
        self._value = self._clamp(value)
        self._text.SetValue(str(self._value))

    def _notify_change(self) -> None:
        if self._change_handler is not None:
            self._change_handler()

    def _on_key_down(self, event: wx.KeyEvent) -> None:
        key = event.GetKeyCode()
        if key == wx.WXK_UP:
            self.SetValue(self._value + 1)
            self._notify_change()
            return
        if key == wx.WXK_DOWN:
            self.SetValue(self._value - 1)
            self._notify_change()
            return
        event.Skip()

    def _on_text_done(self, event: wx.Event) -> None:
        try:
            value = int(self._text.GetValue().strip())
        except ValueError:
            value = self._value
        previous = self._value
        self.SetValue(value)
        if self._value != previous:
            self._notify_change()
        event.Skip()

    def Disable(self) -> bool:
        self._text.Disable()
        return super().Disable()

    def Enable(self, enable: bool = True) -> bool:
        self._text.Enable(enable)
        return super().Enable(enable)


class FileListLoadBar(wx.Panel):
    """Thin gray/black progress strip at the top of the file list."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, size=(-1, LOAD_BAR_HEIGHT))
        self._fraction = 0.0
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, lambda _event: self.Refresh())

    def set_fraction(self, fraction: float) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(wx.Colour(200, 200, 200)))
        dc.DrawRectangle(0, 0, width, height)
        fill_width = max(1, int(width * self._fraction)) if self._fraction > 0 else 0
        if fill_width > 0:
            dc.SetBrush(wx.Brush(wx.Colour(0, 0, 0)))
            dc.DrawRectangle(0, 0, fill_width, height)
        event.Skip()


class RoundedBubblePanel(wx.Panel):
    """Chat bubble with rounded corners drawn in OnPaint."""

    def __init__(self, parent: wx.Window, colour: wx.Colour, radius: int = BUBBLE_RADIUS) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._bg_colour = colour
        self._radius = radius
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.Bind(wx.EVT_PAINT, self._on_paint)

    def set_colour(self, colour: wx.Colour) -> None:
        self._bg_colour = colour
        self.Refresh()

    def _on_paint(self, event: wx.PaintEvent) -> None:
        dc = wx.PaintDC(self)
        gc = wx.GraphicsContext.Create(dc)
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return
        if gc is None:
            dc.SetBrush(wx.Brush(self._bg_colour))
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.DrawRectangle(0, 0, width, height)
            return
        gc.SetBrush(wx.Brush(self._bg_colour))
        gc.SetPen(wx.Pen(self._bg_colour))
        gc.DrawRoundedRectangle(0, 0, width, height, self._radius)
        event.Skip()
