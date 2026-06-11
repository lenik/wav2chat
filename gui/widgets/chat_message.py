"""Shared message layout helpers for chat views."""

from __future__ import annotations

import wx

from wav2chat.gui.constants import BUBBLE_TEXT_WIDTH_PAD, MESSAGE_TEXT_RGB, rgb_colour
from wav2chat.gui.models import FileEntry
from wav2chat.models import Segment
from wav2chat.render import display_name, format_timestamp


def wrap_text_lines(dc: wx.ClientDC, text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for char in paragraph:
            trial = line + char
            if dc.GetTextExtent(trial)[0] > width and line:
                lines.append(line)
                line = char
            else:
                line = trial
        if line:
            lines.append(line)
    return lines or [""]


def wrapped_text_size(parent: wx.Window, text: str, width: int, ui_font: wx.Font) -> wx.Size:
    dc = wx.ClientDC(parent)
    dc.SetFont(ui_font)
    line_height = dc.GetCharHeight()
    line_count = len(wrap_text_lines(dc, text, width))
    height = max(line_height, line_count * line_height) + 4
    return wx.Size(width, height)


def measure_message_text(
    parent: wx.Window,
    text: str,
    max_width: int,
    ui_font: wx.Font,
    *,
    fill_width: bool = False,
) -> wx.Size:
    dc = wx.ClientDC(parent)
    dc.SetFont(ui_font)
    if fill_width:
        return wrapped_text_size(parent, text, max_width, ui_font)

    line_widths = [dc.GetTextExtent(line)[0] for line in text.split("\n")] or [0]
    widest_line = max(line_widths)
    single_line = "\n" not in text and (widest_line + BUBBLE_TEXT_WIDTH_PAD) <= max_width
    if single_line:
        width = max(40, widest_line + BUBBLE_TEXT_WIDTH_PAD)
        _, height = dc.GetTextExtent(text)
        height = max(height, dc.GetCharHeight())
        return wx.Size(width, height)

    return wrapped_text_size(parent, text, max_width, ui_font)


def create_message_ctrl(
    parent: wx.Window,
    text: str,
    max_width: int,
    bg: wx.Colour,
    ui_font: wx.Font,
    *,
    fill_width: bool = False,
) -> tuple[wx.TextCtrl, wx.Size]:
    content_size = measure_message_text(
        parent,
        text,
        max_width,
        ui_font,
        fill_width=fill_width,
    )
    style = (
        wx.TE_MULTILINE
        | wx.TE_READONLY
        | wx.TE_WORDWRAP
        | wx.BORDER_NONE
        | wx.TE_NO_VSCROLL
    )
    message = wx.TextCtrl(parent, value=text, style=style)
    message.SetBackgroundColour(bg)
    message.SetForegroundColour(rgb_colour(*MESSAGE_TEXT_RGB))
    message.SetFont(ui_font)
    message.SetInitialSize(content_size)
    message.SetMinSize(content_size)
    message.SetMaxSize(content_size)
    return message, content_size


def segment_line_text(entry: FileEntry, segment: Segment) -> str:
    start = format_timestamp(segment.start)
    end = format_timestamp(segment.end)
    name = display_name(entry.transcript, segment) if entry.transcript else f"spk{segment.speaker}"
    return f"[{start} - {end}] {name}: {segment.text}"


def chat_panel_width(panel: wx.ScrolledWindow) -> int:
    width = panel.GetClientSize().width
    if width > 0:
        return width
    parent = panel.GetParent()
    if parent is not None:
        parent_width = parent.GetClientSize().width
        if parent_width > 0:
            return parent_width
    return 480
