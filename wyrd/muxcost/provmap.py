"""Reader of the Odin III version 2 name map (``<netlist>.names``, ``--prov-map``).

Reads the file only; never imports odin3. Only the line types the mux cost report needs are kept:
``O`` and ``N`` (named objects), ``R`` (records) and ``C`` (AST constructs). Format:
``docs/user/provenance.md`` of Odin III.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

HEADER = "# odin3-names 2 "
_ESCAPE = re.compile(r"%([0-9A-Fa-f]{2})")


class MapError(Exception):
    """The name map cannot be used; the message says why, in one line."""


def unescape(text: str) -> str:
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), text)


@dataclass(frozen=True)
class Record:
    kind: str
    level: str
    parents: tuple[str, ...]
    cons: tuple[str, ...]
    flags: dict[str, str]

    @property
    def uid(self) -> str | None:
        return self.flags.get("uid")

    @property
    def cell_type(self) -> str | None:
        return self.flags.get("cell")


@dataclass(frozen=True)
class Construct:
    kind: str
    level: str
    parent: str
    file: str
    span: str


@dataclass
class NameMap:
    """``objects``: (kind, name) to (record id, level). ``records`` and ``constructs`` by id."""

    objects: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    records: dict[str, Record] = field(default_factory=dict)
    constructs: dict[str, Construct] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)

    def record_of(self, kind: str, name: str) -> Record | None:
        found = self.objects.get((kind, name))
        return self.records.get(found[0]) if found else None


def _flags(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in text.split(","):
        if item:
            key, _, value = item.partition("=")
            out[key] = value
    return out


def _ids(text: str) -> tuple[str, ...]:
    return tuple(x for x in text.split(",") if x)


def _object(m: NameMap, f: list[str]) -> None:
    if f[0] == "O" and len(f) >= 10:
        m.objects[(f[2], f[3])] = (f[8].split(",")[0], f[9])
    elif f[0] == "N" and len(f) >= 6:
        m.objects[(f[2], f[3])] = (f[4].split(",")[0], f[5])


def _line(m: NameMap, f: list[str]) -> None:
    if f[0] in ("O", "N"):
        _object(m, f)
    elif f[0] == "R" and len(f) >= 9:
        flags = _flags(f[9]) if len(f) > 9 else {}
        m.records[f[1]] = Record(f[2], f[3], _ids(f[6]), _ids(f[8]) if f[2] == "S" else (), flags)
    elif f[0] == "C" and len(f) >= 7:
        m.constructs[f[1]] = Construct(f[2], f[3], f[4], f[5], f[6])
    elif f[0] == "F" and len(f) >= 3:
        m.files[f[1]] = unescape(f[2])


def parse(text: str) -> NameMap:
    """Parse the text of a version 2 name map; raise ``MapError`` when the header is wrong."""
    lines = text.split("\n")
    if not lines or not lines[0].startswith(HEADER):
        raise MapError("not an Odin III version 2 name map (header line missing)")
    m = NameMap()
    for raw in lines[1:]:
        if raw:
            _line(m, raw.split("\t"))
    return m


def read(path: Path) -> NameMap:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise MapError(f"cannot read {path.name}: {e.strerror or e}") from e
    return parse(text)


def ancestors(m: NameMap, rid: str) -> list[str]:
    """Record ids reachable from ``rid`` through parents (``rid`` first), in discovery order."""
    seen: dict[str, None] = {}
    stack = [rid]
    while stack:
        x = stack.pop()
        if x in seen or x not in m.records:
            continue
        seen[x] = None
        stack.extend(reversed(m.records[x].parents))
    return list(seen)
