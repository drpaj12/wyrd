"""Light controllers: the seam between the game engine and Verilog (spec 6)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from wyrd.bifrost import (
    Backend,
    BifrostSession,
    CompileError,
    Diagnostic,
    Recording,
    Signal,
    SimError,
    SimUnavailable,
    default_backend,
    write_vcd,
)

# Re-exported so the Qt-free editor logic (vedit.py) needs no wyrd.bifrost import of its own.
__all__ = ["Backend", "SimError"]


class LightController(Protocol):
    last_inputs: tuple[int, int] | None
    last_outputs: tuple[int, int, int, int] | None

    def start(self) -> None: ...

    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]: ...

    def close(self) -> None: ...

    def start_recording(self) -> None: ...

    def stop_recording(self) -> None: ...

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

    def stop_recording(self) -> None:
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


class ControllerError(Exception):
    """A runtime problem in a player's module; the level pauses."""


_REQUIRED: tuple[tuple[str, str, int], ...] = (
    ("rst", "input", 1),
    ("sensor_light", "input", 8),
    ("general_sensors", "input", 30),
    ("outN", "output", 3),
    ("outS", "output", 3),
    ("outE", "output", 3),
    ("outW", "output", 3),
)


def _port_message(sig: Signal | None, name: str, kind: str, width: int) -> str | None:
    if sig is None:
        return f"port '{name}' is missing"
    if sig.kind != kind or sig.width != width:
        return (
            f"port '{name}' must be an {kind} of width {width}, "
            f"found {sig.kind} of width {sig.width}"
        )
    return None


def check_ports(session: BifrostSession) -> list[str]:
    by_name = {s.name: s for s in session.signals}
    messages: list[str] = []
    clk = by_name.get("clk")
    if clk is None or clk.kind not in ("input", "clock"):
        messages.append("port 'clk' is missing")
    for name, kind, width in _REQUIRED:
        msg = _port_message(by_name.get(name), name, kind, width)
        if msg is not None:
            messages.append(msg)
    return messages


class MidgardController:
    """One intersection: a Bifrost III session driven one clock edge per game tick (spec 7)."""

    def __init__(self, session: BifrostSession, name: str = "") -> None:
        self.session = session
        self.name = name
        self.last_inputs: tuple[int, int] | None = None
        self.last_outputs: tuple[int, int, int, int] | None = None
        self.warnings: list[str] = []
        self._set_light = 0
        self._set_general = 0
        self._warned: set[int] = set()

    def start(self) -> None:
        s = self.session
        try:
            s.reset()
            s.set("sensor_light", 0)
            s.set("general_sensors", 0)
            s.step(1)
            s.set("rst", 1)
        except SimError as exc:
            raise ControllerError(f"cannot start {self.name}: {exc}") from exc
        self._set_light = self._set_general = 0
        self.last_inputs = None
        self.last_outputs = None

    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]:
        s = self.session
        try:
            if light_sensors != self._set_light:
                s.set("sensor_light", light_sensors)
                self._set_light = light_sensors
            if general_sensors != self._set_general:
                s.set("general_sensors", general_sensors)
                self._set_general = general_sensors
            s.step(1)
            n, so, e, w = (s.get(p) for p in ("outN", "outS", "outE", "outW"))
        except SimError as exc:
            raise ControllerError(f"runtime error in {self.name}: {exc}") from exc
        outs = (n, so, e, w)
        self._note_codes(outs)
        self.last_inputs = (light_sensors, general_sensors)
        self.last_outputs = outs
        return outs

    def _note_codes(self, outs: tuple[int, int, int, int]) -> None:
        for code in outs:
            if code > 4 and code not in self._warned:
                self._warned.add(code)
                self.warnings.append(f"{self.name}: output code {code} treated as STOP")

    def close(self) -> None:
        self.session.close()

    def read_debug(self) -> int:
        if not self.session.has_signal("debug_port"):
            return 0
        return self.session.get("debug_port")

    def start_recording(self) -> None:
        self.session.start_recording()

    def stop_recording(self) -> None:
        self.session.stop_recording()

    def recording(self) -> Recording | None:
        return self.session.recording

    def export_vcd(self, path: Path) -> None:
        rec = self.session.recording
        if rec is None:
            raise ControllerError("nothing recorded")
        write_vcd(rec, path, top=self.name or "light")


@dataclass(frozen=True)
class PlayerError:
    index: int
    file: Path
    line: int | None
    col: int | None
    message: str

    def __str__(self) -> str:
        where = str(self.file)
        if self.line is not None:
            where += f":{self.line}"
            if self.col is not None:
                where += f":{self.col}"
        return f"{where}: {self.message}"


@dataclass
class BuildResult:
    controllers: list[LightController | None]
    errors: list[PlayerError]
    warnings: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _first_error(exc: CompileError) -> tuple[int | None, int | None, str]:
    for d in exc.diagnostics:
        if d.severity == "error":
            return d.line, d.col, d.message
    return None, None, str(exc)


def _build_one(
    index: int, path: Path, backend: Backend, result: BuildResult
) -> LightController | None:
    try:
        session = BifrostSession.from_verilog([path], backend=backend)
    except CompileError as exc:
        line, col, msg = _first_error(exc)
        result.errors.append(PlayerError(index, path, line, col, msg))
        return None
    except SimUnavailable:
        raise
    except (SimError, OSError):
        result.errors.append(PlayerError(index, path, None, None, "cannot read file"))
        return None
    problems = check_ports(session)
    if problems:
        session.close()
        result.errors.extend(PlayerError(index, path, None, None, m) for m in problems)
        return None
    result.warnings.extend(d for d in session.diagnostics if d.severity == "warning")
    return MidgardController(session, path.name)


def build_controllers(paths: Sequence[Path], backend: Backend | None = None) -> BuildResult:
    be = backend if backend is not None else default_backend()
    result = BuildResult([], [])
    for index, path in enumerate(paths):
        result.controllers.append(_build_one(index, path, be, result))
    return result
