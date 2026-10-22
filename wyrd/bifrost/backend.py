"""The Backend protocol and the Odin III adapter (spec 5.3). The only module that imports odin3."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from wyrd.bifrost.diagnostics import parse_log
from wyrd.bifrost.errors import CompileError, SimError, SimUnavailable
from wyrd.bifrost.types import Diagnostic, Signal

UNAVAILABLE = (
    "odin3 with the simulation API is not installed; run: pip install \"wyrd[sim]\" "
    "(needs Odin III 1.0.3 or later)"
)


class SimHandle(Protocol):
    def signals(self) -> Sequence[Signal]: ...
    def signal(self, name: str) -> Signal | None: ...
    def get(self, name: str) -> int: ...
    def set(self, name: str, value: int) -> None: ...
    def settle(self) -> None: ...
    def step(self, cycles: int) -> None: ...
    def reset(self) -> None: ...
    @property
    def cycle(self) -> int: ...
    def close(self) -> None: ...


class CompiledDesign(Protocol):
    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]: ...
    def open(self, top: str | None) -> SimHandle: ...
    def close(self) -> None: ...


class Backend(Protocol):
    def compile(self, files: Sequence[Path]) -> CompiledDesign: ...


def _plain(text: str) -> Diagnostic:
    return Diagnostic("error", text, None, None, None, text)


def _signal(info: Any) -> Signal:
    return Signal(str(info.name), int(info.width), info.kind, int(info.msb), int(info.lsb))


class _Handle:
    def __init__(self, odin3: ModuleType, sim: Any, owner: _Compiled) -> None:
        self._err: type[Exception] = odin3.Odin3Error
        self._sim = sim
        self._owner = owner
        self._closed = False
        self._signals = tuple(_signal(i) for i in sim.signals())

    def signals(self) -> Sequence[Signal]:
        return self._signals

    def signal(self, name: str) -> Signal | None:
        try:
            info = self._sim.signal(name)
        except self._err as e:
            raise SimError(str(e)) from e
        return None if info is None else _signal(info)

    def get(self, name: str) -> int:
        try:
            value: int = self._sim.get(name)
        except self._err as e:
            raise SimError(str(e)) from e
        return value

    def set(self, name: str, value: int) -> None:
        try:
            self._sim.set(name, value)
        except self._err as e:
            raise SimError(str(e)) from e

    def settle(self) -> None:
        try:
            self._sim.settle()
        except self._err as e:
            raise SimError(str(e)) from e

    def step(self, cycles: int) -> None:
        try:
            self._sim.step(cycles)
        except self._err as e:
            raise SimError(str(e)) from e

    def reset(self) -> None:
        try:
            self._sim.reset()
        except self._err as e:
            raise SimError(str(e)) from e

    @property
    def cycle(self) -> int:
        value: int = self._sim.cycle
        return value

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._owner.forget(self)
            self._sim.close()


class _Compiled:
    def __init__(
        self, odin3: ModuleType, design: Any, diagnostics: tuple[Diagnostic, ...]
    ) -> None:
        self._odin3 = odin3
        self._design = design
        self._diagnostics = diagnostics
        self._handles: list[_Handle] = []
        self._closed = False

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self._diagnostics

    def forget(self, handle: _Handle) -> None:
        if handle in self._handles:
            self._handles.remove(handle)

    def open(self, top: str | None) -> SimHandle:
        err: type[Exception] = self._odin3.Odin3Error
        try:
            sim = self._design.simulate(top)
        except ValueError as e:
            raise CompileError([_plain(str(e))]) from e
        except err as e:
            raise CompileError([_plain(str(e))]) from e
        handle = _Handle(self._odin3, sim, self)
        self._handles.append(handle)
        return handle

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for handle in list(self._handles):
            handle.close()
        self._design.close()


class Odin3Backend:
    def __init__(self) -> None:
        try:
            module = importlib.import_module("odin3")
        except ImportError as e:
            raise SimUnavailable(UNAVAILABLE) from e
        if not hasattr(module, "Simulation"):
            raise SimUnavailable(UNAVAILABLE)
        self._odin3 = module

    def compile(self, files: Sequence[Path]) -> CompiledDesign:
        for p in files:
            if '"' in str(p):
                raise CompileError([_plain(f"{p}: a path with a double quote is not supported")])
        script = "read_verilog " + " ".join(f'"{p}"' for p in files) + "; proc; opt; lower"
        design = self._odin3.Design()
        failure: Exception | None = None
        with design.odin3.capture_log() as records:
            try:
                design.run_script(script)
            except self._odin3.Odin3Error as e:
                failure = e
        diagnostics = parse_log((r.level, r.message) for r in records)
        if failure is None:
            return _Compiled(self._odin3, design, diagnostics)
        design.close()
        has_error = any(d.severity == "error" for d in diagnostics)
        raise CompileError(diagnostics, None if has_error else str(failure) or None)


def default_backend() -> Backend:
    return Odin3Backend()


def odin3_available() -> bool:
    try:
        Odin3Backend()
    except SimUnavailable:
        return False
    return True
