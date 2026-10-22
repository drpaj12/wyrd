"""Validation and editing of ``wyrd.toml`` text for the GUI editor (spec section 10)."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wyrd.project import ConfigError, load_project

_SWEEP = re.compile(r"^\s*\[\s*sweep\s*\]")
_HEADER = re.compile(r"^\s*\[")
_DESIGN_KEY = re.compile(r"^\s*design\s*=\s*\[")


@dataclass(frozen=True)
class Diagnostic:
    line: int | None
    message: str


@dataclass(frozen=True)
class Validation:
    ok: bool
    runs: int
    diagnostic: Diagnostic | None


class AddDesignError(ValueError):
    """The design block was added but the sweep list could not be edited; ``text`` has the block."""

    def __init__(self, message: str, text: str) -> None:
        super().__init__(message)
        self.text = text


def validate_text(path: Path, text: str) -> Validation:
    """Check ``text`` as the content of the project file at ``path``."""
    try:
        project = load_project(path, text=text)
    except ConfigError as e:
        return Validation(False, 0, Diagnostic(e.line, e.msg))
    except Exception as e:
        return Validation(False, 0, Diagnostic(None, f"{type(e).__name__}: {e}"))
    return Validation(True, len(project.runs), None)


def relative_files(root: Path, chosen: Sequence[Path]) -> list[str]:
    """Paths relative to ``root`` with ``/`` separators."""
    return [Path(os.path.relpath(p, root)).as_posix() for p in chosen]


def _design_block(name: str, files: Sequence[str], top: str | None) -> str:
    lines = ["", "[[design]]", f"name = {json.dumps(name)}"]
    lines.append(f"files = [{', '.join(json.dumps(f) for f in files)}]")
    if top:
        lines.append(f"top = {json.dumps(top)}")
    return "\n".join(lines) + "\n"


def _scan_line(line: str, depth: int) -> int | None:
    """Bracket depth after ``line``; skips strings and comments. None for a multi-line string."""
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            if line.startswith(c * 3, i):
                return None
            quote = c
        elif c == "#":
            break
        elif c == "[":
            depth += 1
        elif c == "]":
            depth = max(depth - 1, 0)
        i += 1
    return depth


def _list_span(text: str, start: int) -> tuple[int, int | None] | None:
    """Close index of the list opened just before ``start`` and the end of its last code char.

    Skips strings and ``#`` comments. The second value is None when the list holds no code.
    """
    depth, i, quote, last = 1, start, "", None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
                last = i + 1
        elif c in "\"'":
            quote = c
        elif c == "#":
            end = text.find("\n", i)
            i = len(text) if end < 0 else end
            continue
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i, last
            last = i + 1
        elif c == "[":
            depth += 1
            last = i + 1
        elif not c.isspace():
            last = i + 1
        i += 1
    return None


def _design_key_line(lines: list[str]) -> int | None:
    """Index of the ``design = [`` line inside the ``[sweep]`` table, if any.

    Only lines at bracket depth 0 count, so a continuation line of a multi-line array that
    starts with ``[`` is not taken for a table header.
    """
    depth, in_sweep = 0, False
    for i, ln in enumerate(lines):
        if depth == 0:
            if _SWEEP.match(ln):
                in_sweep = True
            elif _HEADER.match(ln):
                in_sweep = False
            elif in_sweep and _DESIGN_KEY.match(ln):
                return i
        scanned = _scan_line(ln, depth)
        if scanned is None:
            return None
        depth = scanned
    return None


def _insert_in_sweep(text: str, name: str) -> str | None:
    lines = text.splitlines(keepends=True)
    idx = _design_key_line(lines)
    if idx is None:
        return None
    offset = sum(len(ln) for ln in lines[:idx])
    open_at = offset + lines[idx].index("[", lines[idx].index("="))
    span = _list_span(text, open_at + 1)
    if span is None:
        return None
    _, last = span
    item = json.dumps(name)
    if last is None:
        return text[: open_at + 1] + item + text[open_at + 1 :]
    piece = f" {item}," if text[last - 1] == "," else f", {item}"
    return text[:last] + piece + text[last:]


def add_design(
    text: str, name: str, files: Sequence[str], top: str | None, add_to_sweep: bool
) -> str:
    """Append a ``[[design]]`` block and optionally add the name to the sweep's design list.

    Raise AddDesignError (with the block already appended in ``.text``) when the sweep list
    cannot be found.
    """
    base = text if not text or text.endswith("\n") else text + "\n"
    block = _design_block(name, files, top)
    if add_to_sweep:
        edited = _insert_in_sweep(base, name)
        if edited is None:
            raise AddDesignError(
                "Cannot edit [sweep] design automatically; add the name by hand", base + block
            )
        base = edited
    return base + block
