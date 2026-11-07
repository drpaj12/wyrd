"""Simulations that produce activity: iverilog (RTL and gate level) and Odin III replay."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wyrd.bifrost.power.vcdact import NetAct, read_activity_file, sample_rising

PASS_BAD = re.compile(r"\bFAIL\b|ERROR:")
SEQ_UDP = re.compile(
    r"primitive\s+sky130_fd_sc_hd__udp_d(?:ff|latch)\S*\s*\(.*?\breg\s+Q\s*;", re.S
)


class PowerError(Exception):
    """A step of the power flow failed; the message says which and why."""


@dataclass
class SimResult:
    passed: bool
    log: str
    acts: dict[str, NetAct] = field(default_factory=dict)
    cycles: int = 0
    start_state: str = "x"


def run(
    argv: Sequence[str], cwd: Path, env: dict[str, str] | None = None, timeout: int = 7200
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(argv),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def dump_module(vcd: Path, tb_top: str, inst: str, clock: str) -> str:
    """A module that dumps the DUT instance and the testbench clock (not the whole testbench)."""
    body = f'$dumpfile("{vcd}"); $dumpvars(0, {tb_top}.{inst}); $dumpvars(0, {tb_top}.{clock});'
    return f"module wyrd_dump; initial begin {body} end endmodule\n"


def compile_tb(
    sources: Sequence[Path],
    tb_top: str,
    work: Path,
    vcd: Path,
    inst: str,
    clock: str,
    defines: Sequence[str],
    incdirs: Sequence[Path],
    extra: Sequence[str],
) -> Path:
    work.mkdir(parents=True, exist_ok=True)
    dump = work / "wyrd_dump.v"
    dump.write_text(dump_module(vcd, tb_top, inst, clock))
    vvp = work / "sim.vvp"
    cmd = ["iverilog", "-g2005", *extra, "-s", tb_top, "-s", "wyrd_dump", "-o", str(vvp)]
    cmd += [f"-D{d}" for d in defines] + [f"-I{i}" for i in incdirs]
    cmd += [str(dump)] + [str(s) for s in sources]
    comp = run(cmd, work)
    if comp.returncode != 0:
        raise PowerError(f"iverilog failed: {comp.stderr.strip()[:400]}")
    return vvp


@dataclass(frozen=True)
class TbRun:
    """One testbench run: what to simulate and where the DUT and its clock are."""

    sources: Sequence[Path]
    tb_top: str
    inst: str
    clock: str
    strip: str  # prefix removed from the net names of the result (``tb.dut.``)
    data: Sequence[Path] = ()  # files the testbench reads from its working directory
    defines: Sequence[str] = ()
    incdirs: Sequence[Path] = ()
    pass_text: str = "PASS"
    extra: Sequence[str] = ()


def activity_run(tb: TbRun, work: Path, timeout: int = 14400) -> SimResult:
    """Run a testbench; the VCD goes through a named pipe and is reduced to activity on the fly,
    so a long run never writes a large file. Names have ``tb.strip`` removed."""
    vcd = work / "act.fifo"
    vvp = compile_tb(
        tb.sources, tb.tb_top, work, vcd, tb.inst, tb.clock, tb.defines, tb.incdirs, tb.extra
    )
    for d in tb.data:
        shutil.copy(d, work / d.name)
    if vcd.exists():
        vcd.unlink()
    os.mkfifo(vcd)
    log = work / "sim.log"
    with log.open("w") as out:
        proc = subprocess.Popen(
            ["vvp", "-n", str(vvp)],
            cwd=work,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        clk = f"{tb.tb_top}.{tb.clock}"
        try:
            acts = read_activity_file(vcd, clk)
        except ValueError:
            acts = {}
        proc.wait(timeout=timeout)
    vcd.unlink()
    text = log.read_text(errors="replace")
    ok = proc.returncode == 0 and tb.pass_text in text and PASS_BAD.search(text) is None
    res = SimResult(ok, text)
    if ok and clk in acts:
        res.cycles = acts[clk].toggles // 2
        res.acts = {k[len(tb.strip) :]: v for k, v in acts.items() if k.startswith(tb.strip)}
    return res


def patch_primitives(text: str, init: str) -> str:
    """The sky130 flip-flop and latch UDPs starting at ``init`` (0 or 1) instead of x."""
    return SEQ_UDP.sub(lambda m: f"{m.group(0)}\n    initial Q = 1'b{init};", text)


def vectors_from_tb_vcd(
    vcd: Path, tb_top: str, inst: str, clock_port: str, ports: Sequence[tuple[str, int]]
) -> list[dict[str, int]]:
    """Rows of DUT input values before each rising edge of the DUT clock port (sim_tb --vcd)."""
    prefix = f"{tb_top}.{inst}."
    signals = {prefix + n: w for n, w in ports}
    with vcd.open(errors="replace") as f:
        return sample_rising(f, prefix + clock_port, signals)
