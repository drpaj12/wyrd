"""VCD writer for a Recording (spec 7.2). One cycle is 10 time units, timescale 1ns."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from wyrd.bifrost.record import Recording

_BASE = 94


@dataclass
class _Var:
    code: str
    leaf: str
    width: int


@dataclass
class _Scope:
    variables: list[_Var] = field(default_factory=list)
    children: dict[str, _Scope] = field(default_factory=dict)


def _code(k: int) -> str:
    digits: list[str] = []
    while True:
        k, d = divmod(k, _BASE)
        digits.append(chr(33 + d))
        if k == 0:
            return "".join(digits)


def _clean(text: str) -> str:
    return "".join(
        chr(b) if 33 <= b <= 126 and chr(b) not in "[]" else "_" for b in text.encode("utf-8")
    )


def _scope_tree(entries: list[tuple[str, int, str]]) -> _Scope:
    root = _Scope()
    for name, width, code in entries:
        *path, leaf = [_clean(p) for p in name.split(".")]
        node = root
        for part in path:
            node = node.children.setdefault(part, _Scope())
        node.variables.append(_Var(code, leaf, width))
    return root


def _var_line(v: _Var) -> str:
    rng = f" [{v.width - 1}:0]" if v.width > 1 else ""
    return f"$var wire {v.width} {v.code} {v.leaf}{rng} $end"


def _declarations(root: _Scope, top: str) -> list[str]:
    lines: list[str] = []
    stack: list[str | tuple[str, _Scope]] = [(_clean(top), root)]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            lines.append(item)
            continue
        name, scope = item
        lines.append(f"$scope module {name} $end")
        lines.extend(_var_line(v) for v in scope.variables)
        stack.append("$upscope $end")
        stack.extend(reversed(list(scope.children.items())))
    return lines


def _value(value: int, width: int, code: str) -> str:
    if width == 1:
        return f"{value}{code}"
    return f"b{value:0{width}b} {code}"


@dataclass
class _Layout:
    """Variables in VCD order: clocks first, then the recorded names."""

    names: list[str]
    widths: list[int]
    codes: list[str]
    nclocks: int
    is_input: list[bool]


def _layout(rec: Recording) -> _Layout:
    names = [*rec.clocks, *rec.names]
    widths = [1] * len(rec.clocks) + list(rec.widths)
    flags = [False] * len(rec.clocks) + [n in rec.inputs for n in rec.names]
    codes = [_code(k) for k in range(len(names))]
    return _Layout(names, widths, codes, len(rec.clocks), flags)


class _Writer:
    def __init__(self, lay: _Layout) -> None:
        self.lay = lay
        self.last: dict[int, int] = {}
        self.lines: list[str] = []

    def emit(self, var: int, value: int) -> str | None:
        if self.last.get(var) == value:
            return None
        self.last[var] = value
        return _value(value, self.lay.widths[var], self.lay.codes[var])

    def at(self, time: int, changes: list[tuple[int, int]]) -> None:
        body = [line for var, v in changes if (line := self.emit(var, v)) is not None]
        if body:
            self.lines.append(f"#{time}")
            self.lines.extend(body)

    def dump_start(self, first: tuple[int, ...]) -> None:
        nclk = self.lay.nclocks
        values = [0] * nclk + (list(first) if first else [0] * (len(self.lay.names) - nclk))
        self.lines.append("#0")
        self.lines.append("$dumpvars")
        for var, v in enumerate(values):
            self.lines.append(self.emit(var, v) or "")
        self.lines.append("$end")

    def cycle(self, c: int, sample: tuple[int, ...]) -> None:
        nclk = self.lay.nclocks
        clocks = range(nclk)
        data = [(nclk + j, v) for j, v in enumerate(sample)]
        ins = [(var, v) for var, v in data if self.lay.is_input[var]]
        rest = [(var, v) for var, v in data if not self.lay.is_input[var]]
        self.at(10 * c - 8, ins)
        self.at(10 * c - 5, [(k, 1) for k in clocks] + rest)
        self.at(10 * c, [(k, 0) for k in clocks])


def vcd_text(rec: Recording, top: str = "top") -> str:
    lay = _layout(rec)
    entries = list(zip(lay.names, lay.widths, lay.codes, strict=True))
    head = [
        "$version wyrd sim $end",
        "$timescale 1ns $end",
        *_declarations(_scope_tree(entries), top),
        "$enddefinitions $end",
    ]
    w = _Writer(lay)
    w.dump_start(rec.samples[0] if rec.samples else ())
    for c, sample in zip(rec.cycles[1:], rec.samples[1:], strict=True):
        w.cycle(c, sample)
    return "\n".join([*head, *w.lines]) + "\n"


def write_vcd(rec: Recording, path: Path, top: str = "top") -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(vcd_text(rec, top), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
