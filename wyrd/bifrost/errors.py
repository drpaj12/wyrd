"""Exceptions of the simulation session (spec 5.1)."""

from __future__ import annotations

from collections.abc import Sequence

from wyrd.bifrost.types import Diagnostic


class SimError(Exception):
    """Base class of every Bifrost error."""


class SimUnavailable(SimError):
    """odin3 or its simulation API is missing."""


def format_diagnostic(d: Diagnostic) -> str:
    """`file:line:col: message`, parts omitted when unknown."""
    where = ""
    if d.file is not None:
        where = d.file
        if d.line is not None:
            where += f":{d.line}"
            if d.col is not None:
                where += f":{d.col}"
        where += ": "
    return where + d.message


class CompileError(SimError):
    def __init__(self, diagnostics: Sequence[Diagnostic], message: str | None = None) -> None:
        self.diagnostics: tuple[Diagnostic, ...] = tuple(diagnostics)
        self.message = message if message is not None else self._first_error_text()
        super().__init__(self.message)

    def _first_error_text(self) -> str:
        for d in self.diagnostics:
            if d.severity == "error":
                return format_diagnostic(d)
        return "compile failed"

    def __str__(self) -> str:
        return self.message


class NoSuchSignal(SimError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(
            f"{name}: not in the simulated netlist (a pass may have removed it: mark it "
            "(* keep *) in the HDL, or see BifrostSession.signals())"
        )


class SignalKindError(SimError):
    """`set` on a signal that is not an input."""


class ValueRangeError(SimError, ValueError):
    """A value is negative or does not fit the signal width."""


class SessionClosed(SimError, RuntimeError):
    """A method of a closed session."""


class VectorError(SimError):
    def __init__(self, line: int, message: str) -> None:
        self.line = line
        self.message = message
        super().__init__(f"{line}: {message}")
