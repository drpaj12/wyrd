"""Small QPainter charts for the Mímir browser: a ratio dot chart and a scatter plot."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from wyrd.mimirview import CompareRow, Point

MARGIN = 40
DOT = 4.0
LABEL_W = 170


class DotChart(QWidget):
    """One dot per config at its geomean ratio, a vertical line at 1 (the base)."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[CompareRow] = []
        self.setMinimumHeight(120)

    def set_rows(self, rows: list[CompareRow]) -> None:
        self.rows = [r for r in rows if r.ratio is not None]
        self.update()

    def x_range(self) -> tuple[float, float]:
        vals = [r.ratio for r in self.rows if r.ratio is not None] + [1.0]
        lo, hi = min(vals), max(vals)
        pad = (hi - lo) * 0.1 or 0.1
        return lo - pad, hi + pad

    def x_of(self, ratio: float, width: float) -> float:
        lo, hi = self.x_range()
        return LABEL_W + (ratio - lo) / (hi - lo) * (width - LABEL_W - 10)

    def paintEvent(self, _event: QPaintEvent) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().base())
        if not self.rows:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no comparison")
            return
        w = float(self.width())
        step = max(14.0, (self.height() - 20.0) / len(self.rows))
        x1 = self.x_of(1.0, w)
        p.setPen(QPen(QColor("#888888"), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(x1, 0), QPointF(x1, self.height()))
        for i, r in enumerate(self.rows):
            if r.ratio is None:
                continue
            y = 14 + i * step
            p.setPen(QColor("#333333"))
            p.drawText(QRectF(2, y - 8, LABEL_W - 6, 16), r.label)
            p.setBrush(QColor("#2a6fdb"))
            p.drawEllipse(QPointF(self.x_of(r.ratio, w), y), DOT, DOT)
            p.drawText(QPointF(self.x_of(r.ratio, w) + 8, y + 4), f"{r.ratio:.3f}")


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
        self.setMinimumHeight(160)

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

    def project(self, pts: list[Point]) -> list[tuple[Point, float, float]]:
        if not pts:
            return []
        xs = [self._t(p.x, self.log_x) for p in pts]
        ys = [self._t(p.y, self.log_y) for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w = max(self.width() - 2 * MARGIN, 1)
        h = max(self.height() - 2 * MARGIN, 1)
        return [
            (
                p,
                MARGIN + (x - x0) / ((x1 - x0) or 1) * w,
                self.height() - MARGIN - (y - y0) / ((y1 - y0) or 1) * h,
            )
            for p, x, y in zip(pts, xs, ys, strict=True)
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

    def paintEvent(self, _event: QPaintEvent) -> None:
        q = QPainter(self)
        q.fillRect(self.rect(), self.palette().base())
        q.setPen(QColor("#888888"))
        q.drawRect(MARGIN, MARGIN, self.width() - 2 * MARGIN, self.height() - 2 * MARGIN)
        q.setPen(QColor("#333333"))
        q.drawText(
            QPointF(MARGIN, self.height() - 8), self.x_name + (" (log)" if self.log_x else "")
        )
        q.drawText(QPointF(4, 16), self.y_name + (" (log)" if self.log_y else ""))
        q.setBrush(QColor(42, 111, 219, 160))
        q.setPen(Qt.PenStyle.NoPen)
        for _p, sx, sy in self.project(self.usable()):
            q.drawEllipse(QPointF(sx, sy), 3.0, 3.0)
