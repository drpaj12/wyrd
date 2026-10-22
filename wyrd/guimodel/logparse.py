"""Turn Odin III and VPR log lines into messages with source locations (spec section 6)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

_ODIN = re.compile(r"^odin3: (?P<level>error|warning): (?P<rest>.*)$")
_LOC = re.compile(
    r"(?P<file>[^\s:'\"]+\.[A-Za-z0-9_]+):(?P<line>\d+)(?::(?P<col>\d+))?: "
    r"(?:(?:error|warning): )?"
)
_VPR_WARN = re.compile(r"^Warning (?P<n>\d+): (?P<text>.*)$")
_VPR_ERR = re.compile(r"^Error (?P<n>\d+): ?(?P<text>.*)$")
_UPPER = re.compile(r"^(?P<level>WARNING|ERROR)[: ] ?(?P<text>.*)$")
_VPR_FIELDS = ("Type: ", "File: ", "Line: ", "Message: ")


@dataclass(frozen=True)
class Message:
    severity: str
    tool: str
    text: str
    file: str | None
    line: int | None
    col: int | None
    log: Path
    log_line: int


def _odin_message(level: str, rest: str, log: Path, n: int) -> Message:
    m = _LOC.search(rest)
    if m is None:
        return Message(level, "odin3", rest, None, None, None, log, n)
    text = rest[m.end() :] if m.start() == 0 else rest
    col = m.group("col")
    return Message(
        level, "odin3", text, m.group("file"), int(m.group("line")),
        int(col) if col else None, log, n,
    )  # fmt: skip


def _vpr_text(header: str, fields: dict[str, str]) -> str:
    base = ": ".join(p for p in (fields.get("Type: "), fields.get("Message: ")) if p)
    where = fields.get("File: ", "")
    if where and fields.get("Line: "):
        where += ":" + fields["Line: "]
    if not base and not where:
        return header
    if not where:
        return base
    return f"{base} ({where})" if base else f"({where})"


def _fold_vpr(lines: Sequence[str], start: int) -> tuple[dict[str, str], int]:
    """Collect the Type/File/Line/Message lines after the error header at ``start``."""
    j = start + 1
    if j + 1 < len(lines) and not lines[j].strip() and lines[j + 1].startswith(_VPR_FIELDS):
        j += 1
    fields: dict[str, str] = {}
    for prefix in _VPR_FIELDS:
        if j < len(lines) and lines[j].startswith(prefix):
            fields[prefix] = lines[j][len(prefix) :].strip()
            j += 1
    return fields, j


def _single(line: str, log: Path, n: int) -> Message | None:
    m = _ODIN.match(line)
    if m:
        return _odin_message(m.group("level"), m.group("rest"), log, n)
    m = _VPR_WARN.match(line)
    if m:
        return Message("warning", "vpr", m.group("text"), None, None, None, log, n)
    m = _UPPER.match(line)
    if m:
        sev = m.group("level").lower()
        return Message(sev, "odin3", m.group("text"), None, None, None, log, n)
    return None


def parse_lines(lines: Iterable[str], log: Path) -> list[Message]:
    """Parse log lines; ``log_line`` is 1-based."""
    rows = [ln.rstrip("\r\n") for ln in lines]
    out: list[Message] = []
    i = 0
    while i < len(rows):
        m = _VPR_ERR.match(rows[i])
        if m:
            fields, nxt = _fold_vpr(rows, i)
            text = _vpr_text(m.group("text").strip(), fields)
            out.append(Message("error", "vpr", text, None, None, None, log, i + 1))
            i = nxt
            continue
        msg = _single(rows[i], log, i + 1)
        if msg is not None:
            out.append(msg)
        i += 1
    return out


def parse_log(path: Path) -> list[Message]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return parse_lines(text.splitlines(), path)


def step_messages(step_dir: Path) -> list[Message]:
    """All messages of the ``*.log`` files under ``step_dir``, without duplicates."""
    seen: set[tuple[str, str, str, str | None, int | None]] = set()
    out: list[Message] = []
    for log in sorted(step_dir.rglob("*.log")):
        for msg in parse_log(log):
            key = (msg.severity, msg.tool, msg.text, msg.file, msg.line)
            if key not in seen:
                seen.add(key)
                out.append(msg)
    return out


def _find(file: str, search_dirs: Sequence[Path], design_files: Sequence[Path]) -> Path | None:
    p = Path(file)
    if p.is_absolute() and p.is_file():
        return p
    for d in search_dirs:
        cand = d / file
        if cand.is_file():
            return cand
    same = [f for f in design_files if f.name == p.name]
    return same[0] if len(same) == 1 else None


def resolve_location(
    msg: Message, search_dirs: Sequence[Path], design_files: Sequence[Path] = ()
) -> tuple[Path, int]:
    """Where a click on ``msg`` should open: the source line, else the log line."""
    if msg.file is not None and msg.line is not None:
        found = _find(msg.file, search_dirs, design_files)
        if found is not None:
            return found, msg.line
    return msg.log, msg.log_line
