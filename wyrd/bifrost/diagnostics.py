"""Turn Odin III log records into Diagnostics (spec 5.4)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from wyrd.bifrost.types import Diagnostic

_LOCATED = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+)(?::(?P<col>\d+))?: (?:(?P<sev>error|warning): )?(?P<msg>.*)$"
)

Severity = Literal["error", "warning"]


def _is_noise(message: str) -> bool:
    if message.startswith("pass ") and ": failed: " in message:
        return True
    return message.startswith("python: command ")


def _one(level: int, message: str) -> Diagnostic:
    by_level: Severity = "error" if level == 0 else "warning"
    m = _LOCATED.match(message)
    if m is None:
        return Diagnostic(by_level, message, None, None, None, message)
    sev: Severity = by_level
    if m["sev"] == "error":
        sev = "error"
    elif m["sev"] == "warning":
        sev = "warning"
    col = int(m["col"]) if m["col"] is not None else None
    return Diagnostic(sev, m["msg"], m["file"], int(m["line"]), col, message)


def parse_log(records: Iterable[tuple[int, str]]) -> tuple[Diagnostic, ...]:
    kept = ((lv, msg) for lv, msg in records if lv in (0, 1) and not _is_noise(msg))
    return tuple(_one(level, msg) for level, msg in kept)
