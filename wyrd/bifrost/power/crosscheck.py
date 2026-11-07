"""Compare two activity sources net by net (descriptive, no hypothesis)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from wyrd.bifrost.power.vcdact import NetAct


@dataclass(frozen=True)
class Spread:
    min: float
    median: float
    p90: float
    max: float


@dataclass(frozen=True)
class CrossCheck:
    only_a: int
    only_b: int
    compared: int
    identical: int  # same activity within 1e-9 (toggle counts differ by 0 when cycles match)
    activity_diff: Spread
    p1_diff: Spread

    @property
    def identical_fraction(self) -> float:
        return self.identical / self.compared if self.compared else 0.0


def spread(values: Sequence[float]) -> Spread:
    if not values:
        return Spread(0.0, 0.0, 0.0, 0.0)
    v = sorted(values)
    return Spread(v[0], v[len(v) // 2], v[min(len(v) - 1, int(0.9 * len(v)))], v[-1])


def compare(a: Mapping[str, NetAct], b: Mapping[str, NetAct]) -> CrossCheck:
    common = sorted(set(a) & set(b))
    da = [abs(a[n].activity - b[n].activity) for n in common]
    dp = [abs(a[n].p1 - b[n].p1) for n in common]
    same = sum(1 for d in da if d < 1e-9)
    return CrossCheck(
        len(set(a) - set(b)), len(set(b) - set(a)), len(common), same, spread(da), spread(dp)
    )
