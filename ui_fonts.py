"""Shared Unicode-capable GUI fonts for wx widgets."""

from __future__ import annotations

import wx

_UNICODE_FONT_FACES = (
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Noto Sans CJK TC",
    "Noto Sans CJK HK",
    "Noto Sans",
    "Source Han Sans SC",
    "Source Han Sans CN",
    "Source Han Sans",
    "WenQuanYi Micro Hei",
    "Droid Sans Fallback",
    "Arial Unicode MS",
    "PingFang SC",
    "Hiragino Sans GB",
    "Malgun Gothic",
    "Segoe UI",
    "Noto Color Emoji",
    "Segoe UI Emoji",
    "DejaVu Sans",
)

_installed_font_faces: set[str] | None = None


def _collect_installed_font_faces() -> set[str]:
    global _installed_font_faces
    if _installed_font_faces is not None:
        return _installed_font_faces

    faces: set[str] = set()

    def _remember(face: str, *_args: object) -> None:
        faces.add(face)

    try:
        wx.FontEnumerator(_remember)
    except Exception:
        pass

    _installed_font_faces = faces
    return faces


def pick_unicode_font(
    point_size: int | None = None,
    weight: int = wx.FONTWEIGHT_NORMAL,
) -> wx.Font:
    """Return a GUI font that covers Latin, CJK, and other UI locales."""
    default = wx.SystemSettings.GetFont(wx.SYS_DEFAULT_GUI_FONT)
    if point_size is None:
        point_size = default.GetPointSize()

    installed = _collect_installed_font_faces()
    for face in _UNICODE_FONT_FACES:
        if installed and face not in installed:
            continue
        font = wx.Font(wx.FontInfo(point_size).FaceName(face).Weight(weight))
        if font.IsOk():
            return font

    fallback = wx.Font(default)
    fallback.SetWeight(weight)
    return fallback


def apply_ui_font(
    window: wx.Window,
    font: wx.Font,
    *,
    skip: set[int] | None = None,
) -> None:
    if skip and window.GetId() in skip:
        return
    window.SetFont(font)
    for child in window.GetChildren():
        apply_ui_font(child, font, skip=skip)


def apply_dialog_fonts(
    dialog: wx.Window,
    *,
    skip: set[int] | None = None,
) -> wx.Font:
    """Apply the main UI font to a dialog and all child controls."""
    font = pick_unicode_font()
    apply_ui_font(dialog, font, skip=skip)
    return font
