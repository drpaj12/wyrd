"""Steps turn a run into commands and read their outputs."""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Iterable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol

from wyrd.model import Metric, RunSpec, StepSpec
from wyrd.settings import Settings


class Step(Protocol):
    name: str
    tools: tuple[str, ...]
    is_vpr: bool

    def command(
        self, run: RunSpec, step_dir: Path, settings: Settings
    ) -> tuple[list[str], dict[str, str]]: ...

    def collect(self, step_dir: Path) -> list[Metric]: ...


_COMMAND_STEPS = ("odin3", "vpr", "abc", "shell")


def need_vtr_root(settings: Settings) -> Path:
    if settings.vtr_root is None:
        raise ValueError("vtr_root is not set (machine.toml [tools] or VTR_ROOT)")
    return settings.vtr_root


def arch_xml(settings: Settings, arch: str) -> Path:
    return need_vtr_root(settings) / "vtr_flow" / "arch" / "timing" / f"{arch}.xml"


def tool_path(settings: Settings, name: str) -> str:
    if name == "vpr":
        return str(need_vtr_root(settings) / "vpr" / "vpr")
    if name == "abc":
        return str(need_vtr_root(settings) / "build" / "abc" / "abc")
    return settings.tools[name]


def tool_versions(settings: Settings, names: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        try:
            proc = subprocess.run(
                [tool_path(settings, name), "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            out[name] = proc.stdout.strip() or "unknown"
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            out[name] = "unknown"
    return out


def read_json_object(path: Path) -> dict[str, object] | None:
    """Return the JSON object in `path`; None if the file is missing or holds no object."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"{path}: malformed JSON: {exc}") from exc
    return data if isinstance(data, dict) else None


def finite_number(value: object) -> float | None:
    """Return `value` as a finite float, or None for non-numbers, bools, nan, inf, overflow."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        out = float(value)
    except OverflowError:
        return None
    return out if math.isfinite(out) else None


def get_step(spec: StepSpec) -> Step:
    from wyrd.steps.command import CommandStep
    from wyrd.steps.flow import FlowStep

    if spec.use == "odin3-flow":
        return FlowStep(spec.args)
    if spec.use in _COMMAND_STEPS:
        raw = spec.args.get("argv")
        if not isinstance(raw, list) or not all(isinstance(w, str) for w in raw):
            raise ValueError(f"step {spec.use!r}: args.argv must be a list of strings")
        return CommandStep(spec.use, [str(w) for w in raw])
    for ep in entry_points(group="wyrd.steps"):
        if ep.name == spec.use:
            step: Step = ep.load()(spec)
            return step
    raise KeyError(spec.use)
