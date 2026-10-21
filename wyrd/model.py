"""Data types shared by the project loader, the store, the steps and the scheduler (W1 plan)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Design:
    """A design: its name, its source files (absolute, sorted) and its top module, if given."""

    name: str
    files: tuple[Path, ...]
    top: str | None = None


@dataclass(frozen=True)
class StepSpec:
    """One step of a recipe: the step type (``use``) and its arguments from the project file."""

    use: str
    args: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Recipe:
    """A named, ordered list of steps."""

    name: str
    steps: tuple[StepSpec, ...]


@dataclass(frozen=True)
class RunSpec:
    """One run of the sweep: a design on an arch through a recipe, with its sweep parameters."""

    design: Design
    arch: str
    recipe: Recipe
    params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Metric:
    """One measured value of a step, as reported by the tool."""

    name: str
    value: float
    unit: str = ""
