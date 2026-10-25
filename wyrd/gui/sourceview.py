"""Read-only source viewer with Verilog highlighting."""

from __future__ import annotations

import stat
from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QResizeEvent, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

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


HEAT_WIDTH = 44


def heat_color(share: float) -> QColor:
    """White to red; a share of 0.5 or more is full strength."""
    strength = min(max(share, 0.0) / 0.5, 1.0)
    return QColor.fromHsvF(0.0, 0.15 + 0.85 * strength, 1.0)


class _HeatMargin(QWidget):
    def __init__(self, editor: HeatTextEdit) -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.heat_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self._editor.paint_heat(event)


class HeatTextEdit(QPlainTextEdit):
    """A read-only text view with a margin that shows a share per line (1-based line numbers)."""

    def __init__(self) -> None:
        super().__init__()
        self.heat: dict[int, float] = {}
        self._margin = _HeatMargin(self)
        self.updateRequest.connect(self._scroll_margin)
        self.setViewportMargins(0, 0, 0, 0)

    def heat_width(self) -> int:
        return HEAT_WIDTH if self.heat else 0

    def set_heat(self, heat: dict[int, float]) -> None:
        self.heat = dict(heat)
        self.setViewportMargins(self.heat_width(), 0, 0, 0)
        self._place_margin()
        self._margin.setVisible(bool(self.heat))
        self._margin.update()

    def _place_margin(self) -> None:
        box = self.contentsRect()
        self._margin.setGeometry(QRect(box.left(), box.top(), self.heat_width(), box.height()))

    def _scroll_margin(self, _rect: QRect, dy: int) -> None:
        self._margin.update()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_margin()

    def paint_heat(self, event: QPaintEvent) -> None:
        painter = QPainter(self._margin)
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            share = self.heat.get(block.blockNumber() + 1)
            if share is not None and block.isVisible():
                painter.fillRect(0, top, self.heat_width(), height, heat_color(share))
                painter.setPen(Qt.GlobalColor.black)
                cell = QRect(0, top, self.heat_width() - 3, height)
                painter.drawText(cell, Qt.AlignmentFlag.AlignRight, f"{share * 100:.0f}%")
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        painter.end()


class SourceView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.path_label = QLabel("")
        self.path: Path | None = None
        self.text = HeatTextEdit()
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

    def set_heat(self, heat: dict[int, float]) -> None:
        """Show a share per line (1-based) in a margin; an empty dict hides the margin."""
        self.text.set_heat(heat)

    def open_file(self, path: Path, line: int | None = None) -> bool:
        self.path_label.setText(str(path))
        self._set_highlight(Path("-"))
        try:
            content = read_limited(path)
        except (OSError, ValueError) as e:
            reason = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
            self.path = None
            self.text.set_heat({})
            self.text.setPlainText(f"Cannot show {path}: {reason}")
            self.text.setExtraSelections([])
            return False
        self.path = path
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
