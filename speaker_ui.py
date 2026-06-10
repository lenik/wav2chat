"""Speaker avatar widgets and profile editor for the wx GUI."""

from __future__ import annotations

from collections.abc import Callable

import wx

from wav2chat.dialog_utils import bind_dialog_escape_close, setup_dialog_fonts
from wav2chat.i18n import t
from wav2chat.models import (
    DEFAULT_SPEAKER_AVATARS,
    Speaker,
    default_speaker_avatar,
    speaker_index_from_name,
)

AVATAR_RADIUS = 8
AVATAR_INNER_PAD = 2
AVATAR_EMOJI_FONT_MAX = 32
EMOJI_AVATAR_CHOICES = (
    "👦",
    "👧",
    "👨",
    "👩",
    "👰",
    "👱",
    "👲",
    "👳",
    "👴",
    "👵",
    "👶",
    "👷",
    "👸",
    "👹",
    "👺",
    "👻",
    "👼",
    "👽",
    "👾",
    "👿",
    "💀",
    "💁",
    "💂",
    "💃",
    "🐌",
    "🐍",
    "🐎",
    "🐑",
    "🐒",
    "🐔",
    "🐗",
    "🐘",
    "🐙",
    "🐚",
    "🐛",
    "🐜",
    "🐝",
    "🐞",
    "🐟",
    "🐠",
    "🐡",
    "🐢",
    "🐣",
    "🐤",
    "🐥",
    "🐦",
    "🐧",
    "🐨",
    "🐩",
    "🐫",
    "🐬",
    "🐭",
    "🐮",
    "🐯",
    "🐰",
    "🐱",
    "🐲",
    "🐳",
    "🐴",
    "🐵",
    "🐶",
    "🐷",
    "🐸",
    "🐹",
    "🐺",
    "🐻",
    "🐼",
)


def _rgb_colour(red: int, green: int, blue: int) -> wx.Colour:
    return wx.Colour(red, green, blue)


def speaker_avatar_colour(speaker_name: str, palette: tuple[tuple[int, int, int], ...]) -> wx.Colour:
    index = sum(ord(char) for char in speaker_name) % len(palette)
    red, green, blue = palette[index]
    return _rgb_colour(red, green, blue)


def default_avatar_text(speaker: Speaker, *, speaker_index: int | None = None) -> str:
    if speaker.avatar.strip():
        return speaker.avatar.strip()
    if speaker_index is not None:
        return default_speaker_avatar(speaker_index)
    parsed = speaker_index_from_name(speaker.name)
    if parsed is not None:
        return default_speaker_avatar(parsed)
    role = speaker.role.strip()
    if role:
        return role[0]
    return DEFAULT_SPEAKER_AVATARS[0]


def _pick_emoji_font(point_size: int) -> wx.Font:
    faces = (
        "Noto Color Emoji",
        "Segoe UI Emoji",
        "Apple Color Emoji",
        "Twitter Color Emoji",
        "Noto Sans CJK SC",
        "DejaVu Sans",
    )
    for face in faces:
        font = wx.Font(wx.FontInfo(point_size).FaceName(face))
        if font.IsOk():
            return font
    return wx.Font(wx.FontInfo(point_size))


class EmojiPickerDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, *, current: str) -> None:
        super().__init__(parent, title=t("dialog.choose_avatar"), size=wx.Size(400, 420))
        self._selected = current.strip() or EMOJI_AVATAR_CHOICES[0]

        scroll = wx.ScrolledWindow(self, style=wx.VSCROLL)
        scroll.SetScrollRate(0, 44)
        grid = wx.GridSizer(cols=8, hgap=4, vgap=4)
        emoji_button_ids: set[int] = set()
        for emoji in EMOJI_AVATAR_CHOICES:
            button = wx.Button(scroll, label=emoji, size=wx.Size(36, 36))
            button.SetFont(_pick_emoji_font(18))
            emoji_button_ids.add(button.GetId())
            button.Bind(wx.EVT_BUTTON, lambda _e, value=emoji: self._choose(value))
            grid.Add(button, 0, wx.EXPAND)
        scroll.SetSizer(grid)
        scroll.FitInside()

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(scroll, 1, wx.EXPAND | wx.ALL, 10)
        self.SetSizer(sizer)
        setup_dialog_fonts(self, skip=emoji_button_ids)
        bind_dialog_escape_close(self, modal_cancel=True)
        self.CentreOnParent()

    def _choose(self, emoji: str) -> None:
        self._selected = emoji
        self.EndModal(wx.ID_OK)

    @property
    def selected(self) -> str:
        return self._selected


