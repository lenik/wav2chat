"""Shared segment row state and interaction for chat views."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import wx

from wav2chat.gui.constants import PLAYING_SEGMENT_RGB, rgb_colour
from wav2chat.gui.widgets.common import RoundedBubblePanel


@dataclass
class ChatSegmentContext:
    segment_rows: list[tuple[wx.Panel, wx.Colour, int]] = field(default_factory=list)
    speaker_icons: dict[int, wx.StaticText] = field(default_factory=dict)
    segment_scroll_targets: dict[int, wx.Window] = field(default_factory=dict)
    playing_segment_index: int | None = None

    def clear(self) -> None:
        self.segment_rows.clear()
        self.speaker_icons.clear()
        self.segment_scroll_targets.clear()

    def register_row(self, panel: wx.Panel, base_colour: wx.Colour, segment_index: int) -> None:
        self.segment_rows.append((panel, base_colour, segment_index))

    def update_highlights(self) -> None:
        for panel, base_colour, segment_index in self.segment_rows:
            colour = (
                rgb_colour(*PLAYING_SEGMENT_RGB)
                if segment_index == self.playing_segment_index
                else base_colour
            )
            if isinstance(panel, RoundedBubblePanel):
                panel.set_colour(colour)
            else:
                panel.SetBackgroundColour(colour)
            for child in panel.GetChildren():
                if isinstance(child, (wx.StaticText, wx.TextCtrl)):
                    child.SetBackgroundColour(colour)
            panel.Refresh()

    def bind_segment_play(
        self,
        window: wx.Window,
        segment_index: int,
        *,
        playable: bool,
        on_click: Callable[[int], None],
    ) -> None:
        if not playable:
            return

        def handler(event: wx.MouseEvent) -> None:
            on_click(segment_index)

        window.Bind(wx.EVT_LEFT_DOWN, handler)
        window.SetCursor(wx.Cursor(wx.CURSOR_HAND))
        for child in window.GetChildren():
            self.bind_segment_play(child, segment_index, playable=playable, on_click=on_click)
