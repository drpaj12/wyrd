"""Python fakes of the S1 simulator: a `Backend` and an imitation of the `odin3` binding."""

from __future__ import annotations

import contextlib
import types
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from wyrd.bifrost.errors import CompileError
from wyrd.bifrost.types import Diagnostic, Kind, Signal

TRAFFIC_SIGNALS: tuple[Signal, ...] = (
    Signal("clk", 1, "clock"),
    Signal("rst", 1, "input"),
    Signal("car_ns", 1, "input"),
    Signal("car_ew", 1, "input"),
    Signal("light_ns", 2, "output", 1, 0),
    Signal("light_ew", 2, "output", 1, 0),
    Signal("state", 2, "internal", 1, 0),
    Signal("timer", 3, "internal", 2, 0),
)


class TrafficFsm:
    """The S1 `traffic.v` fixture as a Python state machine."""

    def __init__(self) -> None:
        self._by_name = {s.name: s for s in TRAFFIC_SIGNALS}
        self.reset()

    def reset(self) -> None:
        self.inputs = {"rst": 0, "car_ns": 0, "car_ew": 0}
        self.state = 0
        self.timer = 0
        self.cycle = 0

    def signals(self) -> list[Signal]:
        return list(TRAFFIC_SIGNALS)

    def signal(self, name: str) -> Signal | None:
        return self._by_name.get(name)

    def get(self, name: str) -> int:
        if name not in self._by_name:
            raise KeyError(name)
        if name in self.inputs:
            return self.inputs[name]
        values = {
            "clk": 0,
            "state": self.state,
            "timer": self.timer,
            "light_ns": 2 if self.state == 0 else 1 if self.state == 1 else 0,
            "light_ew": 2 if self.state == 2 else 1 if self.state == 3 else 0,
        }
        return values[name]

    def set(self, name: str, value: int) -> None:
        sig = self._by_name.get(name)
        if sig is None:
            raise KeyError(name)
        if sig.kind != "input":
            raise ValueError(f"{name}: not an input")
        if not 0 <= value < 2**sig.width:
            raise ValueError(f"{name}: value {value} out of range")
        self.inputs[name] = value

    def _tick(self) -> None:
        if self.inputs["rst"]:
            self.state, self.timer = 0, 0
        elif self.timer != 0:
            self.timer -= 1
        else:
            self._advance()
        self.cycle += 1

    def _advance(self) -> None:
        if self.state == 0 and self.inputs["car_ew"]:
            self.state, self.timer = 1, 1
        elif self.state == 1:
            self.state, self.timer = 2, 3
        elif self.state == 2 and self.inputs["car_ns"]:
            self.state, self.timer = 3, 1
        elif self.state == 3:
            self.state, self.timer = 0, 3

    def step(self, cycles: int) -> None:
        for _ in range(cycles):
            self._tick()


class FakeHandle:
    def __init__(self, backend: FakeBackend) -> None:
        self._backend = backend
        self._fsm = TrafficFsm()
        self._closed = False

    def signals(self) -> Sequence[Signal]:
        return self._fsm.signals()

    def signal(self, name: str) -> Signal | None:
        return self._fsm.signal(name)

    def get(self, name: str) -> int:
        return self._fsm.get(name)

    def set(self, name: str, value: int) -> None:
        self._fsm.set(name, value)

    def settle(self) -> None:
        return None

    def step(self, cycles: int) -> None:
        self._fsm.step(cycles)

    def reset(self) -> None:
        self._fsm.reset()

    @property
    def cycle(self) -> int:
        return self._fsm.cycle

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._backend.open_handles -= 1


class FakeCompiled:
    def __init__(self, backend: FakeBackend, diagnostics: tuple[Diagnostic, ...]) -> None:
        self._backend = backend
        self._diagnostics = diagnostics
        self._closed = False

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self._diagnostics

    def open(self, top: str | None) -> FakeHandle:
        self._backend.last_top = top
        self._backend.open_handles += 1
        return FakeHandle(self._backend)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._backend.open_handles -= 1


