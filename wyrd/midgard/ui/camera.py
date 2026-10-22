"""Zoom and pan of the level layer (spec 9.3). No pygame here."""

from __future__ import annotations

W, H = 1280, 1380
MAP = 1280
TILE = 64
MIN_ZOOM = 0.2


def _r(v: float) -> float:
    return round(v, 6)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Camera:
    def __init__(self) -> None:
        self.zoom = 1.0
        self.x = 640.0
        self.y = 690.0

    def wheel(self, amount: int) -> None:
        if amount < 0:
            z = _r(self.zoom - 0.04)
            self.zoom = MIN_ZOOM if z < MIN_ZOOM else z
        elif amount > 0:
            z = _r(self.zoom + 0.04)
            self.zoom = 1.0 if z > 1.0 else z
        self.limit_to_border()

    def key_zoom_in(self) -> None:
        if self.zoom >= 0.1:
            self.zoom = _r(self.zoom - 0.02)
        self.limit_to_border()

    def key_zoom_out(self) -> None:
        if self.zoom != 1.0:
            self.zoom = _r(self.zoom + 0.02)
        self.limit_to_border()

    def pan(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        self.limit_to_border()

    def drag(self, last_real: tuple[float, float], current_real: tuple[float, float]) -> None:
        if last_real[0] == 0 or last_real[1] == 0:
            return
        self.pan(last_real[0] - current_real[0], last_real[1] - current_real[1])

    def limit_to_border(self) -> None:
        min_x, min_y = W * self.zoom / 2, H * self.zoom / 2
        self.x = _clamp(self.x, min_x, W - min_x)
        self.y = _clamp(self.y, min_y, H - min_y - (1 - self.zoom) * 100)

    def to_world(
        self, lx: float, ly: float, win: tuple[int, int] = (W, H)
    ) -> tuple[float, float]:
        z = self.zoom
        real_x = (self.x - W * z / 2) + (lx / win[0]) * W * z
        real_y = (self.y - H * z / 2) + (1 - ly / win[1]) * H * z
        return _clamp(real_x, 0, W), _clamp(real_y, 0, H)

    def tile_at(self, lx: float, ly: float) -> tuple[int, int] | None:
        real_x, real_y = self.to_world(lx, ly)
        if real_y > MAP:
            return None
        return int(real_x / TILE) + 1, int(real_y / TILE) + 1

    def visible_rect(self) -> tuple[float, float, float, float]:
        z = self.zoom
        return (self.x - W * z / 2, self.y - H * z / 2, W * z, H * z)
