"""Hot/cold facts: criticality of attributed path nodes, source-neutral, Qt-free.

A ``Fact`` is one node of one path (file, line, word, bit, crit). ``load_heat`` builds a
``HeatModel`` from ``attribution.json`` (schema 1). The Mímir adapter (``heatmimir``) builds the
same model from the v5 ``timing_object`` table. Criticality follows VPR 9 relaxed criticality, as
Mímir ``docs/specs/2026-10-28-near-critical.md`` section 2.1 (see the heat-explore spec).
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wyrd.guimodel import timing
from wyrd.guimodel.timing import TimingError

THETAS = (0.90, 0.95, 0.99)
BIT_VIAS = frozenset({"name", "pad"})
SCOPE_CRITICAL = "critical"
SCOPE_TOP = "top"
SCOPE_NEAR = "near"
SCOPE_KINDS = (SCOPE_CRITICAL, SCOPE_TOP, SCOPE_NEAR)
DEFAULT_TOP = 10
_CLOCKED = re.compile(r"clocked by ([^)\s]+)")


def round_crit(c: float) -> float:
    """Clamp to 0..1 and round to 9 decimals before any theta comparison (as Mímir)."""
    return round(min(1.0, max(0.0, c)), 9)


@dataclass(frozen=True)
class Scope:
    """Which facts count: the critical path, the worst ``n`` paths, or crit >= ``theta``."""

    kind: str = SCOPE_CRITICAL
    n: int = DEFAULT_TOP
    theta: float = THETAS[0]


@dataclass(frozen=True)
class PathInfo:
    index: int
    slack_ns: float | None
    crit: float
    endpoint: str


@dataclass(frozen=True)
class Fact:
    """One path node, or one Mímir object row (``path`` is then -1 and ``rank`` -1)."""

    file: str | None
    line: int | None
    module: str
    word: str
    bit: int | None
    via: str
    delay_ns: float
    crit: float
    path: int
    rank: int

    @property
    def bit_known(self) -> bool:
        return self.bit is not None and self.bit >= 0 and self.via in BIT_VIAS


@dataclass
class HeatModel:
    facts: tuple[Fact, ...]
    paths: dict[int, PathInfo] = field(default_factory=dict)
    seen_width: dict[tuple[str, str], int] = field(default_factory=dict)
    module_files: dict[str, set[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    has_paths: bool = True
    source: str = "attribution"
    origin: str = ""
    store: str = ""  # a Mímir model: the store file and the run its rows come from
    run_id: str = ""

    def files(self) -> set[str]:
        return {f.file for f in self.facts if f.file is not None}

    def known_names(self) -> set[str]:
        """The file names the model can colour: its span files and the design origin."""
        return self.files() | ({self.origin} if self.origin else set())

    def supports(self, scope: Scope) -> bool:
        return self.has_paths or scope.kind == SCOPE_NEAR

    def select(self, scope: Scope) -> list[Fact]:
        """The facts inside ``scope``; empty when the adapter cannot give that scope."""
        if not self.supports(scope):
            return []
        if scope.kind == SCOPE_CRITICAL:
            return [f for f in self.facts if f.rank == 0]
        if scope.kind == SCOPE_TOP:
            return [f for f in self.facts if 0 <= f.rank < max(scope.n, 0)]
        return [f for f in self.facts if round_crit(f.crit) >= scope.theta]

    def path_infos(self, indexes: Sequence[int]) -> list[PathInfo]:
        return [self.paths[i] for i in indexes if i in self.paths]


def _domain(start: str, end: str) -> tuple[str, str]:
    a, b = _CLOCKED.search(start), _CLOCKED.search(end)
    return (a.group(1) if a else "", b.group(1) if b else "")


@dataclass(frozen=True)
class PathRow:
    index: int
    start: str
    end: str
    slack: float
    required: float


def path_criticalities(paths: Sequence[PathRow]) -> tuple[dict[int, float], int, int]:
    """VPR relaxed criticality per path index, per clock domain pair; (crit, pairs, skipped)."""
    groups: dict[tuple[str, str], list[PathRow]] = defaultdict(list)
    for p in paths:
        groups[_domain(p.start, p.end)].append(p)
    crit: dict[int, float] = {}
    skipped = 0
    for rows in groups.values():
        worst = min(r.slack for r in rows)
        max_req = max(r.required for r in rows)
        shift = -worst if worst < 0 else 0.0
        denom = max_req + shift
        if denom < 0 or (denom == 0 and any(r.slack + shift != 0 for r in rows)):
            skipped += 1
            continue
        for r in rows:
            c = 1.0 if denom == 0 else 1.0 - (r.slack + shift) / denom
            crit[r.index] = round_crit(c)
    return crit, len(groups), skipped


def _f(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _s(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _path_rows(paths: list[dict[str, object]]) -> list[PathRow]:
    return [
        PathRow(
            _int(p.get("index")) or 0,
            _s(p.get("startpoint")),
            _s(p.get("endpoint")),
            _f(p.get("slack_ns")),
            _f(p.get("required_ns")),
        )
        for p in paths
    ]


def _node_fact(node: dict[str, object], crit: float, path: int, rank: int) -> Fact | None:
    where = timing.split_span(node.get("span"))
    word = _s(node.get("word"))
    if where is None and not word:
        return None
    return Fact(
        where[0] if where else None,
        where[1] if where else None,
        _s(node.get("module")),
        word,
        _int(node.get("bit")),
        _s(node.get("word_via")),
        _f(node.get("delay_ns")),
        crit,
        path,
        rank,
    )


def _dicts(value: object) -> list[dict[str, object]]:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def _widths(facts: Sequence[Fact], words: list[dict[str, object]]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for f in facts:
        if f.bit_known and f.bit is not None and f.word:
            key = (f.module, f.word)
            out[key] = max(out.get(key, 0), f.bit + 1)
    for w in words:
        raw = w.get("bits")
        bits = [b for b in raw if isinstance(b, int)] if isinstance(raw, list) else []
        if bits:
            key = (_s(w.get("module")), _s(w.get("word")))
            out[key] = max(out.get(key, 0), max(bits) + 1)
    return out


def _module_files(facts: Sequence[Fact]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for f in facts:
        if f.file is not None and f.module:
            out[f.module].add(f.file)
    return dict(out)


def parse_heat(data: object) -> HeatModel:
    """Build the model from decoded ``attribution.json``; raise ``TimingError``."""
    if not isinstance(data, dict):
        raise TimingError("attribution.json: the top level is not an object")
    version = data.get("schema_version")
    if type(version) is not int or version != timing.SCHEMA_VERSION:
        raise TimingError(
            f"attribution.json has schema_version {version!r}; "
            f"this Wyrd reads schema_version {timing.SCHEMA_VERSION} only"
        )
    paths = _dicts(data.get("paths"))
    rows = _path_rows(paths)
    crit, _pairs, skipped = path_criticalities(rows)
    facts: list[Fact] = []
    infos: dict[int, PathInfo] = {}
    usable = [(p, row) for p, row in zip(paths, rows, strict=True) if row.index in crit]
    usable.sort(key=lambda pr: (-crit[pr[1].index], pr[1].slack, pr[1].index))
    for rank, (p, row) in enumerate(usable):
        c = crit[row.index]
        infos[row.index] = PathInfo(row.index, row.slack, c, row.end)
        for n in _dicts(p.get("nodes")):
            fact = _node_fact(n, c, row.index, rank)
            if fact is not None:
                facts.append(fact)
    model = HeatModel(
        tuple(facts),
        infos,
        _widths(facts, _dicts(data.get("words"))),
        _module_files(facts),
    )
    if skipped:
        model.notes.append(f"{skipped} clock domain pair(s) skipped: criticality is undefined")
    if not facts:
        model.notes.append("no attributed path node has a source line or a word")
    return model


def load_heat(path: Path) -> HeatModel:
    """Read ``attribution.json``; raise ``TimingError`` with a plain message."""
    text = timing._read_capped(path, timing.MAX_ATTRIBUTION_BYTES)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TimingError(f"{path.name} is not valid JSON: {e}") from e
    return parse_heat(data)
