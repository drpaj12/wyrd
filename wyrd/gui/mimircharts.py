"""Small QPainter charts for the Mímir browser: a ratio dot chart and a scatter plot."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QHelpEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from wyrd.guimodel import heatview
from wyrd.mimirview import CompareRow, Point

MARGIN = 40
LEFT, RIGHT, TOP, BOTTOM = 70, 16, 24, 44  # scatter plot area insets (room for tick labels)
DOT = 4.0
ROW_H = 18.0
AXIS_H = 30
LABEL_MAX = 320
LABEL_MIN = 60
LABEL_FRACTION = 0.4
GRID = "#dddddd"
TEXT = "#333333"


def nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """About `n` round tick values inside [lo, hi] (steps of 1, 2 or 5 times a power of ten)."""
    if not hi > lo:
        return [lo]
    raw = (hi - lo) / max(n, 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    first = math.ceil(lo / step - 1e-9)
    last = math.floor(hi / step + 1e-9)
    return [round(i * step, 12) for i in range(first, last + 1)]


def tick_text(v: float) -> str:
    return f"{v:.4g}"


class DotChart(QWidget):
    """One dot per config at its geomean ratio, a vertical line at 1 (the base)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[CompareRow] = []
        self.labels: list[str] = []
        self.setMouseTracking(True)
        self.setMinimumHeight(120)

    def set_rows(self, rows: list[CompareRow], multi_level: bool = False) -> None:
        self.rows = [r for r in rows if r.ratio is not None]
        self.labels = [f"{r.label} [{r.level}]" if multi_level else r.label for r in self.rows]
        self.setMinimumHeight(int(ROW_H * len(self.rows) + AXIS_H + 24) if self.rows else 120)
        self.update()

    def label_width(self) -> int:
        """Width of the label column: the longest label, capped (and at most 40% of the widget)."""
        fm = self.fontMetrics()
        longest = max((fm.horizontalAdvance(t) for t in self.labels), default=0) + 10
        cap = max(LABEL_MIN, min(LABEL_MAX, int(self.width() * LABEL_FRACTION)))
        return min(longest, cap)

    def display_label(self, i: int) -> str:
        """Label `i`, elided in the middle to the label column (single line)."""
        w = self.label_width() - 6
        return self.fontMetrics().elidedText(self.labels[i], Qt.TextElideMode.ElideMiddle, w)

    def x_range(self) -> tuple[float, float]:
        vals = [r.ratio for r in self.rows if r.ratio is not None] + [1.0]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.1 or 0.1
        return lo - pad, hi + pad

    def x_of(self, ratio: float, width: float) -> float:
        lo, hi = self.x_range()
        left = self.label_width()
        return left + (ratio - lo) / (hi - lo) * (width - left - 50)

    def row_at(self, y: float) -> int:
        i = int((y - 14 + ROW_H / 2) // ROW_H)
        return i if 0 <= i < len(self.rows) else -1

    def event(self, e: QEvent) -> bool:
        if e.type() == QEvent.Type.ToolTip and isinstance(e, QHelpEvent):
            i = self.row_at(e.pos().y())
            if i < 0:
                QToolTip.hideText()
            else:
                ratio = self.rows[i].ratio or 0.0
                QToolTip.showText(e.globalPos(), f"{self.labels[i]}\nratio {ratio:.4f}", self)
            return True
        return super().event(e)

    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().base())
        if not self.rows:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no comparison")
            return
        w = float(self.width())
        axis_y = 14 + (len(self.rows) - 1) * ROW_H + ROW_H
        self._paint_axis(p, w, axis_y)
        for i, r in enumerate(self.rows):
            if r.ratio is None:
                continue
            y = 14 + i * ROW_H
            p.setPen(QColor(TEXT))
            p.drawText(
                QRectF(2, y - 8, self.label_width() - 6, 16),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self.display_label(i),
            )
            p.setBrush(QColor("#2a6fdb"))
            p.drawEllipse(QPointF(self.x_of(r.ratio, w), y), DOT, DOT)
            p.drawText(QPointF(self.x_of(r.ratio, w) + 8, y + 4), f"{r.ratio:.3f}")

    def _paint_axis(self, p: QPainter, w: float, axis_y: float) -> None:
        lo, hi = self.x_range()
        p.setPen(QColor("#888888"))
        p.drawLine(QPointF(self.label_width(), axis_y), QPointF(w - 10, axis_y))
        for t in nice_ticks(lo, hi, 5):
            x = self.x_of(t, w)
            p.setPen(QPen(QColor(GRID), 1))
            p.drawLine(QPointF(x, 6), QPointF(x, axis_y))
            p.setPen(QColor(TEXT))
            p.drawLine(QPointF(x, axis_y), QPointF(x, axis_y + 4))
            p.drawText(QPointF(x - 14, axis_y + 16), tick_text(t))
        x1 = self.x_of(1.0, w)
        p.setPen(QPen(QColor("#888888"), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x1, 0), QPointF(x1, axis_y))


