"""Plan the VPR floorplan viewer command for a finished run (spec section 11)."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from wyrd.guimodel.runs import step_dirs

_ECHO = re.compile(r"^(?P<vpr>\S*/vpr)\s+(?P<arch>\S+\.xml)\s+(?P<circuit>\S+)\s+(?P<opts>.*)$")
_VPR_LOG = Path("out") / "vpr" / "run" / "vpr_stdout.log"
_VIEW = ("--disp", "on", "--graphics_pause", "final_stage")


@dataclass(frozen=True)
class FloorplanPlan:
    program: str
    args: tuple[str, ...]
    cwd: Path
    mode: str  # "replay" or "rerun"


@dataclass(frozen=True)
class _Echo:
    vpr: str
    circuit: str
    opts: list[str]


def _last_echo(log: Path) -> _Echo | None:
    found: re.Match[str] | None = None
    try:
        with log.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _ECHO.match(line.rstrip("\r\n"))
                if m:
                    found = m
    except OSError:
        return None
    if found is None:
        return None
    return _Echo(found.group("vpr"), found.group("circuit"), _split(found.group("opts")))


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()


def _option(opts: list[str], name: str) -> str | None:
    for i, tok in enumerate(opts[:-1]):
        if tok == name:
            return opts[i + 1]
    return None


def _arch_from_cmd(cmd_sh: Path) -> str | None:
    try:
        lines = cmd_sh.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if "--arch" in line:
            return _option(_split(line), "--arch")
    return None


def _args(arch: str, echo: _Echo, blif: Path, width: str) -> tuple[tuple[str, ...], str]:
    head = (arch, echo.circuit, "--circuit_file", str(blif))
    files = [blif.parent / f"{echo.circuit}.{ext}" for ext in ("net", "place", "route")]
    if all(f.is_file() for f in files):
        net, place, route = (str(f) for f in files)
        replay = ("--net_file", net, "--place_file", place, "--route_file", route)
        tail = ("--route", "--analysis", "--route_chan_width", width)
        return (*head, *replay, *tail, *_VIEW), "replay"
    iters = _option(echo.opts, "--max_router_iterations")
    limit: tuple[str, ...] = ("--max_router_iterations", iters) if iters else ()
    stages = ("--pack", "--place", "--route", "--route_chan_width", width)
    return (*head, *limit, *stages, *_VIEW), "rerun"


def plan_floorplan(run_dir: Path, vpr_gui: Path | None = None) -> FloorplanPlan | str:
    """The VPR command that shows the run's floorplan, or the reason it cannot be built.

    Pure: no directory is created. ``cwd`` is ``run_dir/floorplan``. ``vpr_gui`` (the
    ``tools.vpr_gui`` setting), when set, replaces the VPR named in the log.
    """
    step = next((s for s in step_dirs(run_dir) if (s.path / _VPR_LOG).is_file()), None)
    if step is None:
        return "no VPR log in this run"
    log = step.path / _VPR_LOG
    echo = _last_echo(log)
    if echo is None:
        return "no VPR command line in vpr_stdout.log"
    arch = _arch_from_cmd(step.path / "cmd.sh")
    if arch is None:
        return "arch path not found in cmd.sh"
    width = _option(echo.opts, "--route_chan_width")
    if width is None:
        return "no --route_chan_width in the VPR command"
    if vpr_gui is not None:
        if not vpr_gui.is_file():
            return f"graphics VPR (tools.vpr_gui) not found: {vpr_gui}"
    elif not Path(echo.vpr).is_file():
        return f"VPR binary not found: {echo.vpr}"
    program = str(vpr_gui) if vpr_gui is not None else echo.vpr
    blif = log.parent / (_option(echo.opts, "--circuit_file") or echo.circuit)
    if not blif.is_file():
        return f"circuit file not found: {blif}"
    args, mode = _args(arch, echo, blif, width)
    return FloorplanPlan(program, args, run_dir / "floorplan", mode)
