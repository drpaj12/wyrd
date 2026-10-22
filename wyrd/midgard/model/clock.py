"""Fixed-step game time (spec 5.9): wall-clock time to whole ticks."""

from __future__ import annotations

TICKS_PER_SECOND = 60
MAX_BACKLOG = 30
SPEEDS = (1, 2, 4)


def ticks_to_seconds(ticks: int) -> int:
    return ticks // TICKS_PER_SECOND


class TickClock:
    def __init__(
        self, ticks_per_second: int = TICKS_PER_SECOND, max_backlog: int = MAX_BACKLOG
    ) -> None:
        self.ticks_per_second = ticks_per_second
        self.max_backlog = max_backlog
        self.acc = 0.0

    def advance(self, dt: float, speed: int = 1) -> int:
        """Add `dt` seconds of wall time; return how many whole ticks to run now."""
        if dt < 0:
            raise ValueError("dt must not be negative")
        if speed not in SPEEDS:
            raise ValueError(f"speed must be one of {SPEEDS}")
        self.acc += dt * self.ticks_per_second * speed
        self.acc = min(self.acc, float(self.max_backlog))
        n = int(self.acc + 1e-9)
        self.acc = max(self.acc - n, 0.0)
        return n

    def reset(self) -> None:
        self.acc = 0.0
