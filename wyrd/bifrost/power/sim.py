"""Simulations that produce activity: iverilog (RTL and gate level) and Odin III replay."""

from __future__ import annotations

import re
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


def dump_module(vcd: Path, tb_top: str) -> str:
    body = f'$dumpfile("{vcd}"); $dumpvars(0, {tb_top});'
    return f"module wyrd_dump; initial begin {body} end endmodule\n"


def iverilog_run(
    sources: Sequence[Path],
    tb_top: str,
    work: Path,
    vcd: Path,
    defines: Sequence[str] = (),
    incdirs: Sequence[Path] = (),
    pass_text: str = "PASS",
    extra: Sequence[str] = (),
) -> SimResult:
    """Compile and run one testbench with a full dump of the testbench scope into ``vcd``."""
    work.mkdir(parents=True, exist_ok=True)
    dump = work / "wyrd_dump.v"
    dump.write_text(dump_module(vcd, tb_top))
    vvp = work / "sim.vvp"
    cmd = ["iverilog", "-g2005", *extra, "-s", tb_top, "-s", "wyrd_dump", "-o", str(vvp)]
    cmd += [f"-D{d}" for d in defines] + [f"-I{i}" for i in incdirs]
    cmd += [str(dump)] + [str(s) for s in sources]
    comp = run(cmd, work)
    if comp.returncode != 0:
        raise PowerError(f"iverilog failed: {comp.stderr.strip()[:400]}")
    sim = run(["vvp", "-n", str(vvp)], work)
    text = sim.stdout + sim.stderr
    ok = sim.returncode == 0 and pass_text in text and PASS_BAD.search(text) is None
    return SimResult(ok, text)


def patch_primitives(text: str, init: str) -> str:
    """The sky130 flip-flop and latch UDPs starting at ``init`` (0 or 1) instead of x."""
    return SEQ_UDP.sub(lambda m: f"{m.group(0)}\n    initial Q = 1'b{init};", text)


def activity_run(
    sources: Sequence[Path],
    tb_top: str,
    clock: str,
    prefix: str,
    work: Path,
    keep_vcd: bool = False,
    defines: Sequence[str] = (),
    incdirs: Sequence[Path] = (),
    pass_text: str = "PASS",
    extra: Sequence[str] = (),
) -> SimResult:
    """Run a testbench and read the activity of every net under ``prefix`` (e.g. ``tb.dut.``).

    Names in the result have the prefix removed. ``clock`` is the testbench clock net."""
    vcd = work / "act.vcd"
    res = iverilog_run(sources, tb_top, work, vcd, defines, incdirs, pass_text, extra)
    if not res.passed:
        return res
    acts = read_activity_file(vcd, f"{tb_top}.{clock}")
    res.cycles = acts[f"{tb_top}.{clock}"].toggles // 2
    res.acts = {k[len(prefix) :]: v for k, v in acts.items() if k.startswith(prefix)}
    if not keep_vcd:
        vcd.unlink()
    return res


def vectors_from_tb_vcd(
    vcd: Path, tb_top: str, inst: str, clock_port: str, ports: Sequence[tuple[str, int]]
) -> list[dict[str, int]]:
    """Rows of DUT input values before each rising edge of the DUT clock port (sim_tb --vcd)."""
    prefix = f"{tb_top}.{inst}."
    signals = {prefix + n: w for n, w in ports}
    with vcd.open(errors="replace") as f:
        return sample_rising(f, prefix + clock_port, signals)
