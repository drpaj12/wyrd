"""Read-only source viewer with Verilog highlighting."""

from __future__ import annotations

import stat
from pathlib import Path

from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import QLabel, QPlainTextEdit, QTextEdit, QVBoxLayout, QWidget

from wyrd.gui.highlighter import VerilogHighlighter

MAX_BYTES = 2_000_000
BINARY_PROBE = 8192
VERILOG_SUFFIXES = frozenset({".v", ".sv", ".vh", ".svh"})


def read_limited(path: Path) -> str:
    """Decoded text of ``path``; raise OSError or ValueError when it cannot be shown."""
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not a regular file")
    if info.st_size > MAX_BYTES:
        raise ValueError(f"file is {info.st_size} bytes, over the {MAX_BYTES} byte limit")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError(f"file is over the {MAX_BYTES} byte limit")
    if b"\0" in data[:BINARY_PROBE]:
        raise ValueError("binary file")
    return data.decode("utf-8", errors="replace")


class SourceView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.path_label = QLabel("")
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self._highlighter: VerilogHighlighter | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addWidget(self.text)

    def _set_highlight(self, path: Path) -> None:
        if self._highlighter is not None:
            self._highlighter.setDocument(None)
            self._highlighter = None
        if path.suffix.lower() in VERILOG_SUFFIXES:
            self._highlighter = VerilogHighlighter(self.text.document())

    def open_file(self, path: Path, line: int | None = None) -> bool:
        self.path_label.setText(str(path))
        self._set_highlight(Path("-"))
        try:
            content = read_limited(path)
        except (OSError, ValueError) as e:
            reason = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
            self.text.setPlainText(f"Cannot show {path}: {reason}")
            self.text.setExtraSelections([])
            return False
        self._set_highlight(path)
        self.text.setPlainText(content)
        self.text.setExtraSelections([])
        if line is not None:
            self._goto(line)
        return True

    def _goto(self, line: int) -> None:
        block = self.text.document().findBlockByNumber(max(line - 1, 0))
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.text.setTextCursor(cursor)
        self.text.centerCursor()
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format.setBackground(QColor("#fff3a0"))
        sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.text.setExtraSelections([sel])
