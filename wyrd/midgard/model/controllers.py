"""Light controllers: the seam between the game engine and Verilog (spec 6)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from wyrd.bifrost import Recording


class LightController(Protocol):
    last_inputs: tuple[int, int] | None
    last_outputs: tuple[int, int, int, int] | None

    def start(self) -> None: ...

    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]: ...

    def close(self) -> None: ...

    def start_recording(self) -> None: ...

    def recording(self) -> Recording | None: ...

    def export_vcd(self, path: Path) -> None: ...


class ScriptedController:
    """A controller backed by a Python function (tests, the safe-controller oracle)."""

    def __init__(self, fn: Callable[[int, int], tuple[int, int, int, int]]) -> None:
        self.fn = fn
        self.starts = 0
        self.last_inputs: tuple[int, int] | None = None
        self.last_outputs: tuple[int, int, int, int] | None = None

    def start(self) -> None:
        self.starts += 1

    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]:
        self.last_inputs = (light_sensors, general_sensors)
        self.last_outputs = self.fn(light_sensors, general_sensors)
        return self.last_outputs

    def close(self) -> None:
        return None

    def start_recording(self) -> None:
        return None

    def recording(self) -> Recording | None:
        return None

    def export_vcd(self, path: Path) -> None:
        raise RuntimeError("scripted controllers cannot record")


def safe_controller(light: int, general: int) -> tuple[int, int, int, int]:
    """The original stub: let one direction at a time through, nothing while the middle is busy."""
    if light & 0b1111:
        return (0, 0, 0, 0)
    if light & 0b01000000:
        return (4, 0, 0, 0)
    if light & 0b00010000:
        return (0, 4, 0, 0)
    if light & 0b00100000:
        return (0, 0, 4, 0)
    if light & 0b10000000:
        return (0, 0, 0, 4)
    return (4, 4, 4, 4)
