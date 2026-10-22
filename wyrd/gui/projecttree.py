"""The project tree widget: designs, recipes and archs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from wyrd.guimodel.projmodel import TreeNode


def _add(parent: QTreeWidget | QTreeWidgetItem, node: TreeNode) -> QTreeWidgetItem:
    item = QTreeWidgetItem([node.label])
    item.setData(0, Qt.ItemDataRole.UserRole, str(node.path) if node.path else None)
    item.setData(0, Qt.ItemDataRole.UserRole + 1, node.kind)
    if isinstance(parent, QTreeWidget):
        parent.addTopLevelItem(item)
    else:
        parent.addChild(item)
    for child in node.children:
        _add(item, child)
    return item


class ProjectTree(QTreeWidget):
    file_activated = Signal(Path)

    def __init__(self) -> None:
        super().__init__()
        self.setHeaderHidden(True)
        self.itemDoubleClicked.connect(self._on_double_click)

    def set_nodes(self, nodes: tuple[TreeNode, ...]) -> None:
        self.clear()
        for node in nodes:
            _add(self, node)
        self.expandAll()

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, Qt.ItemDataRole.UserRole + 1) != "file":
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            self.file_activated.emit(Path(str(path)))