class SpeakerProfileDialog(wx.Dialog):
    def __init__(
        self,
        parent: wx.Window,
        speaker: Speaker,
        *,
        speaker_index: int | None = None,
    ) -> None:
        super().__init__(parent, title=t("dialog.speaker_profile"), size=wx.Size(380, 300))
        self._speaker_index = speaker_index
        self._speaker = Speaker(
            name=speaker.name,
            role=speaker.role,
            gender=speaker.gender,
            avatar=speaker.avatar,
        )
        if not self._speaker.avatar.strip() and speaker_index is not None:
            self._speaker.avatar = default_speaker_avatar(speaker_index)

        form = wx.BoxSizer(wx.VERTICAL)

        form.Add(self._label_row(t("label.speaker_name"), self._readonly_field(speaker.name)), 0, wx.EXPAND)
        self._role = wx.TextCtrl(self, value=speaker.role)
        form.Add(self._label_row(t("label.speaker_role"), self._role), 0, wx.EXPAND | wx.BOTTOM, 8)

        self._gender = wx.Choice(self, choices=self._gender_labels())
        self._set_gender_code(speaker.gender)
        form.Add(self._label_row(t("label.speaker_gender"), self._gender), 0, wx.EXPAND | wx.BOTTOM, 8)

        avatar_panel = wx.Panel(self)
        avatar_row = wx.BoxSizer(wx.HORIZONTAL)
        self._avatar_preview = wx.StaticText(
            avatar_panel,
            label=self._avatar_display_text(),
            size=wx.Size(48, 48),
            style=wx.ALIGN_CENTER,
        )
        self._avatar_preview.SetFont(_pick_emoji_font(28))
        self._avatar_preview.SetMinSize((48, 48))
        self._btn_pick_avatar = wx.Button(avatar_panel, label=t("button.choose_avatar"))
        self._btn_pick_avatar.Bind(wx.EVT_BUTTON, self._on_pick_avatar)
        avatar_row.Add(self._avatar_preview, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        avatar_row.Add(self._btn_pick_avatar, 0, wx.ALIGN_CENTER_VERTICAL)
        avatar_panel.SetSizer(avatar_row)
        form.Add(self._label_row(t("label.speaker_avatar"), avatar_panel), 0, wx.EXPAND)

        close_btn = wx.Button(self, wx.ID_CLOSE, label=t("button.close"))
        close_btn.Bind(wx.EVT_BUTTON, lambda _e: self.Close())

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(form, 1, wx.EXPAND | wx.ALL, 12)
        sizer.Add(close_btn, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)
        setup_dialog_fonts(self, skip={self._avatar_preview.GetId()})
        self.Bind(wx.EVT_CLOSE, self._on_close)
        bind_dialog_escape_close(self)
        self.CentreOnParent()

    def _readonly_field(self, value: str) -> wx.TextCtrl:
        return wx.TextCtrl(self, value=value, style=wx.TE_READONLY)

    def _label_row(self, label: str, control: wx.Window) -> wx.BoxSizer:
        row = wx.BoxSizer(wx.HORIZONTAL)
        label_ctrl = wx.StaticText(self, label=label, size=wx.Size(100, -1))
        row.Add(label_ctrl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        row.Add(control, 1, wx.EXPAND)
        return row

    def _avatar_display_text(self) -> str:
        return default_avatar_text(self._speaker, speaker_index=self._speaker_index)

    _GENDER_CODES = ("", "male", "female", "other")

    def _gender_labels(self) -> list[str]:
        return [
            t("gender.unspecified"),
            t("gender.male"),
            t("gender.female"),
            t("gender.other"),
        ]

    def _set_gender_code(self, code: str) -> None:
        if code in self._GENDER_CODES:
            self._gender.SetSelection(self._GENDER_CODES.index(code))
        else:
            self._gender.SetSelection(0)

    def _collect(self) -> Speaker:
        gender_index = self._gender.GetSelection()
        if gender_index < 0 or gender_index >= len(self._GENDER_CODES):
            gender_index = 0
        return Speaker(
            name=self._speaker.name,
            role=self._role.GetValue().strip(),
            gender=self._GENDER_CODES[gender_index],
            avatar=self._speaker.avatar.strip(),
        )

    def _on_pick_avatar(self, _event: wx.CommandEvent) -> None:
        current = self._speaker.avatar.strip() or self._avatar_display_text()
        dialog = EmojiPickerDialog(self, current=current)
        if dialog.ShowModal() == wx.ID_OK:
            self._speaker.avatar = dialog.selected
            self._avatar_preview.SetLabel(self._speaker.avatar)
        dialog.Destroy()

    def _on_close(self, event: wx.CloseEvent) -> None:
        self._speaker = self._collect()
        event.Skip()

    def get_speaker(self) -> Speaker:
        return self._speaker


class RoundedAvatarPanel(wx.Panel):
    """Rounded-rectangle avatar with auto-sized emoji text."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        speaker_index: int,
        get_speaker: Callable[[], Speaker],
        on_open_profile: Callable[[int], None],
        chat_bg: wx.Colour,
        colour_palette: tuple[tuple[int, int, int], ...],
        size: int,
        on_set_primary: Callable[[int], None] | None = None,
        is_primary_speaker: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._speaker_index = speaker_index
        self._get_speaker = get_speaker
        self._on_open_profile = on_open_profile
        self._on_set_primary = on_set_primary
        self._is_primary_speaker = is_primary_speaker
        self._chat_bg = chat_bg
        self._colour_palette = colour_palette
        self._size = size
        self._radius = AVATAR_RADIUS

        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        self.SetMinSize((size, size))
        self.SetMaxSize((size, size))
        self.Bind(wx.EVT_PAINT, self._on_paint)
        self.Bind(wx.EVT_SIZE, self._on_size)
        self.Bind(wx.EVT_CONTEXT_MENU, self._on_context_menu)

    def refresh_avatar(self) -> None:
        self.Refresh()

    def _on_size(self, event: wx.SizeEvent) -> None:
        self.Refresh()
        event.Skip()

    def _on_context_menu(self, _event: wx.ContextMenuEvent) -> None:
        menu = wx.Menu()
        if self._on_set_primary is not None:
            me_id = wx.NewIdRef()
            me_label = t("menu.its_me")
            if self._is_primary_speaker is not None and self._is_primary_speaker():
                me_label = f"✓ {me_label}"
            menu.Append(me_id, me_label)
            self.Bind(
                wx.EVT_MENU,
                lambda _e: self._on_set_primary(self._speaker_index),
                id=me_id,
            )
        profile_id = wx.NewIdRef()
        menu.Append(profile_id, t("menu.speaker_profile"))
        self.Bind(
            wx.EVT_MENU,
            lambda _e: self._on_open_profile(self._speaker_index),
            id=profile_id,
        )
        self.PopupMenu(menu)
        menu.Destroy()

    def _fit_emoji_font(self, dc: wx.DC, text: str, max_width: int, max_height: int) -> wx.Font:
        start = min(AVATAR_EMOJI_FONT_MAX, max_width, max_height)
        for point_size in range(start, 7, -1):
            font = _pick_emoji_font(point_size)
            dc.SetFont(font)
            width, height = dc.GetTextExtent(text)
            if width <= max_width and height <= max_height:
                return font
        font = _pick_emoji_font(8)
        dc.SetFont(font)
        return font

    def _on_paint(self, event: wx.PaintEvent) -> None:
        speaker = self._get_speaker()
        text = default_avatar_text(speaker, speaker_index=self._speaker_index)
        fill = speaker_avatar_colour(speaker.name, self._colour_palette)

        dc = wx.PaintDC(self)
        width, height = self.GetClientSize()
        if width <= 0 or height <= 0:
            return

        dc.SetBrush(wx.Brush(self._chat_bg))
        dc.SetPen(wx.Pen(self._chat_bg))
        dc.DrawRectangle(0, 0, width, height)

        gc = wx.GraphicsContext.Create(dc)
        if gc is not None:
            gc.SetBrush(wx.Brush(fill))
            gc.SetPen(wx.Pen(fill))
            gc.DrawRoundedRectangle(0, 0, width, height, self._radius)
        else:
            dc.SetBrush(wx.Brush(fill))
            dc.SetPen(wx.Pen(fill))
            dc.DrawRectangle(0, 0, width, height)

        pad = AVATAR_INNER_PAD
        text_max_w = max(1, width - pad * 2)
        text_max_h = max(1, height - pad * 2)
        fitted = self._fit_emoji_font(dc, text, text_max_w, text_max_h)
        dc.SetFont(fitted)
        dc.SetTextForeground(wx.Colour(255, 255, 255))
        text_width, text_height = dc.GetTextExtent(text)
        dc.DrawText(
            text,
            int((width - text_width) / 2),
            int((height - text_height) / 2),
        )
        event.Skip()
