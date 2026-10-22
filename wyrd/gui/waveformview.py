"""The built-in waveform view: draws the rows of `wyrd.guimodel.waveform`."""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from wyrd.guimodel.waveform import WaveRow, format_value, segments

NAME_WIDTH = 160
CELL_WIDTH = 24
MIN_CELL = 8
MAX_CELL = 64
ROW_HEIGHT = 28
MARGIN = 6
Radix = Literal["hex", "dec", "bin"]
RADIXES: dict[str, Radix] = {"hex": "hex", "dec": "dec", "bin": "bin"}

TRACE = QColor(30, 120, 60)
BOX = QColor(40, 90, 160)
CURSOR = QColor(200, 60, 40)
GRID = QColor(210, 210, 210)
TEXT = QColor(30, 30, 30)
BACKGROUND = QColor(255, 255, 255)


class WaveformView(QWidget):
    cursor_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[WaveRow] = []
        self.sample_count = 0
        self.cursor_index: int | None = None
        self.cell_width = CELL_WIDTH
        self.radix: Radix = "hex"
        self._resize()

    def set_rows(self, rows: list[WaveRow]) -> None:
        self.rows = list(rows)
        self.sample_count = max((len(r.values) for r in rows), default=0)
        if self.cursor_index is not None and self.cursor_index >= self.sample_count:
            self.cursor_index = None
            self.cursor_changed.emit(None)
        self._resize()
        self.update()

    def set_radix(self, radix: str) -> None:
        chosen = RADIXES.get(radix)
        if chosen is not None:
            self.radix = chosen
            self.update()

    def _resize(self) -> None:
        width = NAME_WIDTH + max(1, self.sample_count) * self.cell_width + MARGIN
        self.setFixedSize(width, max(1, len(self.rows)) * ROW_HEIGHT + MARGIN)

    def sample_at(self, x: float) -> int | None:
        index = int((x - NAME_WIDTH) // self.cell_width)
        return index if x >= NAME_WIDTH and 0 <= index < self.sample_count else None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        index = self.sample_at(event.position().x())
        self.cursor_index = index
        self.cursor_changed.emit(index)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            event.ignore()
            return
        step = 2 if event.angleDelta().y() > 0 else -2
        self.cell_width = max(MIN_CELL, min(MAX_CELL, self.cell_width + step))
        self._resize()
        self.update()
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKGROUND)
        metrics = QFontMetrics(self.font())
        for index, row in enumerate(self.rows):
            self._paint_row(painter, metrics, index, row)
        if self.cursor_index is not None:
            x = NAME_WIDTH + self.cursor_index * self.cell_width + self.cell_width / 2
            painter.setPen(QPen(CURSOR, 1))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        painter.end()

    def _paint_row(
        self, painter: QPainter, metrics: QFontMetrics, index: int, row: WaveRow
    ) -> None:
        top = index * ROW_HEIGHT
        painter.setPen(QPen(GRID, 1))
        painter.drawLine(0, top + ROW_HEIGHT, self.width(), top + ROW_HEIGHT)
        painter.setPen(QPen(TEXT, 1))
        label = metrics.elidedText(row.name, Qt.TextElideMode.ElideLeft, NAME_WIDTH - MARGIN)
        painter.drawText(
            QRectF(MARGIN, top, NAME_WIDTH - MARGIN, ROW_HEIGHT),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            label,
        )
        previous: int | None = None
        for seg in segments(row.values):
            x0 = NAME_WIDTH + seg.start * self.cell_width
            x1 = NAME_WIDTH + seg.end * self.cell_width
            if row.width == 1:
                previous = self._paint_bit(painter, top, x0, x1, seg.value, previous)
            else:
                self._paint_bus(painter, metrics, top, (x0, x1), seg.value, row.width)

    def _paint_bit(
        self, painter: QPainter, top: int, x0: int, x1: int, value: int, previous: int | None
    ) -> int:
        high = top + MARGIN
        low = top + ROW_HEIGHT - MARGIN
        painter.setPen(QPen(TRACE, 2))
        y = high if value else low
        if previous is not None:
            painter.drawLine(x0, high, x0, low)
        painter.drawLine(x0, y, x1, y)
        return value

    def _paint_bus(
        self,
        painter: QPainter,
        metrics: QFontMetrics,
        top: int,
        span: tuple[int, int],
        value: int,
        width: int,
    ) -> None:
        x0, x1 = span
        box = QRectF(x0 + 1, top + MARGIN, x1 - x0 - 2, ROW_HEIGHT - 2 * MARGIN)
        painter.setPen(QPen(BOX, 1.5))
        painter.drawRect(box)
        text = format_value(value, width, self.radix)
        if metrics.horizontalAdvance(text) + 4 <= box.width():
            painter.setPen(QPen(TEXT, 1))
            painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)
