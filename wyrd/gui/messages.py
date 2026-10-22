"""The Messages pane: parsed tool warnings and errors with click-through."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wyrd.guimodel.logparse import Message, resolve_location

HEADERS = ["Severity", "Tool", "Message", "Location"]


class MessagesPane(QWidget):
    location_activated = Signal(Path, int)

    def __init__(self) -> None:
        super().__init__()
        self.filter = QComboBox()
        self.filter.addItems(["All", "Errors", "Warnings"])
        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout = QVBoxLayout(self)
        layout.addWidget(self.filter)
        layout.addWidget(self.table)
        self._messages: list[Message] = []
        self._targets: list[tuple[Path, int]] = []
        self._search: list[Path] = []
        self._design_files: list[Path] = []
        self._shown: list[int] = []
        self.filter.currentIndexChanged.connect(self._refill)
        self.table.cellDoubleClicked.connect(self._activated)

    def set_messages(
        self, messages: list[Message], search_dirs: list[Path], design_files: list[Path]
    ) -> None:
        self._messages = list(messages)
        self._search = list(search_dirs)
        self._design_files = list(design_files)
        self._targets = [resolve_location(m, self._search, self._design_files) for m in messages]
        self._refill()

    def clear(self) -> None:
        self.set_messages([], [], [])

    def count(self) -> int:
        return self.table.rowCount()

    def _wanted(self, msg: Message) -> bool:
        mode = self.filter.currentText()
        return mode == "All" or msg.severity == {"Errors": "error", "Warnings": "warning"}[mode]

    def _location_text(self, i: int) -> str:
        path, line = self._targets[i]
        return f"{path.name}:{line}"

    def _refill(self) -> None:
        self._shown = [i for i, m in enumerate(self._messages) if self._wanted(m)]
        self.table.setRowCount(len(self._shown))
        for row, i in enumerate(self._shown):
            msg = self._messages[i]
            cells = [msg.severity, msg.tool, msg.text, self._location_text(i)]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))

    def _activated(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._shown):
            path, line = self._targets[self._shown[row]]
            self.location_activated.emit(path, line)
