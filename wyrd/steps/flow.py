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
        self.timing_paths = _timing_paths(self.args)
        self.timing_attr = _flag(self.args, "timing_attr") or self.timing_paths is not None
        if self.timing_attr and not (self.is_vpr and self.args.get("target", "vtr") == "vtr"):
            raise ValueError("step 'odin3-flow': timing_attr needs target = \"vtr\" and vpr = true")
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
        if self.timing_attr:
            argv.append("--timing-attr")
        if self.timing_paths is not None:
            argv += ["--timing-paths", str(self.timing_paths)]
        argv += ["--out", str(step_dir / "out")]
        return argv, {"VTR_ROOT": str(need_vtr_root(settings))}

    def collect(self, step_dir: Path) -> list[Metric]:
        data = read_json_object(step_dir / "out" / "summary.json")
        metrics = _flatten(data, "") if data is not None else []
        return metrics + timing_metrics(step_dir) if self.timing_attr else metrics


def attribution_path(step_dir: Path) -> Path:
    """Where `odin3-flow --timing-attr` leaves attribution.json for the step in `step_dir`."""
    return step_dir / "out" / "timing" / "attribution.json"


def timing_metrics(step_dir: Path) -> list[Metric]:
    """Fmax and CPD from attribution.json; `timing.attributed` is 1 when the file is usable."""
    data = read_json_object(attribution_path(step_dir))
    timing = data.get("timing") if data is not None else None
    if not isinstance(timing, dict) or data is None or data.get("schema_version") != 1:
        return [Metric("timing.attributed", 0.0)]
    out = [Metric("timing.attributed", 1.0)]
    for key, unit in (("fmax_mhz", "MHz"), ("cpd_ns", "ns")):
        number = finite_number(timing.get(key))
        if number is not None:
            out.append(Metric(f"timing.{key}", number, unit))
    return out


def _flag(args: dict[str, object], key: str) -> bool:
    value = args.get(key, False)
    if not isinstance(value, bool):
        raise ValueError(f"step 'odin3-flow': args.{key} must be true or false, got {value!r}")
    return value


def _timing_paths(args: dict[str, object]) -> int | None:
    value = args.get("timing_paths")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(
            f"step 'odin3-flow': args.timing_paths must be a positive integer, got {value!r}"
        )
    return value


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
