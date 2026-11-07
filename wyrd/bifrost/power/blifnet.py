"""BLIF reader, Verilog netlist writer for gate-level simulation, and the Odin III names file."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_BIT = re.compile(r"^(.*)\[(\d+)\]$")


@dataclass
class Names:
    inputs: list[str]
    output: str
    rows: list[tuple[str, str]]  # (cube, output value)


@dataclass
class Latch:
    d: str
    q: str
    kind: str
    clock: str


@dataclass
class Blif:
    model: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    names: list[Names] = field(default_factory=list)
    latches: list[Latch] = field(default_factory=list)
    subckts: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def nets(self) -> list[str]:
        """Every driven net: inputs, gate outputs, latch outputs, subckt outputs, in file order."""
        seen: dict[str, None] = dict.fromkeys(self.inputs)
        for n in self.names:
            seen.setdefault(n.output)
        for lt in self.latches:
            seen.setdefault(lt.q)
        for _, pins in self.subckts:
            for pin, net in pins.items():
                if pin in ("cout", "sumout"):
                    seen.setdefault(net)
        return list(seen)


def _logical_lines(text: str) -> list[str]:
    out: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        line = pending + line
        pending = ""
        if line.strip():
            out.append(line.strip())
    return out


def parse_blif(text: str) -> Blif:
    blif = Blif()
    cur: Names | None = None
    for line in _logical_lines(text):
        words = line.split()
        if words[0] != ".end" and not words[0].startswith("."):
            if cur is not None:
                cube, val = (words[0], words[1]) if len(words) > 1 else ("", words[0])
                cur.rows.append((cube, val))
            continue
        cur = None
        if words[0] == ".model":
            blif.model = blif.model or words[1]
        elif words[0] == ".inputs":
            blif.inputs += words[1:]
        elif words[0] == ".outputs":
            blif.outputs += words[1:]
        elif words[0] == ".names":
            cur = Names(words[1:-1], words[-1], [])
            blif.names.append(cur)
        elif words[0] == ".latch":
            blif.latches.append(_latch(words))
        elif words[0] == ".subckt":
            blif.subckts.append((words[1], dict(w.split("=", 1) for w in words[2:])))
    return blif


def _latch(words: list[str]) -> Latch:
    kind = words[3] if len(words) > 4 else "re"
    clock = words[4] if len(words) > 4 else ""
    return Latch(words[1], words[2], kind, clock)


def _esc(name: str) -> str:
    return "\\" + name + " "


def _cube_expr(inputs: list[str], cube: str) -> str:
    lits = [
        ("" if c == "1" else "~") + _esc(n) for n, c in zip(inputs, cube, strict=True) if c != "-"
    ]
    return "(" + " & ".join(lits) + ")" if lits else "1'b1"


def _names_expr(n: Names) -> str:
    if not n.rows:
        return "1'b0"
    on = n.rows[0][1] == "1"
    terms = [_cube_expr(n.inputs, cube) for cube, _ in n.rows]
    body = " | ".join(terms)
    return f"({body})" if on else f"~({body})"


def _subckt_lines(model: str, pins: dict[str, str]) -> list[str]:
    if model != "adder":
        raise ValueError(f"unsupported .subckt {model} in a gate-level netlist")
    s = f"{_esc(pins['a'])}+ {_esc(pins['b'])}+ {_esc(pins['cin'])}"
    return [f"assign {{{_esc(pins['cout'])}, {_esc(pins['sumout'])}}} = {s};"]


def verilog_netlist(blif: Blif, module: str) -> str:
    """The BLIF as a Verilog module ``module`` with the BLIF net names as escaped identifiers."""
    regs = {lt.q for lt in blif.latches}
    ports = ",\n  ".join(
        [f"input {_esc(n)}" for n in blif.inputs]
        + [f"output {'reg ' if n in regs else ''}{_esc(n)}" for n in blif.outputs]
    )
    lines = [f"module {module} (\n  {ports}\n);"]
    port_set = set(blif.inputs) | set(blif.outputs)
    for net in blif.nets() + [lt.d for lt in blif.latches]:
        if net not in port_set:
            port_set.add(net)
            lines.append(f"{'reg' if net in regs else 'wire'} {_esc(net)};")
    for n in blif.names:
        lines.append(f"assign {_esc(n.output)} = {_names_expr(n)};")
    for lt in blif.latches:
        edge = "negedge" if lt.kind == "fe" else "posedge"
        lines.append(f"always @({edge} {_esc(lt.clock)}) {_esc(lt.q)} <= {_esc(lt.d)};")
    for model, pins in blif.subckts:
        lines += _subckt_lines(model, pins)
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def port_groups(names: list[str]) -> dict[str, int]:
    """Port base name to width: ``a[3]`` and ``a[0]`` make ``a`` 4 bits wide; scalars are 1."""
    width: dict[str, int] = defaultdict(int)
    for n in names:
        m = _BIT.match(n)
        base, hi = (m.group(1), int(m.group(2)) + 1) if m else (n, 1)
        width[base] = max(width[base], hi)
    return dict(width)


def wrapper(blif: Blif, inner: str, outer: str) -> str:
    """Module ``outer`` with vector ports, instantiating the netlist module ``inner``."""
    decl = _decls("input", blif.inputs) + _decls("output", blif.outputs)
    conns = [f".{_esc(n)}({n})" for n in blif.inputs + blif.outputs]
    body = ",\n    ".join(conns)
    head = ",\n  ".join(decl)
    return f"module {outer} (\n  {head}\n);\n  {inner} u_nl (\n    {body}\n  );\nendmodule\n"


def _decls(direction: str, nets: list[str]) -> list[str]:
    out = []
    for base, w in port_groups(nets).items():
        vec = any(_BIT.match(n) and _base(n) == base for n in nets)
        out.append(f"{direction} [{w - 1}:0] {base}" if vec else f"{direction} {base}")
    return out


def _base(net: str) -> str:
    m = _BIT.match(net)
    return m.group(1) if m else net


@dataclass(frozen=True)
class Provenance:
    """One row of an Odin III names file: where a BLIF net comes from in the HDL."""

    net: str
    name: str
    file: str
    line: int


def parse_names(text: str) -> dict[str, Provenance]:
    """Hash net name (or kept HDL name) to its provenance. ``N`` rows keep their HDL name."""
    out: dict[str, Provenance] = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 8 and cols[0] == "O" and cols[2] == "net":
            out[cols[3]] = Provenance(cols[3], cols[4], cols[6], int(cols[7]))
    return out


def read_blif(path: Path) -> Blif:
    return parse_blif(path.read_text())
