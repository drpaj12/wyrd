"""Shared builders for scheduler and preflight tests."""

import dataclasses
from pathlib import Path
from typing import Any
from unittest import mock

from wyrd import settings
from wyrd.model import Design, Recipe, RunSpec, StepSpec
from wyrd.project import Project

SLEEPY = str(Path(__file__).parent / "fakes" / "sleepy")
GB = 2**30
MB = 2**20


def make_settings(**changes: Any) -> settings.Settings:
    with mock.patch.dict("os.environ", {"WYRD_CONFIG": "/nonexistent/m.toml"}):
        base = settings.load(None, {})
    plain = dataclasses.replace(base, launcher="plain", jobs=1, mem_budget=8 * GB, vtr_root=None)
    return dataclasses.replace(plain, **changes)


def shell(*argv: str) -> StepSpec:
    return StepSpec("shell", {"argv": list(argv)})


def sleepy(seconds: float = 0, mb: int = 0, code: int = 0) -> StepSpec:
    return shell(SLEEPY, str(seconds), str(mb), str(code))


def make_project(
    root: Path, designs: dict[str, int], steps: list[StepSpec], arch: str = ""
) -> Project:
    """One run per design (name to size in bytes), all through one recipe (no arch)."""
    recipe = Recipe("r", tuple(steps))
    made: dict[str, Design] = {}
    runs: list[RunSpec] = []
    for name, size in designs.items():
        src = root / "src" / f"{name}.v"
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text("x" * size, encoding="utf-8")
        made[name] = Design(name, (src,), None)
        runs.append(RunSpec(made[name], arch, recipe))
    return Project(root, "p", made, {"r": recipe}, {}, tuple(runs))
