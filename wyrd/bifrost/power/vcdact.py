"""Per-bit static probability and switching activity from a VCD file (streaming)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_RANGE = re.compile(r"^\[(\d+)(?::(\d+))?\]$")


@dataclass(frozen=True)
class NetAct:
    """Activity of one bit. ``activity`` is toggles per clock cycle, ``p1`` the probability of 1."""

    p1: float
    activity: float
    toggles: int
    known_time: int


@dataclass
class _Bit:
    name: str
    last: int | None = None
    t_last: int = 0
    t1: int = 0
    tk: int = 0
    toggles: int = 0
    rises: int = 0

    def update(self, t: int, v: int | None) -> None:
        if self.last is not None:
            dt = t - self.t_last
            self.tk += dt
            if self.last == 1:
                self.t1 += dt
            if v is not None and v != self.last:
                self.toggles += 1
                if v == 1:
                    self.rises += 1
        self.last = v
        self.t_last = t


@dataclass
class _Var:
    bits: list[_Bit]  # index 0 is the least significant bit


def _bit_names(path: str, ref: str, width: int, rng: str | None) -> list[str]:
    ref = ref.lstrip("\\")
    m = _RANGE.match(rng) if rng else None
    if width == 1:
        if m and m.group(2) is None:
            return [f"{path}{ref}[{m.group(1)}]"]
        return [f"{path}{ref}"]
    low = 0
    if m and m.group(2) is not None:
        low = min(int(m.group(1)), int(m.group(2)))
    return [f"{path}{ref}[{low + i}]" for i in range(width)]


def _parse_var(tokens: list[str], scope: list[str]) -> tuple[str, _Var]:
    width, ident, ref = int(tokens[2]), tokens[3], tokens[4]
    rng = tokens[5] if len(tokens) > 6 and tokens[5] != "$end" else None
    path = "".join(s + "." for s in scope)
    return ident, _Var([_Bit(n) for n in _bit_names(path, ref, width, rng)])


def _bit_value(ch: str) -> int | None:
    return int(ch) if ch in "01" else None


def _vector_bits(text: str, width: int) -> list[int | None]:
    text = text.lower()
    pad = "0" if text[0] == "1" or text[0] == "0" else text[0]
    text = text.rjust(width, pad)[-width:]
    return [_bit_value(c) for c in reversed(text)]


class _Reader:
    def __init__(self) -> None:
        self.vars: dict[str, list[_Var]] = {}
        self.scope: list[str] = []
        self.t = 0
        self.in_defs = True

    def header(self, line: str) -> None:
        tokens = line.split()
        if not tokens:
            return
        if tokens[0] == "$scope":
            self.scope.append(tokens[2])
        elif tokens[0] == "$upscope":
            self.scope.pop()
        elif tokens[0] == "$var":
            ident, var = _parse_var(tokens, self.scope)
            self.vars.setdefault(ident, []).append(var)
        elif tokens[0] == "$enddefinitions":
            self.in_defs = False

    def change(self, ident: str, values: list[int | None]) -> None:
        for var in self.vars.get(ident, ()):
            for bit, v in zip(var.bits, values, strict=False):
                bit.update(self.t, v)

    def body(self, line: str) -> None:
        line = line.strip()
        if not line or line.startswith("$"):
            return
        c = line[0]
        if c == "#":
            self.t = int(line[1:])
        elif c in "bB":
            text, ident = line[1:].split()
            width = len(self.vars[ident][0].bits) if ident in self.vars else len(text)
            self.change(ident, _vector_bits(text, width))
        elif c in "01xXzZ":
            self.change(line[1:], [_bit_value(c)])


def _finish(reader: _Reader, clock: str) -> dict[str, NetAct]:
    clocks = [b for vs in reader.vars.values() for v in vs for b in v.bits if _is_clock(b, clock)]
    if not clocks:
        raise ValueError(f"clock net '{clock}' not found in the VCD")
    cycles = max(b.rises for b in clocks)
    if cycles == 0:
        raise ValueError(f"clock net '{clock}' never rises")
    out: dict[str, NetAct] = {}
    for vs in reader.vars.values():
        for v in vs:
            for b in v.bits:
                b.update(reader.t, b.last)
                p1 = b.t1 / b.tk if b.tk else 0.0
                out[b.name] = NetAct(p1, b.toggles / cycles, b.toggles, b.tk)
    return out


def _is_clock(bit: _Bit, clock: str) -> bool:
    return bit.name == clock or bit.name.endswith("." + clock)


def clock_cycles(acts: dict[str, NetAct], clock: str) -> int:
    """Rising edges of the clock net (a clock toggles twice per cycle)."""
    for name, a in acts.items():
        if name == clock or name.endswith("." + clock):
            return a.toggles // 2
    raise ValueError(f"clock net '{clock}' not found")


def read_activity(lines: Iterable[str], clock: str) -> dict[str, NetAct]:
    """Activity of every bit in a VCD. ``clock`` is the clock net's name (leaf or dotted path)."""
    reader = _Reader()
    for line in lines:
        if reader.in_defs:
            reader.header(line)
        else:
            reader.body(line)
    return _finish(reader, clock)


def read_activity_file(path: Path, clock: str) -> dict[str, NetAct]:
    with path.open(errors="replace") as f:
        return read_activity(f, clock)


class Sampler:
    """Values of chosen signals just before each rising edge of a clock net."""

    def __init__(self, clock: str, signals: dict[str, int]) -> None:
        self.clock = clock
        self.signals = signals  # full bit-name prefix (``tb.dut.a``) -> width
        self.reader = _Reader()
        self.rows: list[dict[str, int]] = []
        self._cur: dict[str, int | None] = {}
        self._pending: dict[str, int | None] = {}
        self._ids: dict[str, list[str]] = {}

    def feed(self, line: str) -> None:
        r = self.reader
        if r.in_defs:
            r.header(line)
            return
        line = line.strip()
        if line.startswith("#"):
            self.flush()
            r.t = int(line[1:])
        elif line and line[0] in "01xXzZbB" and not line.startswith("$"):
            self._pending_change(line)

    def _pending_change(self, line: str) -> None:
        if line[0] in "bB":
            text, ident = line[1:].split()
            width = len(self.reader.vars[ident][0].bits) if ident in self.reader.vars else len(text)
            vals = _vector_bits(text, width)
        else:
            ident, vals = line[1:], [_bit_value(line[0])]
        for var in self.reader.vars.get(ident, ()):
            for bit, v in zip(var.bits, vals, strict=False):
                self._pending[bit.name] = v

    def flush(self) -> None:
        if not self._pending:
            return
        before = self._cur.get(self.clock)
        after = self._pending.get(self.clock, before)
        if before == 0 and after == 1:
            self.rows.append(self._row())
        self._cur.update(self._pending)
        self._pending = {}

    def _row(self) -> dict[str, int]:
        row: dict[str, int] = {}
        for name, width in self.signals.items():
            value = 0
            for i in range(width):
                key = f"{name}[{i}]" if width > 1 else name
                if self._cur.get(key) == 1:
                    value |= 1 << i
            row[name] = value
        return row


def sample_rising(
    lines: Iterable[str], clock: str, signals: dict[str, int]
) -> list[dict[str, int]]:
    """One row per rising edge of ``clock`` (full bit name): each signal just before the edge."""
    s = Sampler(clock, signals)
    for line in lines:
        s.feed(line)
    s.flush()
    return s.rows
