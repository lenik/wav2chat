"""Coordinator for list and bubble transcript chat views."""

from __future__ import annotations

from collections.abc import Callable

import wx

from wav2chat.audio_playback import SegmentPlayer
from wav2chat.gui.constants import RENDER_CHUNK_SIZE, SPEAKER_EMOJI_FRAMES
from wav2chat.gui.entry_helpers import entry_meta, entry_title
from wav2chat.gui.models import FileEntry

from wav2chat.gui.widgets.bubble_chat_view import BubbleChatView
from wav2chat.gui.widgets.chat_segment import ChatSegmentContext
from wav2chat.gui.widgets.list_chat_view import ListChatView


class TranscriptChatView:
    """Owns list/bubble views and coordinates chunked transcript rendering."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        get_focus_entry: Callable[[], FileEntry | None],
        get_search_keywords: Callable[[], list[str]],
        get_view_mode: Callable[[], str],
        on_segment_click: Callable[[int], None],
        on_speaker_profile: Callable[[int], None],
        on_set_primary_speaker: Callable[[int], None],
        save_entry_transcript: Callable[[FileEntry], None],
        segment_player: SegmentPlayer,
        title_label: wx.StaticText,
        meta_label: wx.StaticText,
        ui_font: wx.Font,
        ui_font_bold: wx.Font,
        emoji_font: wx.Font,
    ) -> None:
        self._get_focus_entry = get_focus_entry
        self._get_search_keywords = get_search_keywords
        self._get_view_mode = get_view_mode
        self._on_segment_click = on_segment_click
        self._on_speaker_profile = on_speaker_profile
        self._on_set_primary_speaker = on_set_primary_speaker
        self._save_entry_transcript = save_entry_transcript
        self._segment_player = segment_player
        self._title_label = title_label
        self._meta_label = meta_label
        self._ui_font = ui_font
        self._ui_font_bold = ui_font_bold
        self._emoji_font = emoji_font

        self._render_generation = 0
        self._render_in_progress = False
        self._render_state: dict | None = None
        self._speaker_emoji_frame = 0
        self._segment_context = ChatSegmentContext()

        self._relayout_timer = wx.Timer(parent)
        parent.Bind(wx.EVT_TIMER, self._on_relayout_timer, self._relayout_timer)
        self._render_chunk_timer = wx.Timer(parent)
        parent.Bind(wx.EVT_TIMER, self._on_render_chunk_timer, self._render_chunk_timer)
        self._speaker_timer = wx.Timer(parent)
        parent.Bind(wx.EVT_TIMER, self._on_speaker_timer, self._speaker_timer)

        self._list_view = ListChatView(
            parent,
            context=self._segment_context,
            ui_font=ui_font,
            emoji_font=emoji_font,
            make_speaker_icon=self._make_speaker_icon,
            on_segment_click=on_segment_click,
            on_relayout_requested=self._schedule_transcript_relayout,
        )
        self._bubble_view = BubbleChatView(
            parent,
            context=self._segment_context,
            get_focus_entry=get_focus_entry,
            ui_font=ui_font,
            make_speaker_icon=self._make_speaker_icon,
            on_segment_click=on_segment_click,
            on_speaker_profile=on_speaker_profile,
            on_set_primary_speaker=on_set_primary_speaker,
            on_relayout_requested=self._schedule_transcript_relayout,
        )

    @property
    def list_panel(self) -> wx.ScrolledWindow:
        return self._list_view.panel

    @property
    def bubble_panel(self) -> wx.ScrolledWindow:
        return self._bubble_view.panel

    @property
    def view_mode(self) -> str:
        return self._get_view_mode()

    @property
    def playing_segment_index(self) -> int | None:
        return self._segment_context.playing_segment_index

    @playing_segment_index.setter
    def playing_segment_index(self, value: int | None) -> None:
        self._segment_context.playing_segment_index = value

    def bind_view_radios(self, rb_list: wx.RadioButton, rb_bubbles: wx.RadioButton) -> None:
        def on_view_changed(_event: wx.CommandEvent) -> None:
            self.refresh_view(rb_bubbles.GetValue())
        rb_list.Bind(wx.EVT_RADIOBUTTON, on_view_changed)
        rb_bubbles.Bind(wx.EVT_RADIOBUTTON, on_view_changed)

    def refresh_view(self, show_bubbles: bool) -> None:
        self._list_view.panel.Show(not show_bubbles)
        self._bubble_view.panel.Show(show_bubbles)
        parent = self._list_view.panel.GetParent()
        if parent is not None:
            parent.Layout()
        entry = self._get_focus_entry()
        if entry and entry.transcript:
            self.render_transcript(entry)
        else:
            self.clear()
            self.fit_panels()

    def stop_on_close(self) -> None:
        self._render_chunk_timer.Stop()
        self._segment_player.stop()
        self.stop_speaker_animation()

    def update_fonts(self, ui_font: wx.Font, ui_font_bold: wx.Font, emoji_font: wx.Font) -> None:
        self._ui_font = ui_font
        self._ui_font_bold = ui_font_bold
        self._emoji_font = emoji_font
        self._list_view.update_fonts(ui_font, emoji_font)
        self._bubble_view.update_fonts(ui_font)

    def clear(self) -> None:
        self._segment_player.stop()
        self._segment_context.playing_segment_index = None
        self._segment_context.clear()
        self.stop_speaker_animation()
        self._list_view.clear()
        self._bubble_view.clear()

    def fit_panels(self) -> None:
        if self.view_mode == "list" and self._list_view.panel.IsShown():
            self._list_view.fit()
            return
        if self.view_mode == "bubbles" and self._bubble_view.panel.IsShown():
            self._bubble_view.fit()

    def render_transcript(self, entry: FileEntry, relayout: bool = False) -> None:
        transcript = entry.transcript
        if transcript is None:
            return

        self._render_chunk_timer.Stop()
        self._thaw_panels()
        self._render_generation += 1
        render_generation = self._render_generation

        self._title_label.SetLabel(entry_title(entry.path))
        self._title_label.SetFont(self._ui_font_bold)
        self._meta_label.SetLabel(entry_meta(entry.path, transcript.duration))

        playing_index = self._segment_context.playing_segment_index if relayout else None
        if not relayout:
            self._segment_player.stop()
            self._segment_context.playing_segment_index = None
            self.stop_speaker_animation()
        else:
            self.stop_speaker_animation()

        self._segment_context.clear()
        self._list_view.clear()
        self._bubble_view.clear()

        if not transcript.segments:
            self._render_in_progress = False
            self._render_state = None
            self.fit_panels()
            return

        self._render_in_progress = True
        state: dict = {
            "entry": entry,
            "render_generation": render_generation,
            "playing_index": playing_index,
            "keywords": self._get_search_keywords(),
            "next_index": 0,
            "prev_speaker": None,
            "first_match_index": None,
        }

        if self.view_mode == "list":
            state["list_max_width"] = self._list_view.prepare_render()
        else:
            max_width, chat_bg, first_line_top_pad = self._bubble_view.prepare_render()
            state["bubble_max_width"] = max_width
            state["chat_bg"] = chat_bg
            state["first_line_top_pad"] = first_line_top_pad

        self._render_state = state
        self._render_chunk_timer.Start(1, oneShot=True)

    def stop_speaker_animation(self) -> None:
        self._speaker_timer.Stop()
        self._speaker_emoji_frame = 0

    def hide_playing_speaker(self) -> None:
        for icon in self._segment_context.speaker_icons.values():
            icon.Hide()
        self.stop_speaker_animation()

    def show_playing_speaker(self, segment_index: int) -> None:
        self.hide_playing_speaker()
        icon = self._segment_context.speaker_icons.get(segment_index)
        if icon is None:
            return
        icon.SetLabel(SPEAKER_EMOJI_FRAMES[0])
        icon.Show()
        parent = icon.GetParent()
        if parent is not None:
            parent.Layout()
        self._bubble_view.panel.Layout()
        self._list_view.panel.Layout()
        if not self._speaker_timer.IsRunning():
            self._speaker_timer.Start(200)

    def _scroll_to_segment(self, segment_index: int) -> None:
        target = self._segment_context.segment_scroll_targets.get(segment_index)
        if target is None:
            return
        panel = self._list_view.panel if self.view_mode == "list" else self._bubble_view.panel
        if not panel.IsShown():
            return
        self._scroll_window_to_child(panel, target)

    def _scroll_window_to_child(
        self,
        scrolled: wx.ScrolledWindow,
        child: wx.Window,
    ) -> None:
        y = 0
        current: wx.Window | None = child
        while current is not None and current is not scrolled:
            y += current.GetPosition().y
            current = current.GetParent()

        _, unit_y = scrolled.GetScrollPixelsPerUnit()
        if unit_y <= 0:
            unit_y = 10
        _, view_y = scrolled.GetViewStart()
        scroll_y = view_y * unit_y
        client_h = scrolled.GetClientSize().height
        child_h = child.GetSize().height
        target_y = max(0, y - max(0, (client_h - child_h) // 2))
        if abs(target_y - scroll_y) > 2:
            scrolled.Scroll(-1, int(target_y / unit_y))

    def _make_speaker_icon(self, parent: wx.Window) -> wx.StaticText:
        icon = wx.StaticText(parent, label=SPEAKER_EMOJI_FRAMES[0])
        icon.SetFont(self._emoji_font)
        icon.Hide()
        return icon

    def _schedule_transcript_relayout(self) -> None:
        if not self._relayout_timer.IsRunning():
            self._relayout_timer.Start(200, oneShot=True)

    def _on_relayout_timer(self, _event: wx.TimerEvent) -> None:
        entry = self._get_focus_entry()
        if entry and entry.transcript:
            self.render_transcript(entry, relayout=True)

    def _on_speaker_timer(self, _event: wx.TimerEvent) -> None:
        if self._segment_context.playing_segment_index is None:
            self.stop_speaker_animation()
            return
        icon = self._segment_context.speaker_icons.get(self._segment_context.playing_segment_index)
        if icon is None:
            self.stop_speaker_animation()
            return
        self._speaker_emoji_frame = (self._speaker_emoji_frame + 1) % len(SPEAKER_EMOJI_FRAMES)
        icon.SetLabel(SPEAKER_EMOJI_FRAMES[self._speaker_emoji_frame])
        icon.Refresh()

    def _thaw_panels(self) -> None:
        self._list_view.thaw()
        self._bubble_view.thaw()

    def _on_render_chunk_timer(self, _event: wx.TimerEvent) -> None:
        state = self._render_state
        if state is None:
            return
        if state["render_generation"] != self._render_generation:
            self._cancel_transcript_render()
            return

        entry: FileEntry = state["entry"]
        transcript = entry.transcript
        if transcript is None:
            self._finish_transcript_render(state)
            return

        start = int(state["next_index"])
        end = min(start + RENDER_CHUNK_SIZE, len(transcript.segments))
        for segment_index in range(start, end):
            segment = transcript.segments[segment_index]
            if self.view_mode == "list":
                self._list_view.append_segment(
                    entry,
                    segment_index,
                    segment,
                    list_max_width=int(state["list_max_width"]),
                    keywords=state["keywords"],
                    state=state,
                )
            else:
                self._bubble_view.append_segment(
                    entry,
                    segment_index,
                    segment,
                    bubble_max_width=int(state["bubble_max_width"]),
                    chat_bg=state["chat_bg"],
                    first_line_top_pad=int(state["first_line_top_pad"]),
                    keywords=state["keywords"],
                    state=state,
                )

        state["next_index"] = end
        if end >= len(transcript.segments):
            self._finish_transcript_render(state)
        else:
            self._render_chunk_timer.Start(10, oneShot=True)

    def _cancel_transcript_render(self) -> None:
        self._render_state = None
        self._render_in_progress = False
        self._thaw_panels()

    def _finish_transcript_render(self, state: dict) -> None:
        if self.view_mode == "bubbles":
            self._bubble_view.finish_render()
        else:
            self._list_view.finish_render()

        render_generation = int(state["render_generation"])
        playing_index = state["playing_index"]
        keywords = state["keywords"]
        first_match_index = state["first_match_index"]
        self._render_state = None
        self.fit_panels()

        def finish_layout() -> None:
            self._render_in_progress = False
            if render_generation != self._render_generation:
                return
            if playing_index is not None:
                self._segment_context.playing_segment_index = int(playing_index)
                self.show_playing_speaker(int(playing_index))
            elif keywords and first_match_index is not None:
                self._scroll_to_segment(int(first_match_index))
            self._segment_context.update_highlights()

        wx.CallAfter(finish_layout)
