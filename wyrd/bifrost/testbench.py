"""Run Verilog testbenches through Odin III (run_testbenches, sim_tb); spec section 2."""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from wyrd.bifrost.backend import ScriptRunner, default_runner
from wyrd.bifrost.errors import SimError

Status = Literal["pass", "fail", "error", "timeout"]
On = Literal["rtl", "netlist", "both"]
ON_VALUES: tuple[str, ...] = ("rtl", "netlist", "both")
_PREP = "read_verilog; proc; opt; lower"
_NETLIST = "abc --lut 6"
_BAD_CHARS = re.compile(r'[\s";]')
_NETLIST_LINE = re.compile(r"^\s*testbench\s+\S+.*\bon\s+(netlist|both)\b", re.MULTILINE)


class TbError(SimError):
    """Odin III produced no result (a script error, a missing project, a bad option)."""


@dataclass(frozen=True)
class TbMismatch:
    compared: str
    line: int
    time: int | None
    field: int
    want: str
    got: str


@dataclass(frozen=True)
class TbResult:
    name: str
    status: Status
    on: str
    wall_ms: int
    end_time: int
    lines: int
    mismatch: TbMismatch | None
    timeout: bool
    error: str | None
    output: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "pass"


@dataclass(frozen=True)
class TbReport:
    results: tuple[TbResult, ...]

    def count(self, status: Status) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def to_json(self) -> str:
        rows = [
            {
                "name": r.name,
                "status": "fail" if r.status == "timeout" else r.status,
                "on": r.on,
                "wall_ms": r.wall_ms,
                "end_time": r.end_time,
                "lines": r.lines,
                "timeout": r.timeout,
                "mismatch": None if r.mismatch is None else vars(r.mismatch),
                "error": r.error,
            }
            for r in self.results
        ]
        counts = {s: self.count(s) for s in ("pass", "fail", "error", "timeout")}
        return json.dumps({"testbenches": rows, **counts}, indent=2) + "\n"


def _mismatch(raw: dict[str, Any] | None) -> TbMismatch | None:
    if raw is None:
        return None
    time = raw.get("time")
    return TbMismatch(
        str(raw["compared"]),
        int(raw["line"]),
        None if time is None else int(time),
        int(raw["field"]),
        str(raw["want"]),
        str(raw["got"]),
    )


def _status(raw: dict[str, Any]) -> Status:
    status = str(raw["status"])
    if status == "pass":
        return "pass"
    if status == "fail":
        return "timeout" if raw.get("timeout") else "fail"
    if status == "error":
        return "error"
    raise TbError(f"unknown testbench status `{status}`")


def _result(raw: dict[str, Any]) -> TbResult:
    return TbResult(
        str(raw["name"]),
        _status(raw),
        str(raw["on"]),
        int(raw["wall_ms"]),
        int(raw["end_time"]),
        int(raw["lines"]),
        _mismatch(raw.get("mismatch")),
        bool(raw.get("timeout", False)),
        None if raw.get("error") is None else str(raw["error"]),
    )


def parse_report(text: str) -> TbReport:
    """Read the `run_testbenches --json` records."""
    try:
        data = json.loads(text)
        return TbReport(tuple(_result(r) for r in data["testbenches"]))
    except (ValueError, KeyError, TypeError) as e:
        raise TbError(f"cannot read the run_testbenches result: {e}") from e


def _check_path(p: Path) -> str:
    text = str(p.resolve())
    if _BAD_CHARS.search(text):
        raise TbError(f'{p}: a path with whitespace, `"` or `;` is not supported')
    return text


def _needs_netlist(project: Path, only: str | None) -> bool:
    try:
        text = project.read_text(encoding="utf-8")
    except OSError as e:
        raise TbError(f"{project}: cannot read: {e}") from e
    if only is None:
        return _NETLIST_LINE.search(text) is not None
    return any(
        re.match(rf"\s*testbench\s+{re.escape(only)}\s", line) and _NETLIST_LINE.match(line)
        for line in text.splitlines()
    )


def run_project_testbenches(
    project: str | Path,
    *,
    only: str | None = None,
    seed: int = 0,
    runner: ScriptRunner | None = None,
) -> TbReport:
    """Run the testbenches of an `.o3proj` (or a qsf-imported project); one result each."""
    path = Path(project)
    proj = _check_path(path)
    run = runner if runner is not None else default_runner()
    with tempfile.TemporaryDirectory(prefix="wyrd-tb-") as tmp:
        out = Path(tmp) / "result.json"
        prep = f"read_project {proj}; {_PREP}"
        if _needs_netlist(path, only):
            prep += f"; {_NETLIST}"
        script = f"{prep}; run_testbenches --json {_check_path(out)} --seed {seed}"
        if only is not None:
            script += f" --only {only}"
        outcome = run.run(script)
        if not out.is_file():
            raise TbError(outcome.error or "run_testbenches wrote no result")
        return parse_report(out.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class TbSpec:
    """One testbench file with its DUT sources."""

    tb: Path
    dut: Sequence[Path]
    dut_top: str | None = None
    tb_top: str | None = None
    dut_inst: str | None = None
    max_time: int | None = None
    expect: Path | None = None
    on: On = "rtl"
    name: str = "tb"


def _project_text(spec: TbSpec) -> str:
    lines = [f"file verilog {_check_path(p)}" for p in spec.dut]
    if spec.dut_top:
        lines.append(f"top {spec.dut_top}")
    parts = [f"testbench {spec.name} file {_check_path(spec.tb)}"]
    for key, value in (("top", spec.tb_top), ("dut", spec.dut_inst), ("max-time", spec.max_time)):
        if value is not None:
            parts.append(f"{key} {value}")
    if spec.expect is not None:
        parts.append(f"expect {_check_path(spec.expect)}")
    parts.append(f"on {spec.on}")
    return "\n".join([*lines, " ".join(parts)]) + "\n"


def _capture_output(spec: TbSpec, proj: Path, work: Path, run: ScriptRunner) -> str | None:
    """The `$display` text of the testbench on the RTL (or, for `netlist`, the abc netlist)."""
    out = work / "output.txt"
    prep = f"read_project {_check_path(proj)}; {_PREP}"
    if spec.on == "netlist":
        prep += f"; {_NETLIST}"
    tb_top = f"--top {spec.tb_top} " if spec.tb_top else ""
    outcome = run.run(f"{prep}; sim_tb --out {_check_path(out)} {tb_top}{_check_path(spec.tb)}")
    if not outcome.ok or not out.is_file():
        return None
    return out.read_text(encoding="utf-8")


def run_testbench_file(
    spec: TbSpec, *, seed: int = 0, runner: ScriptRunner | None = None
) -> TbResult:
    """Run one testbench against DUT files. Output text captured with `sim_tb --out`."""
    if not spec.dut:
        raise TbError("no DUT Verilog files given")
    run = runner if runner is not None else default_runner()
    with tempfile.TemporaryDirectory(prefix="wyrd-tb-") as tmp:
        work = Path(tmp)
        proj = work / "wyrd.o3proj"
        proj.write_text(_project_text(spec), encoding="utf-8")
        report = run_project_testbenches(proj, seed=seed, runner=run)
        if len(report.results) != 1:
            raise TbError("expected one testbench result")
        text = _capture_output(spec, proj, work, run)
        return _with_output(report.results[0], text)


def _with_output(r: TbResult, text: str | None) -> TbResult:
    return TbResult(
        r.name, r.status, r.on, r.wall_ms, r.end_time, r.lines, r.mismatch, r.timeout, r.error, text
    )
