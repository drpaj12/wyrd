"""A Python fake of Bifrost's `Backend` for the Midgard III light modules."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from wyrd.bifrost.backend import Backend
from wyrd.bifrost.errors import CompileError, SimError
from wyrd.bifrost.types import Diagnostic, Signal
from wyrd.midgard.model.controllers import safe_controller

_OUTS = ("outN", "outS", "outE", "outW")


def _signals(flags: frozenset[str]) -> list[Signal]:
    light_width = 4 if "BAD_WIDTH" in flags else 8
    sigs = [
        Signal("clk", 1, "clock"),
        Signal("rst", 1, "input"),
        Signal("sensor_light", light_width, "input", light_width - 1, 0),
        Signal("general_sensors", 30, "input", 29, 0),
    ]
    outs = [n for n in _OUTS if not (n == "outW" and "MISSING_OUTW" in flags)]
    sigs += [Signal(n, 3, "output", 2, 0) for n in outs]
    sigs.append(Signal("debug_port", 30, "output", 29, 0))
    return sigs


class FakeLightHandle:
    def __init__(self, backend: FakeLightBackend, flags: frozenset[str]) -> None:
        self._backend = backend
        self._flags = flags
        self._sigs = {s.name: s for s in _signals(flags)}
        self.log: list[tuple[int, int, int]] = []
        self.set_calls: list[tuple[str, int]] = []
        self.closed = False
        self.reset()

    def reset(self) -> None:
        self.values = {n: 0 for n in self._sigs}
        self._cycle = 0

    def signals(self) -> Sequence[Signal]:
        return list(self._sigs.values())

    def signal(self, name: str) -> Signal | None:
        return self._sigs.get(name)

    def get(self, name: str) -> int:
        if name not in self._sigs:
            raise KeyError(name)
        return self.values[name]

    def set(self, name: str, value: int) -> None:
        sig = self._sigs.get(name)
        if sig is None:
            raise KeyError(name)
        if sig.kind != "input" or not 0 <= value < 2**sig.width:
            raise ValueError(f"{name}: bad value {value}")
        self.set_calls.append((name, value))
        self.values[name] = value

    def settle(self) -> None:
        return None

    def step(self, cycles: int) -> None:
        for _ in range(cycles):
            self._step_one()

    def _step_one(self) -> None:
        v = self.values
        self.log.append((v["rst"], v["sensor_light"], v["general_sensors"]))
        if v["rst"] == 0:
            outs = (0, 0, 0, 0)
        else:
            if "RUNTIME_ERROR" in self._flags:
                raise SimError("boom")
            outs = safe_controller(v["sensor_light"], v["general_sensors"])
            if "CODE5" in self._flags:
                outs = (5, *outs[1:])
        for name, code in zip(_OUTS, outs, strict=True):
            if name in v:
                v[name] = code
        self._cycle += 1

    @property
    def cycle(self) -> int:
        return self._cycle

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            self._backend.open_handles -= 1


class FakeLightCompiled:
    def __init__(self, backend: FakeLightBackend, flags: frozenset[str]) -> None:
        self._backend = backend
        self._flags = flags

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return ()

    def open(self, top: str | None) -> FakeLightHandle:
        self._backend.open_handles += 1
        handle = FakeLightHandle(self._backend, self._flags)
        self._backend.handles.append(handle)
        return handle

    def close(self) -> None:
        return None


class FakeLightBackend:
    """Flags in the file text pick the behaviour: SYNTAX_ERROR, MISSING_OUTW, BAD_WIDTH,
    RUNTIME_ERROR, CODE5."""

    FLAGS = ("MISSING_OUTW", "BAD_WIDTH", "RUNTIME_ERROR", "CODE5")

    def __init__(self) -> None:
        self.open_handles = 0
        self.handles: list[FakeLightHandle] = []

    def live(self) -> list[FakeLightHandle]:
        return [h for h in self.handles if not h.closed]

    def compile(self, files: Sequence[Path]) -> FakeLightCompiled:
        text = "\n".join(p.read_text(encoding="utf-8") for p in files)
        if "SYNTAX_ERROR" in text:
            path = files[0]
            raw = f"{path}:2:5: error: syntax: unexpected X"
            raise CompileError([Diagnostic("error", "syntax: unexpected X", str(path), 2, 5, raw)])
        return FakeLightCompiled(self, frozenset(f for f in self.FLAGS if f in text))


def _check_protocol(b: FakeLightBackend) -> Backend:
    return b