class ScatterChart(QWidget):
    """Scatter of points with optional log axes; hover shows the nearest point's label."""

    hovered = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.points: list[Point] = []
        self.log_x = False
        self.log_y = False
        self.x_name = ""
        self.y_name = ""
        self.setMouseTracking(True)
        self.setMinimumHeight(200)

    def set_points(self, pts: list[Point], x_name: str, y_name: str) -> None:
        self.points, self.x_name, self.y_name = pts, x_name, y_name
        self.update()

    def set_log(self, log_x: bool, log_y: bool) -> None:
        self.log_x, self.log_y = log_x, log_y
        self.update()

    def usable(self) -> list[Point]:
        return [
            p for p in self.points if (not self.log_x or p.x > 0) and (not self.log_y or p.y > 0)
        ]

    @staticmethod
    def _t(v: float, log: bool) -> float:
        return math.log10(v) if log else v

    def extent(self, pts: list[Point]) -> tuple[float, float, float, float]:
        """Min and max of the transformed x and y values: x0, x1, y0, y1."""
        xs = [self._t(p.x, self.log_x) for p in pts]
        ys = [self._t(p.y, self.log_y) for p in pts]
        return min(xs), max(xs), min(ys), max(ys)

    def plot_size(self) -> tuple[float, float]:
        return max(self.width() - LEFT - RIGHT, 1), max(self.height() - TOP - BOTTOM, 1)

    def project(self, pts: list[Point]) -> list[tuple[Point, float, float]]:
        if not pts:
            return []
        x0, x1, y0, y1 = self.extent(pts)
        w, h = self.plot_size()
        return [
            (
                p,
                LEFT + (self._t(p.x, self.log_x) - x0) / ((x1 - x0) or 1) * w,
                self.height() - BOTTOM - (self._t(p.y, self.log_y) - y0) / ((y1 - y0) or 1) * h,
            )
            for p in pts
        ]

    def nearest(self, x: float, y: float, radius: float = 8.0) -> Point | None:
        best: tuple[float, Point] | None = None
        for p, sx, sy in self.project(self.usable()):
            d = math.hypot(sx - x, sy - y)
            if d <= radius and (best is None or d < best[0]):
                best = (d, p)
        return None if best is None else best[1]

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        p = self.nearest(pos.x(), pos.y())
        self.hovered.emit("" if p is None else f"{p.label}  x={p.x:.6g}  y={p.y:.6g}")

    def axis_ticks(self, lo: float, hi: float, log: bool) -> list[tuple[float, str]]:
        """(position in transformed units, label in data units) for about five ticks."""
        return [(t, tick_text(10**t if log else t)) for t in nice_ticks(lo, hi, 5)]

    def paintEvent(self, _event: QPaintEvent) -> None:
        q = QPainter(self)
        q.fillRect(self.rect(), self.palette().base())
        w, h = self.plot_size()
        q.setPen(QColor("#888888"))
        q.drawRect(QRectF(LEFT, TOP, w, h))
        pts = self.usable()
        if pts:
            self._paint_ticks(q, pts, w, h)
        q.setPen(QColor(TEXT))
        q.drawText(QPointF(LEFT, self.height() - 6), self.x_name + (" (log)" if self.log_x else ""))
        q.drawText(QPointF(4, 14), self.y_name + (" (log)" if self.log_y else ""))
        q.setBrush(QColor(42, 111, 219, 160))
        q.setPen(Qt.PenStyle.NoPen)
        for _p, sx, sy in self.project(pts):
            q.drawEllipse(QPointF(sx, sy), 3.0, 3.0)

    def _paint_ticks(self, q: QPainter, pts: list[Point], w: float, h: float) -> None:
        x0, x1, y0, y1 = self.extent(pts)
        for t, text in self.axis_ticks(x0, x1, self.log_x):
            x = LEFT + (t - x0) / ((x1 - x0) or 1) * w
            q.setPen(QPen(QColor(GRID), 1))
            q.drawLine(QPointF(x, TOP), QPointF(x, TOP + h))
            q.setPen(QColor(TEXT))
            q.drawText(QPointF(x - 14, TOP + h + 14), text)
        for t, text in self.axis_ticks(y0, y1, self.log_y):
            y = TOP + h - (t - y0) / ((y1 - y0) or 1) * h
            q.setPen(QPen(QColor(GRID), 1))
            q.drawLine(QPointF(LEFT, y), QPointF(LEFT + w, y))
            q.setPen(QColor(TEXT))
            q.drawText(QPointF(4, y + 4), text)


class HistChart(QWidget):
    """Bar chart of the path criticality histogram (20 bins), bars coloured by bin crit."""

    def __init__(self) -> None:
        super().__init__()
        self.counts: list[int] = []
        self.setMinimumHeight(140)

    def set_counts(self, counts: list[int]) -> None:
        self.counts = list(counts)
        self.update()

    def bar_rects(self, w: float, h: float) -> list[QRectF]:
        top = max(self.counts, default=0) or 1
        n = len(self.counts) or 1
        bw = w / n
        return [QRectF(LEFT + i * bw, TOP + h * (1 - c / top), bw - 1, h * c / top)
                for i, c in enumerate(self.counts)]  # fmt: skip

    def paintEvent(self, _event: QPaintEvent) -> None:
        q = QPainter(self)
        q.fillRect(self.rect(), self.palette().base())
        w = max(self.width() - LEFT - MARGIN, 10.0)
        h = max(self.height() - TOP - AXIS_H, 10.0)
        q.setPen(QColor("#888888"))
        q.drawRect(QRectF(LEFT, TOP, w, h))
        n = len(self.counts) or 1
        for i, r in enumerate(self.bar_rects(w, h)):
            red, green, blue = heatview.crit_rgb((i + 0.5) / n)
            q.fillRect(r, QColor(red, green, blue))
        q.setPen(QColor(TEXT))
        top = max(self.counts, default=0)
        q.drawText(QPointF(4, 14), f"paths per crit bin (max {top})")
        for t in (0.0, 0.5, 0.9, 1.0):
            q.drawText(QPointF(LEFT + t * (w - 18), TOP + h + 14), f"{t:.1f}")
        q.drawText(QPointF(LEFT, self.height() - 6), "path criticality")
