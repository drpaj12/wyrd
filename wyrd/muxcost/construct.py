"""The HDL construct of a mux, from the AST layer of the name map."""

from __future__ import annotations

import re
from dataclasses import dataclass

from wyrd.muxcost.provmap import NameMap, ancestors

KINDS = {"CASE": "case", "IF": "if", "TERNARY": "?:", "SELECT": "index"}
_SPAN = re.compile(r"^(.*):(\d+)\.(\d+)-(?:(\d+)\.)?(\d+)$")


@dataclass(frozen=True)
class Where:
    """A construct: its kind (``case``, ``if``, ``?:``, ``index``, ``other``) and HDL span."""

    kind: str
    file: str
    line: int
    span: str

    @property
    def key(self) -> str:
        return f"{self.file}:{self.span}"


def _depth(m: NameMap, cid: str) -> int:
    depth = 0
    seen: set[str] = set()
    while cid in m.constructs and cid not in seen:
        seen.add(cid)
        cid = m.constructs[cid].parent
        depth += 1
    return depth


def _candidates(m: NameMap, rid: str) -> dict[str, list[str]]:
    """Construct ids of the origin records above ``rid``, grouped by kind name."""
    out: dict[str, list[str]] = {}
    for x in ancestors(m, rid):
        for cid in m.records[x].cons:
            cons = m.constructs.get(cid)
            if cons is not None and cons.kind in KINDS:
                out.setdefault(cons.kind, []).append(cid)
    return out


def _span_where(kind: str, text: str) -> Where | None:
    mt = _SPAN.match(text)
    if mt is None:
        return None
    end = f"{mt.group(4)}." if mt.group(4) else ""
    return Where(
        kind, mt.group(1), int(mt.group(2)), f"{mt.group(2)}.{mt.group(3)}-{end}{mt.group(5)}"
    )


def of_cell(m: NameMap, cell: str, src: str) -> Where:
    """The outermost construct of the preferred kind above the cell; else its own ``src`` span."""
    rid = m.objects.get(("node", cell), ("", ""))[0]
    cands = _candidates(m, rid) if rid in m.records else {}
    for kind in KINDS:
        if kind in cands:
            cid = min(cands[kind], key=lambda c: (_depth(m, c), c))
            cons = m.constructs[cid]
            path = m.files.get(cons.file, cons.file)
            return _span_where(KINDS[kind], f"{path}:{cons.span}") or Where("other", path, 0, "")
    return _span_where("other", src.split("|")[0]) or Where("other", "", 0, "")
