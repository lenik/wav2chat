"""Directory tree browser widget."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx

from wav2chat.fs_browser import TREE_DUMMY_LABEL, list_subdirectories


class DirTree:
    """Encapsulates directory tree navigation."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        on_directory_selected: Callable[[Path], None],
    ) -> None:
        self._on_directory_selected = on_directory_selected
        self._tree_selecting = False
        self._root_item: wx.TreeItemId | None = None
        self._needs_init = False
        self._pending_directory: Path | None = None

        self._panel = wx.Panel(parent)
        self._recursive = wx.CheckBox(self._panel, label="")
        self._tree = wx.TreeCtrl(
            self._panel,
            style=wx.TR_DEFAULT_STYLE | wx.TR_LINES_AT_ROOT | wx.BORDER_SUNKEN,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._recursive, 0, wx.ALL, 4)
        sizer.Add(self._tree, 1, wx.EXPAND)
        self._panel.SetSizer(sizer)

        self._tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_sel_changed)
        self._tree.Bind(wx.EVT_TREE_ITEM_EXPANDING, self._on_expanding)

    @property
    def panel(self) -> wx.Panel:
        return self._panel

    @property
    def tree(self) -> wx.TreeCtrl:
        return self._tree

    @property
    def recursive_checkbox(self) -> wx.CheckBox:
        return self._recursive

    def recursive(self) -> bool:
        return self._recursive.GetValue()

    def set_recursive_label(self, label: str) -> None:
        self._recursive.SetLabel(label)

    def mark_needs_init(self) -> None:
        self._needs_init = True

    def defer_directory(self, directory: Path) -> None:
        self._pending_directory = directory

    def init(self) -> None:
        self._needs_init = False
        self._tree.DeleteAllItems()
        root_path = Path("/")
        root = self._tree.AddRoot("/")
        self._tree.SetItemData(root, root_path)
        self._root_item = root
        if list_subdirectories(root_path):
            placeholder = self._tree.AppendItem(root, TREE_DUMMY_LABEL)
            self._tree.SetItemData(placeholder, None)

    def flush_if_needed(self, *, ui_active: bool) -> None:
        if not ui_active:
            return
        if self._needs_init or self._root_item is None or not self._root_item.IsOk():
            self.init()
        pending = self._pending_directory
        if pending is not None:
            self._pending_directory = None
            self.select_directory(pending)

    def focus_selected(self, directory: Path | None = None) -> None:
        item = self._tree.GetSelection()
        if not item.IsOk() and directory is not None:
            self.select_directory(directory, ui_active=True)
            item = self._tree.GetSelection()
        if not item.IsOk():
            return
        self._tree.EnsureVisible(item)
        self._tree.SetFocus()

    def select_directory(self, directory: Path, *, ui_active: bool = True) -> None:
        try:
            directory = directory.expanduser().resolve()
        except OSError:
            return
        if not directory.is_dir():
            directory = directory.parent
        if not ui_active:
            self._pending_directory = directory
            return
        item = self.ensure_item(directory)
        if item is None or not item.IsOk():
            return
        self._tree_selecting = True
        try:
            self._tree.SelectItem(item)
            self._tree.EnsureVisible(item)
        finally:
            wx.CallAfter(self._release_selecting)

    def ensure_item(self, directory: Path) -> wx.TreeItemId | None:
        try:
            directory = directory.resolve()
        except OSError:
            return None
        if self._root_item is None or not self._root_item.IsOk():
            self.init()
        item = self._tree.GetRootItem()
        if not item.IsOk():
            return None
        root_data = self._tree.GetItemData(item)
        if isinstance(root_data, Path):
            current = root_data
        else:
            current = Path("/")

        try:
            rel_parts = directory.relative_to(current).parts
        except ValueError:
            current = Path(directory.anchor)
            item = self._tree.GetRootItem()
            try:
                rel_parts = directory.relative_to(current).parts
            except ValueError:
                return item if item.IsOk() else None

        for part in rel_parts:
            current = current / part
            child = self._find_child(item, current)
            if child is None:
                parent_data = self._tree.GetItemData(item)
                if isinstance(parent_data, Path):
                    self._populate_children(item, parent_data)
                child = self._find_child(item, current)
                if child is None:
                    child = self._append_dir_node(item, current)
            item = child
            self._tree.Expand(item)
        return item

    def _append_dir_node(self, parent: wx.TreeItemId, path: Path) -> wx.TreeItemId:
        label = path.name or str(path)
        item = self._tree.AppendItem(parent, label)
        self._tree.SetItemData(item, path)
        if list_subdirectories(path):
            placeholder = self._tree.AppendItem(item, TREE_DUMMY_LABEL)
            self._tree.SetItemData(placeholder, None)
        return item

    def _find_child(self, parent: wx.TreeItemId, path: Path) -> wx.TreeItemId | None:
        try:
            target = path.resolve()
        except OSError:
            target = path
        child, cookie = self._tree.GetFirstChild(parent)
        while child.IsOk():
            data = self._tree.GetItemData(child)
            if isinstance(data, Path):
                try:
                    if data.resolve() == target:
                        return child
                except OSError:
                    if data == path:
                        return child
            child, cookie = self._tree.GetNextChild(parent, cookie)
        return None

    def _populate_children(self, item: wx.TreeItemId, path: Path) -> None:
        if not self._tree.ItemHasChildren(item):
            return
        first, _cookie = self._tree.GetFirstChild(item)
        if first.IsOk() and self._tree.GetItemText(first) == TREE_DUMMY_LABEL:
            self._tree.DeleteChildren(item)
            for child_path in list_subdirectories(path):
                self._append_dir_node(item, child_path)

    def _on_expanding(self, event: wx.TreeEvent) -> None:
        item = event.GetItem()
        data = self._tree.GetItemData(item)
        if isinstance(data, Path):
            self._populate_children(item, data)
        event.Skip()

    def _on_sel_changed(self, event: wx.TreeEvent) -> None:
        if self._tree_selecting:
            event.Skip()
            return
        item = event.GetItem()
        data = self._tree.GetItemData(item)
        if isinstance(data, Path) and data.is_dir():
            self._on_directory_selected(data)
        event.Skip()

    def _release_selecting(self) -> None:
        self._tree_selecting = False