class FakeBackend:
    """A `Backend` whose every design is the traffic FSM, unless the text says otherwise."""

    def __init__(self) -> None:
        self.compiled = 0
        self.open_handles = 0
        self.last_top: str | None = None
        self.compile_calls: list[tuple[Path, ...]] = []

    def compile(self, files: Sequence[Path]) -> FakeCompiled:
        self.compile_calls.append(tuple(files))
        texts = [(p, p.read_text(encoding="utf-8")) for p in files]
        warnings: list[Diagnostic] = []
        for path, text in texts:
            if "SYNTAX_ERROR" in text:
                raw = f"{path}:2:5: error: syntax: unexpected X"
                diag = Diagnostic("error", "syntax: unexpected X", str(path), 2, 5, raw)
                raise CompileError([diag])
            if "WARN_ME" in text:
                raw = f"{path}:1:1: warning: unused thing"
                warnings.append(Diagnostic("warning", "unused thing", str(path), 1, 1, raw))
        self.compiled += 1
        self.open_handles += 1
        return FakeCompiled(self, tuple(warnings))


class LogRecord(NamedTuple):
    level: int
    message: str


class SignalInfo(NamedTuple):
    id: int
    name: str
    leaf: str
    width: int
    kind: Kind
    msb: int
    lsb: int
    scope: str
    obj: int
    first_bit: int


def _info(index: int, sig: Signal) -> SignalInfo:
    leaf = sig.name.rsplit(".", 1)[-1]
    return SignalInfo(index, sig.name, leaf, sig.width, sig.kind, sig.msb, sig.lsb, "", 0, 0)


def _name_of(sig: Any) -> str:
    return str(sig.name) if isinstance(sig, SignalInfo) else str(sig)


def make_fake_odin3(
    *,
    has_simulation: bool = True,
    fail_with: list[tuple[int, str]] | None = None,
    warnings: list[tuple[int, str]] | None = None,
) -> types.ModuleType:
    """A module imitating the `odin3` binding (S1 SP-1) over the traffic FSM."""
    module = types.ModuleType("odin3")
    log_of_scripts: list[str] = []

    class Odin3Error(RuntimeError):
        pass

    class Simulation:
        def __init__(self) -> None:
            self._fsm = TrafficFsm()
            self._closed = False

        def signals(self) -> list[SignalInfo]:
            return [_info(i, s) for i, s in enumerate(self._fsm.signals())]

        def signal(self, name: str) -> SignalInfo | None:
            sig = self._fsm.signal(name)
            return None if sig is None else _info(0, sig)

        def get(self, sig: Any) -> int:
            return self._fsm.get(_name_of(sig))

        def set(self, sig: Any, value: int) -> None:
            self._fsm.set(_name_of(sig), value)

        def settle(self) -> None:
            return None

        def step(self, cycles: int = 1) -> None:
            self._fsm.step(cycles)

        def reset(self) -> None:
            self._fsm.reset()

        @property
        def cycle(self) -> int:
            return self._fsm.cycle

        def close(self) -> None:
            self._closed = True

    class Log:
        def __init__(self) -> None:
            self.records: list[LogRecord] | None = None

        @contextlib.contextmanager
        def capture_log(self) -> Iterator[list[LogRecord]]:
            self.records = []
            try:
                yield self.records
            finally:
                self.records = None

    class Design:
        scripts = log_of_scripts

        def __init__(self) -> None:
            self.odin3 = Log()
            self.closed = False

        def run_script(self, text: str) -> None:
            log_of_scripts.append(text)
            extra = [LogRecord(lv, msg) for lv, msg in (warnings or [])]
            if fail_with is not None:
                extra += [LogRecord(lv, msg) for lv, msg in fail_with]
            if self.odin3.records is not None:
                self.odin3.records.extend(extra)
            if fail_with is not None:
                raise Odin3Error("script failed")

        def simulate(self, top: str | None = None) -> Simulation:
            if top == "nope":
                raise ValueError("no module named 'nope'")
            return Simulation()

        def close(self) -> None:
            self.closed = True

    module.__dict__.update(
        Odin3Error=Odin3Error, Design=Design, LogRecord=LogRecord, SignalInfo=SignalInfo
    )
    if has_simulation:
        module.__dict__["Simulation"] = Simulation
    return module
