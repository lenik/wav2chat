"""Path breadcrumb navigation widget."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx

from wav2chat.fs_browser import list_subdirectories, path_breadcrumb_segments
from wav2chat.i18n import t

from wav2chat.gui.widgets.common import FlatLinkButton


class PathBreadcrumb:
    """Encapsulates breadcrumb segment buttons and sibling menu."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_navigate: Callable[[Path], None],
        get_background: Callable[[], wx.Colour],
    ) -> None:
        self._on_navigate = on_navigate
        self._get_background = get_background
        self._frame = parent
        self._panel = wx.Panel(parent, style=wx.BORDER_NONE)
        self._sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._panel.SetSizer(self._sizer)

    @property
    def panel(self) -> wx.Panel:
        return self._panel

    def set_directory(self, directory: Path) -> None:
        self._sizer.Clear(delete_windows=True)
        segments = path_breadcrumb_segments(directory)
        for index, (label, segment_path) in enumerate(segments):
            if index > 0:
                chevron = FlatLinkButton(self._panel, ">")
                chevron.SetToolTip(t("tooltip.breadcrumb_siblings"))
                chevron.BindClick(
                    lambda path=segment_path, btn=chevron: self._on_breadcrumb_siblings(
                        path,
                        btn,
                    ),
                )
                self._sizer.Add(chevron, 0, wx.ALIGN_CENTER_VERTICAL)
            button = FlatLinkButton(self._panel, label)
            button.SetToolTip(str(segment_path))
            button.BindClick(
                lambda path=segment_path: self._on_navigate(path),
            )
            self._sizer.Add(button, 0, wx.ALIGN_CENTER_VERTICAL)
        self.apply_colours()
        self._panel.Layout()

    def apply_colours(self) -> None:
        bg = self._get_background()
        self._panel.SetBackgroundColour(bg)
        for index in range(self._sizer.GetItemCount()):
            window = self._sizer.GetItem(index).GetWindow()
            if isinstance(window, FlatLinkButton):
                window._apply_colours()
            elif isinstance(window, wx.StaticText):
                window.SetBackgroundColour(bg)

    def _on_breadcrumb_siblings(
        self,
        segment_path: Path,
        anchor: wx.Window,
    ) -> None:
        parent_dir = segment_path.parent
        siblings = list_subdirectories(parent_dir)
        if not siblings:
            return

        menu = wx.Menu()
        for sibling in siblings:
            item_id = wx.NewIdRef()
            item_label = sibling.name
            if sibling == segment_path:
                item_label = f"✓ {item_label}"
            menu.Append(item_id, item_label)
            self._frame.Bind(
                wx.EVT_MENU,
                lambda event, path=sibling: self._on_navigate(path),
                id=item_id,
            )

        pos = anchor.GetScreenPosition()
        size = anchor.GetSize()
        self._panel.PopupMenu(
            menu,
            self._panel.ScreenToClient(wx.Point(pos.x, pos.y + size.height)),
        )
        menu.Destroy()
