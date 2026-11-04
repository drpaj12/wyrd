"""Read a BLIF to netlist edges, fanin, fanout and logic level (standard library only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

OUT_PIN_PREFIXES = ("out", "dout", "q")


@dataclass
class Netlist:
    """Nets by name: the driver kind, the nets it reads, and edges (driver net, sink net, kind)."""

    drivers: dict[str, str] = field(default_factory=dict)  # net -> names | latch | subckt
    inputs: dict[str, list[str]] = field(default_factory=dict)  # net -> nets it reads
    primary_inputs: set[str] = field(default_factory=set)

    def edges(self) -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for net in sorted(self.inputs):
            kind = self.drivers[net]
            out.extend((src, net, kind) for src in sorted(set(self.inputs[net])))
        return out

    def fanout(self) -> dict[str, int]:
        count: dict[str, int] = {}
        for net, srcs in self.inputs.items():
            for src in set(srcs):
                count[src] = count.get(src, 0) + 1
            count.setdefault(net, 0)
        return count

    def levels(self) -> dict[str, int]:
        """Logic depth: 0 at inputs and register or block outputs; a LUT adds one."""
        memo: dict[str, int] = {}
        visiting: set[str] = set()
        for root in sorted(self.drivers):
            stack = [root]
            while stack:
                net = stack[-1]
                if net in memo:
                    stack.pop()
                elif self.drivers.get(net) != "names":
                    memo[net] = 0
                    stack.pop()
                else:
                    visiting.add(net)
                    pending = [s for s in self.inputs[net] if s not in memo and s not in visiting]
                    if pending:
                        stack.extend(pending)
                        continue
                    memo[net] = 1 + max((memo.get(s, 0) for s in self.inputs[net]), default=0)
                    visiting.discard(net)
                    stack.pop()
        return memo


def stages_of(nl: Netlist) -> dict[str, int]:
    """Register stage: registers and block outputs add one to the deepest input stage."""
    memo: dict[str, int] = {}
    visiting: set[str] = set()
    for root in sorted(nl.drivers):
        stack = [root]
        while stack:
            net = stack[-1]
            if net in memo:
                stack.pop()
                continue
            visiting.add(net)
            pending = [
                s
                for s in nl.inputs.get(net, [])
                if s in nl.drivers and s not in memo and s not in visiting
            ]
            if pending:
                stack.extend(pending)
                continue
            deepest = max((memo.get(s, 0) for s in nl.inputs.get(net, [])), default=0)
            memo[net] = deepest + (0 if nl.drivers[net] == "names" else 1)
            visiting.discard(net)
            stack.pop()
    return memo


def logical_lines(text: str) -> list[str]:
    lines: list[str] = []
    cur = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.endswith("\\"):
            cur += line[:-1] + " "
            continue
        cur += line
        if cur.strip():
            lines.append(cur.strip())
        cur = ""
    if cur.strip():
        lines.append(cur.strip())
    return lines


def read_blif(path: Path) -> Netlist:
    nl = Netlist()
    for line in logical_lines(path.read_text(encoding="utf-8")):
        words = line.split()
        key = words[0]
        if key == ".inputs":
            nl.primary_inputs.update(words[1:])
        elif key == ".names" and len(words) >= 2:
            nl.drivers[words[-1]] = "names"
            nl.inputs[words[-1]] = words[1:-1]
        elif key == ".latch" and len(words) >= 3:
            nl.drivers[words[2]] = "latch"
            nl.inputs[words[2]] = [words[1]]
        elif key == ".subckt":
            add_subckt(nl, words[2:])
    return nl


def add_subckt(nl: Netlist, pins: list[str]) -> None:
    ins: list[str] = []
    outs: list[str] = []
    for pin in pins:
        port, _, net = pin.partition("=")
        base = port.split("[", 1)[0]
        (outs if base in OUT_PIN_PREFIXES else ins).append(net)
    for net in outs:
        nl.drivers[net] = "subckt"
        nl.inputs[net] = ins
