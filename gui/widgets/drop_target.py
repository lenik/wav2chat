"""File drop target for the wx GUI."""

from __future__ import annotations

from pathlib import Path

import wx


class PathDropTarget(wx.FileDropTarget):
    def __init__(self, callback) -> None:
        super().__init__()
        self._callback = callback

    def OnDropFiles(self, _x: int, _y: int, filenames: list[str]) -> bool:
        paths = [Path(path) for path in filenames]
        wx.CallAfter(self._callback, paths)
        return True
