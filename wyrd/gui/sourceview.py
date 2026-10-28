"""Read-only source viewer with Verilog highlighting."""

from __future__ import annotations

import stat
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QHelpEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from wyrd.gui.highlighter import VerilogHighlighter
from wyrd.guimodel import heatview
from wyrd.guimodel.heatview import FileHeat, HeatRange

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


LINE_TINT_ALPHA = 55
STRIP_HEIGHT = 4


def _qcolor(crit: float, alpha: int = 255) -> QColor:
    r, g, b = heatview.crit_rgb(crit)
    return QColor(r, g, b, alpha)


def _token_format(crit: float, unknown: bool) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setBackground(_qcolor(crit))
    dark = heatview.text_is_dark(heatview.crit_rgb(crit))
    fmt.setForeground(QColor("#000000") if dark else QColor("#ffffff"))
    if unknown:
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
        fmt.setUnderlineColor(QColor("#000000"))
    return fmt


class HeatLegend(QWidget):
    """The blue to red scale with crit ticks, the theta line and the column note."""

    def __init__(self) -> None:
        super().__init__()
        self.theta: float | None = None
        self.setMinimumHeight(34)

    def set_theta(self, theta: float | None) -> None:
        self.theta = theta
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        bar = QRect(8, 2, max(self.width() - 16, 10), 12)
        for i in range(bar.width()):
            p.fillRect(bar.left() + i, bar.top(), 1, bar.height(), _qcolor(i / bar.width()))
        p.setPen(Qt.GlobalColor.black)
        ticks = [0.0, 0.5, 1.0] + ([self.theta] if self.theta is not None else [])
        for t in ticks:
            x = bar.left() + round(t * (bar.width() - 1))
            p.drawLine(x, bar.top(), x, bar.bottom() + 3)
            p.drawText(min(max(x - 14, 0), self.width() - 30), bar.bottom() + 15, f"{t:.2f}")
        p.end()


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

    heat_clicked = Signal(int, int)

    def __init__(self) -> None:
        super().__init__()
        self.heat: dict[int, float] = {}
        self.file_heat: FileHeat | None = None
        self._goto_selection: QTextEdit.ExtraSelection | None = None
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

    def set_file_heat(self, fh: FileHeat | None) -> None:
        self.file_heat = fh
        self.apply_selections()
        self.viewport().update()

    def set_goto(self, sel: QTextEdit.ExtraSelection | None) -> None:
        self._goto_selection = sel
        self.apply_selections()

    def apply_selections(self) -> None:
        out: list[QTextEdit.ExtraSelection] = []
        if self.file_heat is not None:
            out += self._tint_selections(self.file_heat)
            out += self._range_selections(self.file_heat)
        if self._goto_selection is not None:
            out.append(self._goto_selection)
        self.setExtraSelections(out)

    def _block_cursor(self, line: int, c0: int, c1: int) -> QTextCursor | None:
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return None
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + c0)
        cursor.setPosition(min(block.position() + c1, block.position() + block.length() - 1),
                           QTextCursor.MoveMode.KeepAnchor)
        return cursor

    def _tint_selections(self, fh: FileHeat) -> list[QTextEdit.ExtraSelection]:
        out: list[QTextEdit.ExtraSelection] = []
        for line, crit in fh.lines.items():
            block = self.document().findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(block)
            sel.format.setBackground(_qcolor(crit, LINE_TINT_ALPHA))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            out.append(sel)
        return out

    def _range_selections(self, fh: FileHeat) -> list[QTextEdit.ExtraSelection]:
        out: list[QTextEdit.ExtraSelection] = []
        for r in fh.ranges:
            parts = (
                [(g.col_start, g.col_end, g.crit) for g in r.segments]
                if r.segments
                else [(r.col_start, r.col_end, r.crit)]
            )
            for c0, c1, crit in parts:
                cursor = self._block_cursor(r.line, c0, c1)
                if cursor is None:
                    continue
                sel = QTextEdit.ExtraSelection()
                sel.cursor = cursor
                sel.format = _token_format(crit, r.unknown_bits)
                out.append(sel)
        return out

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.file_heat is None:
            return
        p = QPainter(self.viewport())
        for r in self.file_heat.ranges:
            if r.strip:
                self._paint_strip(p, r)
        p.end()

    def _paint_strip(self, p: QPainter, r: HeatRange) -> None:
        block = self.document().findBlockByNumber(r.line - 1)
        if not block.isValid():
            return
        a = QTextCursor(block)
        a.setPosition(block.position() + r.col_start)
        b = QTextCursor(block)
        b.setPosition(block.position() + r.col_end)
        ra, rb = self.cursorRect(a), self.cursorRect(b)
        width = max(rb.left() - ra.left(), len(r.strip))
        n = len(r.strip)
        for i, (_bit, crit) in enumerate(r.strip):
            x0 = ra.left() + width * i // n
            x1 = ra.left() + width * (i + 1) // n
            p.fillRect(x0, ra.bottom() - STRIP_HEIGHT, max(x1 - x0, 1), STRIP_HEIGHT, _qcolor(crit))

    def position_of(self, pos: QPoint) -> tuple[int, int]:
        cursor = self.cursorForPosition(pos)
        return cursor.blockNumber() + 1, cursor.positionInBlock()

    def event(self, e: QEvent) -> bool:
        if isinstance(e, QHelpEvent) and self.file_heat is not None:
            tip = self._tip_at(e.pos())
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
                return True
        return super().event(e)

    def _tip_at(self, pos: QPoint) -> str:
        fh = self.file_heat
        if fh is None:
            return ""
        line, col = self.position_of(pos)
        r = fh.range_at(line, col)
        if r is not None:
            return r.tooltip
        crit = fh.lines.get(line)
        return "" if crit is None else f"line {line}: crit {crit:.3f}"

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        super().mouseReleaseEvent(e)
        if self.file_heat is not None and not self.textCursor().hasSelection():
            line, col = self.position_of(e.position().toPoint())
            self.heat_clicked.emit(line, col)

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
        self.legend = HeatLegend()
        self.legend_note = QLabel("")
        self.legend.setVisible(False)
        self.legend_note.setVisible(False)
        self._highlighter: VerilogHighlighter | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addWidget(self.legend)
        layout.addWidget(self.legend_note)
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

    def set_file_heat(
        self, fh: FileHeat | None, theta: float | None = None, notes: list[str] | None = None
    ) -> None:
        """Show hot/cold tokens (None clears), a legend with the theta line and the notes."""
        self.text.set_file_heat(fh)
        shown = fh is not None
        self.legend.setVisible(shown)
        self.legend_note.setVisible(shown)
        self.legend.set_theta(theta)
        extra = [] if fh is None else [f"unplaced: {', '.join(fh.unplaced)}"] * bool(fh.unplaced)
        self.legend_note.setText("  ".join([heatview.LEGEND_NOTE, *(notes or []), *extra]))

    def open_file(self, path: Path, line: int | None = None) -> bool:
        self.path_label.setText(str(path))
        self._set_highlight(Path("-"))
        try:
            content = read_limited(path)
        except (OSError, ValueError) as e:
            reason = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
            self.path = None
            self.text.set_heat({})
            self.text.set_file_heat(None)
            self.text.setPlainText(f"Cannot show {path}: {reason}")
            self.text.set_goto(None)
            return False
        self.path = path
        self._set_highlight(path)
        self.text.setPlainText(content)
        self.text.set_goto(None)
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
        self.text.set_goto(sel)
