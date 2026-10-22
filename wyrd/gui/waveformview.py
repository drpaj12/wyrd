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

from wyrd.guimodel.waveform import WaveRow, format_value, segments, visible_range

NAME_WIDTH = 160
CELL_WIDTH = 24
MIN_CELL = 8
MAX_CELL = 64
ROW_HEIGHT = 28
MARGIN = 6
MAX_WIDGET = 16_000_000
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
        self.first_sample = 0
        self.sample_count = 0
        self.cursor_index: int | None = None
        self.cell_width = CELL_WIDTH
        self.radix: Radix = "hex"
        self._resize()

    def set_rows(self, rows: list[WaveRow], first: int = 0) -> None:
        """Show rows whose values start at recording sample `first`; indexes stay absolute."""
        self.rows = list(rows)
        self.first_sample = first
        self.sample_count = first + max((len(r.values) for r in rows), default=0)
        index = self.cursor_index
        if index is not None and not first <= index < self.sample_count:
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
        shown = max(1, self.sample_count - self.first_sample)
        width = min(MAX_WIDGET, NAME_WIDTH + shown * self.cell_width + MARGIN)
        self.resize(width, max(1, len(self.rows)) * ROW_HEIGHT + MARGIN)

    def sample_at(self, x: float) -> int | None:
        index = self.first_sample + int((x - NAME_WIDTH) // self.cell_width)
        return index if x >= NAME_WIDTH and self.first_sample <= index < self.sample_count else None

    def _x_of(self, index: int) -> int:
        return NAME_WIDTH + (index - self.first_sample) * self.cell_width

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
        area = event.rect()
        painter.fillRect(area, BACKGROUND)
        metrics = QFontMetrics(self.font())
        span = visible_range(
            area.left(),
            area.right(),
            NAME_WIDTH,
            self.cell_width,
            self.first_sample,
            self.sample_count,
        )
        for index, row in enumerate(self.rows):
            self._paint_row(painter, metrics, index, row, span)
        if self.cursor_index is not None:
            x = self._x_of(self.cursor_index) + self.cell_width / 2
            painter.setPen(QPen(CURSOR, 1))
            painter.drawLine(QPointF(x, 0), QPointF(x, self.height()))
        painter.end()

    def _paint_row(
        self,
        painter: QPainter,
        metrics: QFontMetrics,
        index: int,
        row: WaveRow,
        span: tuple[int, int],
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
        lo, hi = span
        for seg in segments(row.values[lo - self.first_sample : hi - self.first_sample]):
            x0 = self._x_of(lo + seg.start)
            x1 = self._x_of(lo + seg.end)
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
