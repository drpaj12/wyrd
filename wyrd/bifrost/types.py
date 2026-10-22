"""Plain data types of the simulation session (spec 5.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["input", "clock", "output", "internal"]


@dataclass(frozen=True)
class Signal:
    name: str
    width: int
    kind: Kind
    msb: int = 0
    lsb: int = 0


@dataclass(frozen=True)
class Diagnostic:
    severity: Literal["error", "warning"]
    message: str
    file: str | None
    line: int | None
    col: int | None
    raw: str
