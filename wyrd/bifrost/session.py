"""BifrostSession: a named-signal simulation session over a Backend (spec 5.2)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import TracebackType

from wyrd.bifrost.backend import Backend, CompiledDesign, SimHandle, default_backend
from wyrd.bifrost.errors import (
    CompileError,
    NoSuchSignal,
    SessionClosed,
    SignalKindError,
    ValueRangeError,
)
from wyrd.bifrost.record import Recorder, Recording
from wyrd.bifrost.types import Diagnostic, Signal


def _unreadable(path: Path) -> CompileError:
    d = Diagnostic("error", "cannot read file", str(path), None, None, f"{path}: cannot read file")
    return CompileError([d])


def _resolve(files: Sequence[str | Path]) -> list[Path]:
    if not files:
        raise ValueError("no Verilog files given")
    paths = [Path(f).resolve() for f in files]
    for p in paths:
        if not p.is_file():
            raise _unreadable(p)
    return paths


class BifrostSession:
    def __init__(
        self, compiled: CompiledDesign, handle: SimHandle, sources: Sequence[Path]
    ) -> None:
        self._compiled = compiled
        self._handle = handle
        self._sources = tuple(sources)
        self._closed = False
        self._signals = tuple(handle.signals())
        self._cache: dict[str, Signal] = {s.name: s for s in self._signals}
        self._recorder: Recorder | None = None

    @classmethod
    def from_verilog(
        cls,
        files: Sequence[str | Path],
        *,
        top: str | None = None,
        backend: Backend | None = None,
    ) -> BifrostSession:
        paths = _resolve(files)
        compiled = (backend if backend is not None else default_backend()).compile(paths)
        try:
            handle = compiled.open(top)
        except BaseException:
            compiled.close()
            raise
        try:
            return cls(compiled, handle, paths)
        except BaseException:
            handle.close()
            compiled.close()
            raise

    @property
    def sources(self) -> tuple[Path, ...]:
        return self._sources

    @property
    def diagnostics(self) -> tuple[Diagnostic, ...]:
        return self._compiled.diagnostics

    @property
    def signals(self) -> tuple[Signal, ...]:
        return self._signals

    def _of_kind(self, kind: str) -> tuple[Signal, ...]:
        return tuple(s for s in self._signals if s.kind == kind)

    @property
    def inputs(self) -> tuple[Signal, ...]:
        return self._of_kind("input")

    @property
    def clocks(self) -> tuple[Signal, ...]:
        return self._of_kind("clock")

    @property
    def outputs(self) -> tuple[Signal, ...]:
        return self._of_kind("output")

    @property
    def closed(self) -> bool:
        return self._closed

    def _check_open(self) -> None:
        if self._closed:
            raise SessionClosed("the simulation session is closed")

    @property
    def cycle(self) -> int:
        self._check_open()
        return self._handle.cycle

    def signal(self, name: str) -> Signal:
        self._check_open()
        sig = self._cache.get(name)
        if sig is None:
            sig = self._handle.signal(name)
            if sig is None:
                raise NoSuchSignal(name)
            self._cache[name] = sig
        return sig

    def has_signal(self, name: str) -> bool:
        try:
            self.signal(name)
        except NoSuchSignal:
            return False
        return True

    def get(self, name: str) -> int:
        self._check_open()
        try:
            return self._handle.get(name)
        except KeyError:
            raise NoSuchSignal(name) from None

    def get_many(self, names: Iterable[str]) -> dict[str, int]:
        return {n: self.get(n) for n in names}

    def _check_set(self, name: str, value: int) -> Signal:
        sig = self.signal(name)
        if sig.kind == "clock":
            raise SignalKindError(f"clock '{name}' is stepped, not set")
        if sig.kind != "input":
            raise SignalKindError(f"{sig.kind} '{name}' cannot be set, only inputs can")
        if value < 0 or value >= 1 << sig.width:
            raise ValueRangeError(f"{name}: value {value} does not fit {sig.width} bits")
        return sig

    def _put(self, name: str, value: int) -> None:
        try:
            self._handle.set(name, value)
        except KeyError:
            raise NoSuchSignal(name) from None
        except ValueError as e:
            raise ValueRangeError(str(e)) from e

    def set(self, name: str, value: int) -> None:
        self._check_open()
        self._check_set(name, value)
        self._put(name, value)

    def set_many(self, values: Mapping[str, int]) -> None:
        self._check_open()
        for name, value in values.items():
            self._check_set(name, value)
        for name, value in values.items():
            self._put(name, value)

    def step(self, cycles: int = 1) -> None:
        self._check_open()
        if cycles < 0:
            raise ValueError("cycles must be >= 0")
        if self._recorder is None:
            if cycles:
                self._handle.step(cycles)
            return
        self._step_recording(self._recorder, cycles)

    def _step_recording(self, rec: Recorder, cycles: int) -> None:
        for done in range(cycles):
            if rec.full:
                self._handle.step(cycles - done)
                return
            self._handle.step(1)
            self._sample(rec)

    def _sample(self, rec: Recorder) -> None:
        rec.add(self._handle.cycle, [self._handle.get(n) for n in rec.names])

    def settle(self) -> None:
        self._check_open()
        self._handle.settle()

    def reset(self) -> None:
        self._check_open()
        self._handle.reset()
        old = self._recorder
        if old is not None:
            self._recorder = Recorder(
                old.names, old.widths, old.clocks, old.max_samples, old.inputs
            )
            self._sample(self._recorder)

    def start_recording(
        self, names: Sequence[str] | None = None, max_samples: int = 1_000_000
    ) -> Recording:
        self._check_open()
        if max_samples < 1:
            raise ValueError("max_samples must be >= 1")
        if names is None:
            chosen = [s for s in self._signals if s.kind in ("input", "output")]
        else:
            chosen = [self.signal(n) for n in names]
        rec = Recorder(
            [s.name for s in chosen],
            [s.width for s in chosen],
            [s.name for s in self.clocks],
            max_samples,
            [s.name for s in chosen if s.kind == "input"],
        )
        self._sample(rec)
        self._recorder = rec
        return rec.snapshot()

    def stop_recording(self) -> Recording | None:
        self._check_open()
        rec, self._recorder = self._recorder, None
        return None if rec is None else rec.snapshot()

    @property
    def recording(self) -> Recording | None:
        return None if self._recorder is None else self._recorder.snapshot()

    @property
    def recording_full(self) -> bool:
        return self._recorder is not None and self._recorder.full

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._handle.close()
        finally:
            self._compiled.close()

    def __enter__(self) -> BifrostSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
