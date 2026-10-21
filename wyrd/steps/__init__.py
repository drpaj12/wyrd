"""Steps turn a run into commands and read their outputs."""

from __future__ import annotations

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


def _need_vtr_root(settings: Settings) -> Path:
    if settings.vtr_root is None:
        raise ValueError("vtr_root is not set (machine.toml [tools] or VTR_ROOT)")
    return settings.vtr_root


def arch_xml(settings: Settings, arch: str) -> Path:
    return _need_vtr_root(settings) / "vtr_flow" / "arch" / "timing" / f"{arch}.xml"


def tool_path(settings: Settings, name: str) -> str:
    if name == "vpr":
        return str(_need_vtr_root(settings) / "vpr" / "vpr")
    if name == "abc":
        return str(_need_vtr_root(settings) / "build" / "abc" / "abc")
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


def get_step(spec: StepSpec) -> Step:
    from wyrd.steps.command import CommandStep
    from wyrd.steps.flow import FlowStep

    if spec.use == "odin3-flow":
        return FlowStep(spec.args)
    if spec.use in _COMMAND_STEPS:
        raw = spec.args.get("argv")
        argv = [str(w) for w in raw] if isinstance(raw, list) else None
        return CommandStep(spec.use, argv)
    for ep in entry_points(group="wyrd.steps"):
        if ep.name == spec.use:
            step: Step = ep.load()(spec)
            return step
    raise KeyError(spec.use)
