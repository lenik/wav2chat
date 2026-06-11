"""Bubble-mode transcript chat view."""

from __future__ import annotations

from collections.abc import Callable

import wx

from wav2chat.gui.constants import (
    AVATAR_COL_WIDTH,
    AVATAR_SIZE,
    BUBBLE_AVATAR_H_MARGIN,
    BUBBLE_INNER_PAD,
    BUBBLE_LEFT_RGB,
    BUBBLE_RADIUS,
    BUBBLE_RIGHT_RGB,
    BUBBLE_SIDE_CHROME,
    CHAT_BG_RGB,
    SEARCH_BUBBLE_RGB,
    SPEAKER_AVATAR_RGBS,
    rgb_colour,
)
from wav2chat.gui.entry_helpers import entry_has_playable_audio, segment_matches_keywords
from wav2chat.gui.models import FileEntry
from wav2chat.models import Segment, Speaker
from wav2chat.gui.speaker_ui import RoundedAvatarPanel

from wav2chat.gui.widgets.chat_message import chat_panel_width, create_message_ctrl
from wav2chat.gui.widgets.chat_segment import ChatSegmentContext
from wav2chat.gui.widgets.common import RoundedBubblePanel


class BubbleChatView:
    """WeChat-style bubble transcript view with avatars."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        context: ChatSegmentContext,
        get_focus_entry: Callable[[], FileEntry | None],
        ui_font: wx.Font,
        make_speaker_icon: Callable[[wx.Window], wx.StaticText],
        on_segment_click: Callable[[int], None],
        on_speaker_profile: Callable[[int], None],
        on_set_primary_speaker: Callable[[int], None],
        on_relayout_requested: Callable[[], None],
    ) -> None:
        self._context = context
        self._get_focus_entry = get_focus_entry
        self._ui_font = ui_font
        self._make_speaker_icon = make_speaker_icon
        self._on_segment_click = on_segment_click
        self._on_speaker_profile = on_speaker_profile
        self._on_set_primary_speaker = on_set_primary_speaker
        self._on_relayout_requested = on_relayout_requested
        self._last_layout_width = 0
        self._avatar_panels: dict[int, RoundedAvatarPanel] = {}

        self._panel = wx.ScrolledWindow(parent, style=wx.VSCROLL | wx.BORDER_NONE)
        self._panel.SetBackgroundColour(rgb_colour(*CHAT_BG_RGB))
        self._panel.SetScrollRate(0, 10)
        self._sizer = wx.BoxSizer(wx.VERTICAL)
        self._panel.SetSizer(self._sizer)
        self._panel.Bind(wx.EVT_SIZE, self._on_panel_size)

    @property
    def panel(self) -> wx.ScrolledWindow:
        return self._panel

    @property
    def avatar_panels(self) -> dict[int, RoundedAvatarPanel]:
        return self._avatar_panels

    def update_fonts(self, ui_font: wx.Font) -> None:
        self._ui_font = ui_font

    def clear(self) -> None:
        self._sizer.Clear(True)
        self._avatar_panels.clear()

    def message_max_width(self) -> int:
        return max(80, chat_panel_width(self._panel) - BUBBLE_SIDE_CHROME)

    def prepare_render(self) -> tuple[int, wx.Colour, int]:
        if self._panel.IsShown():
            parent = self._panel.GetParent()
            if parent is not None:
                parent.Layout()
        max_width = self.message_max_width()
        self._last_layout_width = chat_panel_width(self._panel)
        chat_bg = rgb_colour(*CHAT_BG_RGB)
        first_line_top_pad = self._first_line_top_pad()
        self._panel.Freeze()
        return max_width, chat_bg, first_line_top_pad

    def finish_render(self) -> None:
        self._sizer.AddSpacer(20)
        self._sizer.Layout()
        if self._panel.IsFrozen():
            self._panel.Thaw()

    def thaw(self) -> None:
        if self._panel.IsFrozen():
            self._panel.Thaw()

    def fit(self) -> None:
        if not self._panel.IsShown():
            return
        self._sizer.Layout()
        min_size = self._sizer.GetMinSize()
        client_width = max(min_size.width, self._panel.GetClientSize().width)
        virtual_height = min_size.height + 24
        current = self._panel.GetVirtualSize()
        if current.width != client_width or current.height != virtual_height:
            self._panel.SetVirtualSize((client_width, virtual_height))
        self._panel.Layout()
        self._panel.FitInside()

    def append_segment(
        self,
        entry: FileEntry,
        segment_index: int,
        segment: Segment,
        *,
        bubble_max_width: int,
        chat_bg: wx.Colour,
        first_line_top_pad: int,
        keywords: list[str],
        state: dict,
    ) -> None:
        transcript = entry.transcript
        assert transcript is not None
        is_me = transcript.is_me_speaker(segment.speaker)
        is_search_match = segment_matches_keywords(segment, keywords)
        if is_search_match and state.get("first_match_index") is None:
            state["first_match_index"] = segment_index
        prev_speaker: int | None = state.get("prev_speaker")
        show_avatar = segment.speaker != prev_speaker
        state["prev_speaker"] = segment.speaker

        row_panel = wx.Panel(self._panel)
        row_panel.SetBackgroundColour(chat_bg)
        row_sizer = wx.BoxSizer(wx.HORIZONTAL)
        row_gap = 6 if show_avatar else 3

        avatar_widget: wx.Panel | None = None
        if show_avatar:
            avatar_widget = self._make_avatar_widget(row_panel, segment.speaker, chat_bg)

        bubble_colour = self._segment_display_colour(
            is_search_match=is_search_match,
            is_me_speaker=is_me,
        )
        bubble = RoundedBubblePanel(row_panel, bubble_colour, BUBBLE_RADIUS)
        bubble_sizer = wx.BoxSizer(wx.VERTICAL)
        message_ctrl, _content_size = create_message_ctrl(
            bubble,
            segment.text,
            bubble_max_width,
            bubble_colour,
            self._ui_font,
            fill_width=False,
        )
        bubble_sizer.Add(message_ctrl, 0, wx.ALL, BUBBLE_INNER_PAD)
        bubble.SetSizer(bubble_sizer)

        playable = entry_has_playable_audio(entry)
        speaker_icon: wx.StaticText | None = None
        if playable:
            speaker_icon = self._make_speaker_icon(row_panel)
            self._context.speaker_icons[segment_index] = speaker_icon
            speaker_icon.SetBackgroundColour(chat_bg)

        bubble_top_flag = wx.ALIGN_TOP | wx.TOP
        bubble_top_border = first_line_top_pad if show_avatar else 0
        avatar_sizer_flags = wx.ALIGN_TOP | wx.LEFT | wx.RIGHT
        avatar_sizer_border = BUBBLE_AVATAR_H_MARGIN

        if is_me:
            row_sizer.AddStretchSpacer(1)
            if speaker_icon is not None:
                row_sizer.Add(speaker_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 2)
            row_sizer.Add(
                bubble,
                0,
                bubble_top_flag,
                bubble_top_border if show_avatar else row_gap,
            )
            if show_avatar and avatar_widget is not None:
                row_sizer.Add(avatar_widget, 0, avatar_sizer_flags, avatar_sizer_border)
            else:
                row_sizer.Add(
                    self._make_avatar_indent(row_panel, chat_bg),
                    0,
                    avatar_sizer_flags,
                    avatar_sizer_border,
                )
        else:
            if show_avatar and avatar_widget is not None:
                row_sizer.Add(avatar_widget, 0, avatar_sizer_flags, avatar_sizer_border)
            else:
                row_sizer.Add(
                    self._make_avatar_indent(row_panel, chat_bg),
                    0,
                    avatar_sizer_flags,
                    avatar_sizer_border,
                )
            row_sizer.Add(
                bubble,
                0,
                bubble_top_flag,
                bubble_top_border if show_avatar else row_gap,
            )
            if speaker_icon is not None:
                row_sizer.Add(speaker_icon, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
            row_sizer.AddStretchSpacer(1)

        row_panel.SetSizer(row_sizer)
        self._sizer.Add(row_panel, 0, wx.EXPAND | wx.TOP, row_gap)
        self._context.register_row(bubble, bubble_colour, segment_index)
        self._context.segment_scroll_targets[segment_index] = row_panel
        self._context.bind_segment_play(
            row_panel,
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
            return rgb_colour(*SEARCH_BUBBLE_RGB)
        if is_me_speaker:
            return rgb_colour(*BUBBLE_RIGHT_RGB)
        return rgb_colour(*BUBBLE_LEFT_RGB)

    def _first_line_top_pad(self) -> int:
        dc = wx.ClientDC(self._panel)
        dc.SetFont(self._ui_font)
        line_height = dc.GetCharHeight()
        return max(0, int(AVATAR_SIZE / 2 - BUBBLE_INNER_PAD - line_height / 2))

    def _make_avatar_indent(self, parent: wx.Window, chat_bg: wx.Colour) -> wx.Panel:
        indent = wx.Panel(parent, style=wx.BORDER_NONE)
        indent.SetBackgroundColour(chat_bg)
        indent.SetMinSize((AVATAR_COL_WIDTH, AVATAR_SIZE))
        return indent

    def _make_avatar_widget(
        self,
        parent: wx.Window,
        speaker_index: int,
        chat_bg: wx.Colour,
    ) -> wx.Panel:
        holder = wx.Panel(parent, style=wx.BORDER_NONE)
        holder.SetBackgroundColour(chat_bg)
        holder.SetMinSize((AVATAR_COL_WIDTH, AVATAR_SIZE))
        holder_sizer = wx.BoxSizer(wx.VERTICAL)

        def get_speaker() -> Speaker:
            entry = self._get_focus_entry()
            if entry is None or entry.transcript is None:
                return Speaker(name=f"spk{speaker_index}")
            return entry.transcript.speaker_at(speaker_index)

        def is_me() -> bool:
            entry = self._get_focus_entry()
            if entry is None or entry.transcript is None:
                return False
            return entry.transcript.is_me_speaker(speaker_index)

        avatar = RoundedAvatarPanel(
            holder,
            speaker_index=speaker_index,
            get_speaker=get_speaker,
            on_open_profile=self._on_speaker_profile,
            chat_bg=chat_bg,
            colour_palette=SPEAKER_AVATAR_RGBS,
            size=AVATAR_SIZE,
            on_set_primary=self._on_set_primary_speaker,
            is_primary_speaker=is_me,
        )
        self._avatar_panels[speaker_index] = avatar
        holder_sizer.Add(avatar, 0, wx.ALIGN_CENTER_HORIZONTAL)
        holder.SetSizer(holder_sizer)
        return holder

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
