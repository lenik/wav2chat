"""Status bitmap and image list building for the wx GUI."""

from __future__ import annotations

import wx

from wav2chat.gui.constants import (
    IMG_CONVERTED,
    IMG_CONVERTING,
    IMG_EMPTY,
    IMG_ERROR,
    IMG_SESSION_ONLY,
    IMG_UNCONVERTED,
    IMG_WARNING,
    STATUS_DOT_RGB,
    STATUS_ICON_SIZE,
)
from wav2chat.gui.models import FileEntry
from wav2chat.models import Transcript


def transcript_is_empty(transcript: Transcript | None) -> bool:
    if transcript is None:
        return False
    return not any(segment.text.strip() for segment in transcript.segments)


def create_dot_bitmap(
    colour: wx.Colour,
    size: int = STATUS_ICON_SIZE,
    *,
    outline: bool = False,
) -> wx.Bitmap:
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    image = wx.Image(size, size)
    if not image.IsOk():
        return wx.Bitmap(size, size)
    for y in range(size):
        for x in range(size):
            image.SetRGB(x, y, bg.Red(), bg.Green(), bg.Blue())
    bitmap = wx.Bitmap(image)
    dc = wx.MemoryDC(bitmap)
    dc.SetBrush(wx.Brush(colour))
    if outline:
        dc.SetPen(wx.Pen(wx.Colour(160, 160, 160)))
    else:
        dc.SetPen(wx.Pen(colour))
    radius = max(2, size // 2 - 2)
    dc.DrawCircle(size // 2, size // 2, radius)
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def create_warning_bitmap(size: int = STATUS_ICON_SIZE) -> wx.Bitmap:
    bg = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    image = wx.Image(size, size)
    if not image.IsOk():
        return wx.Bitmap(size, size)
    for y in range(size):
        for x in range(size):
            image.SetRGB(x, y, bg.Red(), bg.Green(), bg.Blue())
    bitmap = wx.Bitmap(image)
    dc = wx.MemoryDC(bitmap)
    gc = wx.GraphicsContext.Create(dc)
    if gc is not None:
        path = gc.CreatePath()
        path.MoveToPoint(size / 2, 2)
        path.AddLineToPoint(size - 2, size - 2)
        path.AddLineToPoint(2, size - 2)
        path.CloseSubpath()
        gc.SetBrush(wx.Brush(wx.Colour(255, 193, 7)))
        gc.SetPen(wx.Pen(wx.Colour(230, 140, 0)))
        gc.FillPath(path)
        font = wx.Font(max(7, size - 7), wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
        gc.SetFont(font, wx.Colour(40, 40, 40))
        gc.DrawText("!", size / 2 - 3, size / 2 - 6)
    dc.SelectObject(wx.NullBitmap)
    return bitmap


def build_status_image_list() -> wx.ImageList:
    images = wx.ImageList(STATUS_ICON_SIZE, STATUS_ICON_SIZE, True)
    mask = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
    for index in range(IMG_CONVERTING + 1):
        red, green, blue = STATUS_DOT_RGB[index]
        bitmap = create_dot_bitmap(wx.Colour(red, green, blue))
        images.Add(bitmap, mask)
    images.Add(create_warning_bitmap(), mask)
    white = STATUS_DOT_RGB[IMG_SESSION_ONLY]
    images.Add(create_dot_bitmap(wx.Colour(*white), outline=True), mask)
    return images


def status_image_index(entry: FileEntry) -> int:
    if entry.json_invalid:
        return IMG_WARNING
    if entry.session_only:
        return IMG_SESSION_ONLY
    if entry.status == "converted":
        if transcript_is_empty(entry.transcript):
            return IMG_EMPTY
        return IMG_CONVERTED
    if entry.status == "error":
        return IMG_ERROR
    if entry.status == "converting":
        return IMG_CONVERTING
    return IMG_UNCONVERTED
