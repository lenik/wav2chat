"""List-mode transcript chat view."""

from __future__ import annotations

from collections.abc import Callable

import wx

from wav2chat.gui.constants import (
    BUBBLE_LEFT_RGB,
    BUBBLE_RIGHT_RGB,
    LIST_SIDE_CHROME,
    SEARCH_BUBBLE_RGB,
    SEARCH_MATCH_RGB,
    rgb_colour,
)
from wav2chat.gui.entry_helpers import entry_has_playable_audio, segment_matches_keywords
from wav2chat.gui.models import FileEntry
from wav2chat.models import Segment

from wav2chat.gui.widgets.chat_message import (
    chat_panel_width,
    create_message_ctrl,
    segment_line_text,
)
from wav2chat.gui.widgets.chat_segment import ChatSegmentContext


class ListChatView:
    """Scrollable list of timestamped transcript lines."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        context: ChatSegmentContext,
        ui_font: wx.Font,
        emoji_font: wx.Font,
        make_speaker_icon: Callable[[wx.Window], wx.StaticText],
        on_segment_click: Callable[[int], None],
        on_relayout_requested: Callable[[], None],
    ) -> None:
        self._context = context
        self._ui_font = ui_font
        self._emoji_font = emoji_font
        self._make_speaker_icon = make_speaker_icon
        self._on_segment_click = on_segment_click
        self._on_relayout_requested = on_relayout_requested
        self._last_layout_width = 0

        self._panel = wx.ScrolledWindow(parent, style=wx.VSCROLL | wx.BORDER_NONE)
        self._panel.SetScrollRate(0, 10)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self._panel.SetSizer(self._sizer)
        self._panel.Hide()
        self._panel.Bind(wx.EVT_SIZE, self._on_panel_size)

    @property
    def panel(self) -> wx.ScrolledWindow:
        return self._panel

    def update_fonts(self, ui_font: wx.Font, emoji_font: wx.Font) -> None:
        self._ui_font = ui_font
        self._emoji_font = emoji_font

    def clear(self) -> None:
        self._sizer.Clear(True)

    def message_max_width(self) -> int:
        return max(160, chat_panel_width(self._panel) - LIST_SIDE_CHROME)

    def prepare_render(self) -> int:
        if self._panel.IsShown():
            parent = self._panel.GetParent()
            if parent is not None:
                parent.Layout()
        max_width = self.message_max_width()
        self._last_layout_width = chat_panel_width(self._panel)
        self._panel.Freeze()
        return max_width

    def finish_render(self) -> None:
        self._panel.Layout()
        if self._panel.IsFrozen():
            self._panel.Thaw()

    def thaw(self) -> None:
        if self._panel.IsFrozen():
            self._panel.Thaw()

    def fit(self) -> None:
        if not self._panel.IsShown():
            return
        self._panel.Layout()
        self._panel.FitInside()

    def append_segment(
        self,
        entry: FileEntry,
        segment_index: int,
        segment: Segment,
        *,
        list_max_width: int,
        keywords: list[str],
        state: dict,
    ) -> None:
        is_me = entry.transcript.is_me_speaker(segment.speaker)  # type: ignore[union-attr]
        is_search_match = segment_matches_keywords(segment, keywords)
        if is_search_match and state.get("first_match_index") is None:
            state["first_match_index"] = segment_index
        row_colour = self._segment_display_colour(
            is_search_match=is_search_match,
            is_me_speaker=is_me,
        )
        row = wx.Panel(self._panel)
        row.SetBackgroundColour(row_colour)
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        message_ctrl, _content_size = create_message_ctrl(
            row,
            segment_line_text(entry, segment),
            list_max_width,
            row_colour,
            self._ui_font,
            fill_width=True,
        )
        row_sizer.Add(message_ctrl, 0, wx.ALL, 8)
        playable = entry_has_playable_audio(entry)
        if playable:
            speaker_icon = self._make_speaker_icon(row)
            speaker_icon.SetBackgroundColour(row_colour)
            row_sizer.Add(speaker_icon, 0, wx.ALIGN_TOP | wx.RIGHT, 6)
            self._context.speaker_icons[segment_index] = speaker_icon
        row.SetSizer(row_sizer)
        self._sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, 2)
        self._context.register_row(row, row_colour, segment_index)
        self._context.segment_scroll_targets[segment_index] = row
        self._context.bind_segment_play(
            row,
            segment_index,
            playable=playable,
            on_click=self._on_segment_click,
        )

    def _segment_display_colour(
        self,
        *,
        is_search_match: bool,
        is_me_speaker: bool,
    ) -> wx.Colour:
        if is_search_match:
            return rgb_colour(*SEARCH_MATCH_RGB)
        if is_me_speaker:
            return rgb_colour(*BUBBLE_RIGHT_RGB)
        return rgb_colour(*BUBBLE_LEFT_RGB)

    def _on_panel_size(self, event: wx.SizeEvent) -> None:
        width = event.GetSize().width
        if width <= 0:
            event.Skip()
            return
        if abs(width - self._last_layout_width) >= 16:
            self._last_layout_width = width
            self._on_relayout_requested()
        else:
            wx.CallAfter(self.fit)
        event.Skip()
