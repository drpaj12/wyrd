"""Vector file <-> Verilog testbench (spec 2026-10-31 section 3)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from wyrd.bifrost.errors import SimError
from wyrd.bifrost.types import Signal
from wyrd.bifrost.vectors import VectorFile, data_ports, port_lines

MAX_WIDTH = 64
HEADER_TAG = "// wyrd-vectors-header: "
_TB_MODULE = "wyrd_tb"
_BITS = re.compile(r"^[01]+$")


class ConvertError(SimError):
    """A conversion that cannot be done (wide port, unknown DUT top, foreign output)."""


def _check_widths(signals: Sequence[Signal]) -> None:
    for s in signals:
        if s.width > MAX_WIDTH:
            raise ConvertError(
                f"{s.name}: {s.width} bits; testbench mode handles at most {MAX_WIDTH}"
            )


def _decl(kind: str, s: Signal) -> str:
    rng = f" [{s.width - 1}:0]" if s.width > 1 else ""
    return f"  {kind}{rng} {s.name};"


def _bits(value: int, width: int) -> str:
    return f"{value:0{width}b}"


def _display_text(
    cycle: int, data: Sequence[Signal], outputs: Sequence[Signal], row: Sequence[int]
) -> str:
    ins = "".join(_bits(v, s.width) for v, s in zip(row, data, strict=True)) or "-"
    fmt = f"{cycle} {ins}" + (" " + "%b" * len(outputs) if outputs else "")
    args = "".join(f", {o.name}" for o in outputs)
    return f'$display("{fmt}"{args});'


def _cycle_lines(
    cycle: int,
    row: Sequence[int],
    clock: Signal | None,
    data: Sequence[Signal],
    outputs: Sequence[Signal],
) -> str:
    sets = " ".join(
        f"{s.name} = {s.width}'b{_bits(v, s.width)};" for v, s in zip(row, data, strict=True)
    )
    show = _display_text(cycle, data, outputs, row)
    if clock is None:
        return f"    {sets} #10 {show}"
    return f"    {sets} #5 {clock.name} = 1; #1 {show} #4 {clock.name} = 0;"


def vectors_to_testbench(
    module: str,
    ports: Sequence[Signal],
    outputs: Sequence[Signal],
    vf: VectorFile,
    header: str,
) -> str:
    """A port-only testbench that applies `vf` cycle by cycle and prints vector lines."""
    data = data_ports(ports)
    clock = next((p for p in ports if p.kind == "clock"), None)
    _check_widths([*ports, *outputs])
    decls = [_decl("reg", p) for p in ports] + [_decl("wire", o) for o in outputs]
    conns = ", ".join(f".{s.name}({s.name})" for s in [*ports, *outputs])
    init = " ".join(f"{p.name} = 0;" for p in ports)
    body = [_cycle_lines(c, row, clock, data, outputs) for c, row in enumerate(vf.rows)]
    lines = [
        f"{HEADER_TAG}{header}",
        "`timescale 1ns/1ps",
        f"module {_TB_MODULE};",
        *decls,
        f"  {module} u_dut({conns});",
        "  initial begin",
        f"    {init}" if init else "    // no ports",
        *body,
        "    $finish;",
        "  end",
        "endmodule",
    ]
    return "\n".join(lines) + "\n"


def header_of(tb_text: str, cycles: int, seed: int = 0) -> str:
    """The vector-file header comment stored in a Wyrd testbench, else a generated one."""
    for line in tb_text.splitlines():
        if line.startswith(HEADER_TAG):
            return line[len(HEADER_TAG) :]
    return f"# wyrd-tb seed {seed} cycles {cycles}"


def _vector_line(line: str, expected: int, data_bits: int, out_bits: int) -> tuple[str, str] | None:
    """(input bits, output bits) of a printed vector line, None when it is not one."""
    words = line.split()
    if not words or words[0] != str(expected) or len(words) not in (2, 3):
        return None
    ins = words[1]
    outs = words[2] if len(words) == 3 else ""
    if ins != "-" and not (_BITS.match(ins) and len(ins) == data_bits):
        return None
    if ins == "-" and data_bits != 0:
        return None
    if len(outs) != out_bits or (outs and not _BITS.match(outs)):
        return None
    return ins, outs


def testbench_to_vectors(
    output: str,
    ports: Sequence[Signal],
    outputs: Sequence[Signal],
    header: str,
) -> str:
    """The vector file for the `$display` text of a Wyrd-format testbench run."""
    data = data_ports(ports)
    data_bits = sum(p.width for p in data)
    out_bits = sum(o.width for o in outputs)
    rows: list[str] = []
    for line in output.splitlines():
        got = _vector_line(line, len(rows), data_bits, out_bits)
        if got is not None:
            rows.append(f"{len(rows)} {got[0]}" + (f" {got[1]}" if outputs else ""))
    if not rows:
        raise ConvertError(
            "no vector lines in the testbench output; Wyrd reads lines of "
            "`<cycle> <input bits> <output bits>` (the format its own testbenches print)"
        )
    head = [header, *port_lines(ports, outputs)]
    return "\n".join([*head, *rows]) + "\n"


_MODULE = re.compile(r"\bmodule\s+([A-Za-z_]\w*)")
_COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)


def _instantiated(name: str, text: str) -> bool:
    pattern = re.compile(rf"\b{name}\s+(#\s*\(.*?\)\s*)?\w+\s*\(", re.DOTALL)
    return any(not text[: m.start()].rstrip().endswith("module") for m in pattern.finditer(text))


def detect_top(files: Sequence[Path]) -> str:
    """The one module no other module in `files` instantiates (spec default D-7)."""
    text = "\n".join(_COMMENTS.sub("", Path(f).read_text(encoding="utf-8")) for f in files)
    names: list[str] = list(dict.fromkeys(_MODULE.findall(text)))
    if not names:
        raise ConvertError("no module found in the DUT files")
    free = [n for n in names if not _instantiated(n, text)]
    if len(free) != 1:
        raise ConvertError(f"cannot tell the DUT top ({', '.join(free or names)}); give --dut-top")
    return free[0]
