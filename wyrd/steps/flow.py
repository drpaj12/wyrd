"""The odin3-flow step: one command, metrics from out/summary.json."""

from __future__ import annotations

import json
from pathlib import Path

from wyrd.model import Metric, RunSpec
from wyrd.settings import Settings
from wyrd.steps import arch_xml, tool_path


class FlowStep:
    name = "odin3-flow"

    def __init__(self, args: dict[str, object] | None = None) -> None:
        self.args = args or {}
        self.is_vpr = bool(self.args.get("vpr", True))
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
        return argv, {"VTR_ROOT": str(settings.vtr_root)}

    def collect(self, step_dir: Path) -> list[Metric]:
        path = step_dir / "out" / "summary.json"
        if not path.is_file():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return _flatten(data, "") if isinstance(data, dict) else []


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
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out.append(Metric(name, float(value), _unit(name)))
    return out
