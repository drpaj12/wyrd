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


def _list_end(text: str, start: int) -> int | None:
    """Index of the ``]`` closing the list whose ``[`` precedes ``start``; skips strings."""
    i, quote = start, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "]":
            return i
        i += 1
    return None


def _design_key_line(lines: list[str]) -> int | None:
    """Index of the ``design = [`` line inside the ``[sweep]`` table, if any."""
    start = next((i for i, ln in enumerate(lines) if _SWEEP.match(ln)), None)
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        if _DESIGN_KEY.match(lines[i]):
            return i
        if _HEADER.match(lines[i]):
            return None
    return None


def _insert_in_sweep(text: str, name: str) -> str | None:
    lines = text.splitlines(keepends=True)
    idx = _design_key_line(lines)
    if idx is None:
        return None
    offset = sum(len(ln) for ln in lines[:idx])
    open_at = offset + lines[idx].index("[", lines[idx].index("="))
    close = _list_end(text, open_at + 1)
    if close is None:
        return None
    body = text[open_at + 1 : close].rstrip()
    last = open_at + 1 + len(body)
    item = json.dumps(name)
    if not body.strip():
        piece = item
    elif body.endswith(","):
        piece = f" {item},"
    else:
        piece = f", {item}"
    return text[:last] + piece + text[last:]


def add_design(text: str, name: str, files: Sequence[str], top: str | None,
               add_to_sweep: bool) -> str:  # fmt: skip
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
