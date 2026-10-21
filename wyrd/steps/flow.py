"""The odin3-flow step: one command, metrics from out/summary.json."""

from __future__ import annotations

from pathlib import Path

from wyrd.model import Metric, RunSpec
from wyrd.settings import Settings
from wyrd.steps import arch_xml, finite_number, need_vtr_root, read_json_object, tool_path


class FlowStep:
    name = "odin3-flow"

    def __init__(self, args: dict[str, object] | None = None) -> None:
        self.args = args or {}
        vpr = self.args.get("vpr", True)
        if not isinstance(vpr, bool):
            raise ValueError(f"step 'odin3-flow': args.vpr must be true or false, got {vpr!r}")
        self.is_vpr = vpr
        self.tools: tuple[str, ...] = ("odin3_flow", "odin3") + (("vpr",) if self.is_vpr else ())

    def command(
        self, run: RunSpec, step_dir: Path, settings: Settings
    ) -> tuple[list[str], dict[str, str]]:
        argv = [tool_path(settings, "odin3_flow"), *[str(f) for f in run.design.files]]
        if run.design.top:
            argv += ["--top", run.design.top]
        argv += ["--target", str(self.args.get("target", "vtr"))]
        argv += ["--arch", str(arch_xml(settings, run.arch))]
        argv.append("--vpr" if self.is_vpr else "--no-vpr")
        argv += ["--out", str(step_dir / "out")]
        return argv, {"VTR_ROOT": str(need_vtr_root(settings))}

    def collect(self, step_dir: Path) -> list[Metric]:
        data = read_json_object(step_dir / "out" / "summary.json")
        return _flatten(data, "") if data is not None else []


def _unit(name: str) -> str:
    if name.startswith("seconds."):
        return "s"
    return "ns" if name == "crit_path_ns" else ""


def _flatten(data: dict[str, object], prefix: str) -> list[Metric]:
    out: list[Metric] = []
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.extend(_flatten(value, f"{name}."))
        else:
            number = finite_number(value)
            if number is not None:
                out.append(Metric(name, number, _unit(name)))
    return out
