"""File-level testbench conversions and the derived VCD (spec 2026-10-31 sections 2 and 3)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from wyrd.bifrost.backend import Backend, ScriptRunner
from wyrd.bifrost.session import BifrostSession
from wyrd.bifrost.tbconvert import (
    ConvertError,
    detect_top,
    header_of,
    testbench_to_vectors,
    vectors_to_testbench,
)
from wyrd.bifrost.testbench import TbSpec, run_testbench_file
from wyrd.bifrost.vcd import write_vcd
from wyrd.bifrost.vectors import parse_vectors, session_ports

_PORT_KINDS = (["input"], ["clock"], ["output"])


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConvertError(f"{path}: cannot read: {e}") from e


def _header_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#") and line.split()[1:2] not in _PORT_KINDS:
            return line
    return "# wyrd seed 0 cycles 0"


def vectors_file_to_testbench(
    dut: Sequence[Path],
    vectors: Path,
    out: Path,
    *,
    top: str | None = None,
    backend: Backend | None = None,
) -> int:
    """Write the testbench for a vector file; returns the cycle count."""
    module = top if top is not None else detect_top(dut)
    text = _read(vectors)
    with BifrostSession.from_verilog(list(dut), top=top, backend=backend) as session:
        ports, outputs = session_ports(session)
        vf = parse_vectors(text, ports, outputs, str(vectors))
    out.write_text(vectors_to_testbench(module, ports, outputs, vf, _header_line(text)), "utf-8")
    return len(vf.rows)


def _run_text(dut: Sequence[Path], tb: Path, top: str | None, runner: ScriptRunner | None) -> str:
    result = run_testbench_file(TbSpec(tb, dut, dut_top=top), runner=runner)
    if result.output is None:
        raise ConvertError(result.error or f"{tb}: the testbench did not run")
    return result.output


def testbench_file_to_vectors(
    dut: Sequence[Path],
    tb: Path,
    out: Path,
    *,
    top: str | None = None,
    backend: Backend | None = None,
    runner: ScriptRunner | None = None,
) -> int:
    """Run `tb` against the DUT on Odin III and write what it printed as a vector file."""
    text = _run_text(dut, tb, top, runner)
    with BifrostSession.from_verilog(list(dut), top=top, backend=backend) as session:
        ports, outputs = session_ports(session)
    vectors = testbench_to_vectors(text, ports, outputs, header_of(_read(tb), 0))
    out.write_text(vectors, "utf-8")
    return sum(1 for line in vectors.splitlines() if not line.startswith("#"))


def testbench_file_to_vcd(
    dut: Sequence[Path],
    output: str,
    out: Path,
    *,
    top: str | None = None,
    backend: Backend | None = None,
) -> None:
    """Replay the input columns of a testbench's printed vector lines and write a VCD."""
    with BifrostSession.from_verilog(list(dut), top=top, backend=backend) as session:
        ports, outputs = session_ports(session)
        vectors = testbench_to_vectors(output, ports, outputs, "# wyrd-tb")
        vf = parse_vectors(vectors, ports, outputs, "<testbench output>")
        write_vcd(session.run_vectors(vf), out)
