"""Read-only source viewer with Verilog highlighting."""

from __future__ import annotations

import stat
from bisect import bisect_left, bisect_right
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QHelpEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QTextBlock,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from wyrd.gui.highlighter import VerilogHighlighter
from wyrd.guimodel import heatview
from wyrd.guimodel.heatview import FileHeat, HeatRange
from wyrd.guimodel.pathview import Overlay

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
STEP_WIDTH = 96
DIM_ALPHA = 170
UNION_ALPHA = 110


def heat_color(share: float) -> QColor:
    """White to red; a share of 0.5 or more is full strength."""
    strength = min(max(share, 0.0) / 0.5, 1.0)
    return QColor.fromHsvF(0.0, 0.15 + 0.85 * strength, 1.0)


LINE_TINT_ALPHA = 55
STRIP_HEIGHT = 4
SELECTION_MARGIN = 300  # blocks above and below the viewport that get selections
UNKNOWN_FILL = "#c8c8c8"


def _qcolor(crit: float, alpha: int = 255) -> QColor:
    r, g, b = heatview.crit_rgb(crit)
    return QColor(r, g, b, alpha)


def _token_format(crit: float, unknown: bool) -> QTextCharFormat:
    fmt = QTextCharFormat()
    if crit < 0:  # a bit that was never seen with a bit index
        fmt.setBackground(QColor(UNKNOWN_FILL))
        fmt.setForeground(QColor("#000000"))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DotLine)
        fmt.setUnderlineColor(QColor("#000000"))
        return fmt
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
        self.setMinimumHeight(48)

    def set_theta(self, theta: float | None) -> None:
        self.theta = theta
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        bar = QRect(8, 2, max(self.width() - 16, 10), 12)
        for i in range(bar.width()):
            p.fillRect(bar.left() + i, bar.top(), 1, bar.height(), _qcolor(i / bar.width()))
        p.setPen(Qt.GlobalColor.black)
        self._tick_row(p, bar, [0.0, 0.5, 1.0], 15, "")
        if self.theta is not None:  # its own row, so its label never meets the others
            self._tick_row(p, bar, [self.theta], 28, "theta ")
        p.end()

    @staticmethod
    def _tick_row(p: QPainter, bar: QRect, ticks: list[float], y: int, prefix: str) -> None:
        for t in ticks:
            x = bar.left() + round(t * (bar.width() - 1))
            p.drawLine(x, bar.top(), x, bar.bottom() + (3 if y < 20 else 16))
            width = p.fontMetrics().horizontalAdvance(f"{prefix}{t:.2f}")
            left = min(max(x - width // 2, 0), max(bar.right() + 8 - width, 0))
            p.drawText(left, bar.bottom() + y, f"{prefix}{t:.2f}")


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
        self._range_lines: list[int] = []
        self._tint_lines: list[int] = []
        self._built: tuple[int, int] | None = None
        self.overlay: Overlay | None = None
        self._margin = _HeatMargin(self)
        self.updateRequest.connect(self._scroll_margin)
        self.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.setViewportMargins(0, 0, 0, 0)

    def _step_width(self) -> int:
        return STEP_WIDTH if self.overlay is not None and self.overlay.gutter() else 0

    def heat_width(self) -> int:
        return (HEAT_WIDTH if self.heat else 0) + self._step_width()

    def _relayout_margin(self) -> None:
        self.setViewportMargins(self.heat_width(), 0, 0, 0)
        self._place_margin()
        self._margin.setVisible(self.heat_width() > 0)
        self._margin.update()

    def set_heat(self, heat: dict[int, float]) -> None:
        self.heat = dict(heat)
        self._relayout_margin()

    def set_overlay(self, overlay: Overlay | None) -> None:
        """Show one path (step markers in the gutter) or a union (heat per line); everything not
        on it is dimmed. None clears."""
        self.overlay = overlay if overlay is not None and overlay.lines() else None
        self._relayout_margin()
        self.apply_selections()
        self.viewport().update()

    def set_file_heat(self, fh: FileHeat | None) -> None:
        self.file_heat = fh
        self._range_lines = [r.line for r in fh.ranges] if fh is not None else []
        self._tint_lines = sorted(fh.lines) if fh is not None else []
        self._built = None
        self.apply_selections()
        self.viewport().update()

    def set_goto(self, sel: QTextEdit.ExtraSelection | None) -> None:
        self._goto_selection = sel
        self.apply_selections()

    def _window(self) -> tuple[int, int]:
        """1-based first and last line that get selections: the viewport plus a margin."""
        first = self.firstVisibleBlock().blockNumber()
        bottom = self.cursorForPosition(QPoint(0, max(self.viewport().height() - 1, 0)))
        last = max(bottom.blockNumber(), first)
        return max(first - SELECTION_MARGIN, 0) + 1, last + SELECTION_MARGIN + 1

    def _scrolled(self) -> None:
        """Rebuild the selections when the viewport leaves the built window."""
        if self.file_heat is None or self._built is None:
            return
        first = self.firstVisibleBlock().blockNumber() + 1
        bottom = self.cursorForPosition(QPoint(0, max(self.viewport().height() - 1, 0)))
        last = bottom.blockNumber() + 1
        if first < self._built[0] or last > self._built[1]:
            self.apply_selections()

    def apply_selections(self) -> None:
        out: list[QTextEdit.ExtraSelection] = []
        if self.file_heat is not None:
            lo, hi = self._window()
            self._built = (lo, hi)
            out += self._tint_selections(self.file_heat, lo, hi)
            out += self._range_selections(self.file_heat, lo, hi)
        out += self._union_selections()
        if self._goto_selection is not None:
            out.append(self._goto_selection)
        self.setExtraSelections(out)

    def _block_cursor(self, line: int, c0: int, c1: int) -> QTextCursor | None:
        """Cursor over the code-point columns c0..c1 of a line (Qt counts UTF-16 units)."""
        block = self.document().findBlockByNumber(line - 1)
        if not block.isValid():
            return None
        text = block.text()
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + heatview.utf16_col(text, c0))
        cursor.setPosition(
            min(block.position() + heatview.utf16_col(text, c1),
                block.position() + block.length() - 1),
            QTextCursor.MoveMode.KeepAnchor,
        )  # fmt: skip
        return cursor

    def _tint_selections(self, fh: FileHeat, lo: int, hi: int) -> list[QTextEdit.ExtraSelection]:
        out: list[QTextEdit.ExtraSelection] = []
        keys = self._tint_lines
        for line in keys[bisect_left(keys, lo):bisect_right(keys, hi)]:
            block = self.document().findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(block)
            sel.format.setBackground(_qcolor(fh.lines[line], LINE_TINT_ALPHA))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            out.append(sel)
        return out

    def _range_selections(self, fh: FileHeat, lo: int, hi: int) -> list[QTextEdit.ExtraSelection]:
        out: list[QTextEdit.ExtraSelection] = []
        keys = self._range_lines
        for r in fh.ranges[bisect_left(keys, lo):bisect_right(keys, hi)]:
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

    def _union_selections(self) -> list[QTextEdit.ExtraSelection]:
        out: list[QTextEdit.ExtraSelection] = []
        if self.overlay is None or not self.overlay.union:
            return out
        for line, crit in self.overlay.colors.items():
            block = self.document().findBlockByNumber(line - 1)
            if not block.isValid():
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(block)
            sel.format.setBackground(_qcolor(crit, UNION_ALPHA))
            sel.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
            out.append(sel)
        return out

    def _paint_dim(self, p: QPainter) -> None:
        """Veil every visible line that is not on the shown path(s)."""
        ov = self.overlay
        if ov is None:
            return
        on = ov.lines()
        veil = QColor(self.palette().base().color())
        veil.setAlpha(DIM_ALPHA)
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= self.viewport().height():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and block.blockNumber() + 1 not in on:
                p.fillRect(0, top, self.viewport().width(), height, veil)
            top += height
            block = block.next()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if self.file_heat is None and self.overlay is None:
            return
        p = QPainter(self.viewport())
        self._paint_dim(p)
        if self.file_heat is not None:
            lo, hi = self._window()
            keys = self._range_lines
            on = self.overlay.lines() if self.overlay is not None else None
            for r in self.file_heat.ranges[bisect_left(keys, lo):bisect_right(keys, hi)]:
                if r.strip and (on is None or r.line in on):
                    self._paint_strip(p, r)
        p.end()

    def _paint_strip(self, p: QPainter, r: HeatRange) -> None:
        block = self.document().findBlockByNumber(r.line - 1)
        if not block.isValid():
            return
        text = block.text()
        a = QTextCursor(block)
        a.setPosition(block.position() + heatview.utf16_col(text, r.col_start))
        b = QTextCursor(block)
        b.setPosition(block.position() + heatview.utf16_col(text, r.col_end))
        ra, rb = self.cursorRect(a), self.cursorRect(b)
        width = max(rb.left() - ra.left(), len(r.strip))
        n = len(r.strip)
        for i, (_bit, crit) in enumerate(r.strip):
            x0 = ra.left() + width * i // n
            x1 = ra.left() + width * (i + 1) // n
            p.fillRect(x0, ra.bottom() - STRIP_HEIGHT, max(x1 - x0, 1), STRIP_HEIGHT, _qcolor(crit))

    def position_of(self, pos: QPoint) -> tuple[int, int]:
        cursor = self.cursorForPosition(pos)
        text = cursor.block().text()
        return cursor.blockNumber() + 1, heatview.codepoint_col(text, cursor.positionInBlock())

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

    def _paint_marker(self, painter: QPainter, block: QTextBlock, top: int, height: int) -> None:
        """Step numbers and delay of a line on the shown path, in the gutter."""
        if self.overlay is None or not self.overlay.gutter() or not block.isVisible():
            return
        text = self.overlay.marker(block.blockNumber() + 1)
        if not text:
            return
        left = HEAT_WIDTH if self.heat else 0
        painter.fillRect(left, top, STEP_WIDTH, height, QColor("#e8e8f4"))
        painter.setPen(Qt.GlobalColor.black)
        cell = QRect(left, top, STEP_WIDTH - 3, height)
        painter.drawText(cell, Qt.AlignmentFlag.AlignRight, text)

    def paint_heat(self, event: QPaintEvent) -> None:
        painter = QPainter(self._margin)
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        height = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            share = self.heat.get(block.blockNumber() + 1)
            if share is not None and block.isVisible():
                painter.fillRect(0, top, HEAT_WIDTH, height, heat_color(share))
                painter.setPen(Qt.GlobalColor.black)
                cell = QRect(0, top, HEAT_WIDTH - 3, height)
                painter.drawText(cell, Qt.AlignmentFlag.AlignRight, f"{share * 100:.0f}%")
            self._paint_marker(painter, block, top, height)
            top += round(self.blockBoundingRect(block).height())
            block = block.next()
        painter.end()


class SourceView(QWidget):
    cone_requested = Signal(str)  # ">" fan-out or "<" fan-in cone of the clicked token

    def __init__(self) -> None:
        super().__init__()
        self.fan_in = QPushButton("<")
        self.fan_out = QPushButton(">")
        self.fan_in.setToolTip("Fan-in cone of the clicked token: back to the primary inputs")
        self.fan_out.setToolTip("Fan-out cone of the clicked token: forward to the primary outputs")
        self.fan_in.clicked.connect(lambda: self.cone_requested.emit("<"))
        self.fan_out.clicked.connect(lambda: self.cone_requested.emit(">"))
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
        row = QHBoxLayout()
        row.addWidget(self.path_label, 1)
        row.addWidget(QLabel("Cone:"))
        row.addWidget(self.fan_in)
        row.addWidget(self.fan_out)
        for b in (self.fan_in, self.fan_out):
            b.setMaximumWidth(36)
        layout.addLayout(row)
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

    def set_overlay(self, overlay: Overlay | None) -> None:
        """Show a path or union overlay in the open file (None clears)."""
        self.text.set_overlay(overlay)

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

    def focus_token(self, line: int, c0: int, c1: int) -> None:
        """Scroll to a token (code-point columns of a 1-based line) and select it."""
        cursor = self.text._block_cursor(line, c0, c1)
        if cursor is None:
            return
        self.text.setTextCursor(cursor)
        self.text.centerCursor()
        self.text.apply_selections()

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
