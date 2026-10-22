"""Light controllers: the seam between the game engine and Verilog (spec 6)."""

from __future__ import annotations

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
