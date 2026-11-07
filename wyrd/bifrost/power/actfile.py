"""VPR activity (.act) files and the VPR power report (.power)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wyrd.bifrost.power.vcdact import NetAct


@dataclass(frozen=True)
class ActSummary:
    nets: int
    matched: int
    default_p1: float
    default_activity: float

    @property
    def matched_fraction(self) -> float:
        return self.matched / self.nets if self.nets else 0.0


def build_act(
    nets: Iterable[str], found: Mapping[str, NetAct], skip: Iterable[str] = ()
) -> tuple[dict[str, tuple[float, float]], ActSummary]:
    """Activity for every net; a net not in ``found`` gets the mean of the matched nets."""
    skipped = set(skip)
    names = [n for n in nets if n not in skipped]
    hit = {n: found[n] for n in names if n in found}
    mean_p = sum(a.p1 for a in hit.values()) / len(hit) if hit else 0.5
    mean_a = sum(a.activity for a in hit.values()) / len(hit) if hit else 0.1
    out = {n: (hit[n].p1, hit[n].activity) if n in hit else (mean_p, mean_a) for n in names}
    return out, ActSummary(len(names), len(hit), mean_p, mean_a)


def write_act(path: Path, act: Mapping[str, tuple[float, float]]) -> None:
    lines = [f"{n} {p:.6f} {a:.6f}" for n, (p, a) in act.items()]
    path.write_text("\n".join(lines) + "\n")


def read_act(path: Path) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for line in path.read_text().splitlines():
        words = line.split()
        if len(words) == 3:
            out[words[0]] = (float(words[1]), float(words[2]))
    return out


@dataclass
class FpgaPower:
    total_w: float
    dynamic_w: float
    static_w: float
    clock_w: float
    routing_w: float
    logic_w: float
    critical_path_s: float = 0.0
    warnings: list[str] = field(default_factory=list)


_ROW = re.compile(r"^\s*(Total|Routing|PB Types|Clock)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([\w.+-]+)")


def parse_power(text: str) -> FpgaPower:
    """Totals of a VPR ``.power`` file (the breakdown table and the warnings section)."""
    rows: dict[str, tuple[float, float]] = {}
    for line in text.splitlines():
        m = _ROW.match(line)
        if m and m.group(1) not in rows:
            frac = float(m.group(4)) if m.group(4) not in ("-nan", "nan") else 0.0
            rows[m.group(1)] = (float(m.group(2)), frac)
    if "Total" not in rows:
        raise ValueError("no power breakdown in the VPR power report")
    total, dyn_frac = rows["Total"]
    return FpgaPower(
        total_w=total,
        dynamic_w=total * dyn_frac,
        static_w=total * (1.0 - dyn_frac),
        clock_w=rows.get("Clock", (0.0, 0.0))[0],
        routing_w=rows.get("Routing", (0.0, 0.0))[0],
        logic_w=rows.get("PB Types", (0.0, 0.0))[0],
        critical_path_s=_crit(text),
        warnings=_warnings(text),
    )


def _warnings(text: str) -> list[str]:
    m = re.search(r"-+ Warnings -+\n(.*?)\n-{5,}", text, re.S)
    return [w.strip() for w in m.group(1).splitlines() if w.strip()] if m else []


def _crit(text: str) -> float:
    m = re.search(r"^Critical Path:\s*(\S+)", text, re.M)
    return float(m.group(1)) if m else 0.0
