"""Backward-compatible re-export; use transcript_chat_view.py."""

from wav2chat.gui.widgets.bubble_chat_view import BubbleChatView
from wav2chat.gui.widgets.list_chat_view import ListChatView
from wav2chat.gui.widgets.transcript_chat_view import TranscriptChatView

__all__ = ["BubbleChatView", "ListChatView", "TranscriptChatView"]
