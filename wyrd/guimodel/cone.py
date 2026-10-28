"""Fan-out and fan-in cones of a source line (Qt-free).

Two sources, always labelled: the *structural* cone walks the stored line-level HDL graph (Mímir
schema 7, breadth first, level = distance in logic levels); the *timing* cone takes the steps after
(or before) the clicked node on every stored path through it (schema 6) and stops where the paths
end. Spec: docs/specs/2026-10-28-cones.md.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from wyrd.mimirview import GraphNode, PathNodeRow

FORWARD, BACKWARD = ">", "<"
STRUCTURAL, TIMING = "structural", "timing"
REG, PI, PO = "register", "PI", "PO"
SOURCE_LABELS = {STRUCTURAL: "Structural cone (HDL graph)", TIMING: "Timing cone (stored paths)"}
TIMING_NOTE = (
    "Timing cone: only the steps of the stored paths through the clicked node, and it stops where "
    "those paths end (at registers)."
)


@dataclass(frozen=True)
class ConeNode:
    """One line (and word, bit) of a cone; ``level`` is its distance from the start."""

    file: str
    line: int
    module: str
    word: str
    bit: int
    level: int
    kind: str = ""  # REG, PI or PO at the ends of the cone
    crit: float | None = None


@dataclass
class Cone:
    source: str
    direction: str
    cross: bool
    nodes: list[ConeNode] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    hidden: int = 0  # nodes below the near-critical cut-off, not shown

    def title(self) -> str:
        arrow = "fan-out (>, to primary outputs)" if self.direction == FORWARD else (
            "fan-in (<, to primary inputs)")  # fmt: skip
        cross = ", crossing registers" if self.cross and self.source == STRUCTURAL else ""
        return f"{SOURCE_LABELS[self.source]}: {arrow}{cross}"

    def by_level(self) -> list[tuple[int, list[ConeNode]]]:
        levels: dict[int, list[ConeNode]] = {}
        for n in self.nodes:
            levels.setdefault(n.level, []).append(n)
        return [(lv, sorted(ns, key=lambda n: (n.file, n.line, n.word, n.bit)))
                for lv, ns in sorted(levels.items())]  # fmt: skip

    def lines(self) -> dict[str, dict[int, int]]:
        """file -> line -> smallest level."""
        out: dict[str, dict[int, int]] = {}
        for n in self.nodes:
            cur = out.setdefault(n.file, {})
            cur[n.line] = min(cur.get(n.line, n.level), n.level)
        return out


def split_span(span: str) -> tuple[str, int] | None:
    name, sep, tail = span.rpartition(":")
    return (name, int(tail)) if sep and name and tail.isdigit() else None


def start_nodes(
    nodes: Iterable[GraphNode], spans: Sequence[str], word: str | None, bit: int | None
) -> set[GraphNode]:
    """The graph nodes that are the clicked token: on one of the spans, the word and the bit when
    given; when the word or bit matches nothing, the word, then the whole line."""
    on_line = {n for n in nodes if n[0] in spans}
    if word:
        same_word = {n for n in on_line if n[2] == word}
        if bit is not None:
            exact = {n for n in same_word if n[3] == bit}
            if exact:
                return exact
        if same_word:
            return same_word
    return on_line


def walk(
    edges: Iterable[tuple[GraphNode, GraphNode, int]],
    ports: Iterable[tuple[GraphNode, str, str]],
    starts: set[GraphNode],
    direction: str,
    cross: bool,
) -> dict[GraphNode, tuple[int, str]]:
    """Breadth-first levels from ``starts``: node -> (level, kind). A register output is where a
    walk that does not cross registers ends: forward it does not take the edge that leaves it;
    backward it reaches the register (kind REG) and goes no further. PI and PO nodes are named."""
    fwd: dict[GraphNode, list[tuple[GraphNode, int]]] = {}
    back: dict[GraphNode, list[tuple[GraphNode, int]]] = {}
    for s, d, reg in edges:
        fwd.setdefault(s, []).append((d, reg))
        back.setdefault(d, []).append((s, reg))
    adj = fwd if direction == FORWARD else back
    seen: dict[GraphNode, tuple[int, str]] = {n: (0, "") for n in starts}
    queue = deque((n, 0) for n in sorted(starts))
    while queue:
        node, lv = queue.popleft()
        for nxt, reg in adj.get(node, ()):
            if reg and not cross and direction == FORWARD:
                continue
            if nxt in seen:
                continue
            ended = bool(reg and not cross)  # backward: the register output is the end
            seen[nxt] = (lv + 1, REG if ended else "")
            if not ended:
                queue.append((nxt, lv + 1))
    kinds = {n: k for n, k, _p in ports}
    for n, (lv, k) in list(seen.items()):
        if not k and n in kinds and lv > 0:
            seen[n] = (lv, kinds[n])
    return seen


def structural_cone(
    edges: Sequence[tuple[GraphNode, GraphNode, int]],
    ports: Sequence[tuple[GraphNode, str, str]],
    spans: Sequence[str],
    word: str | None,
    bit: int | None,
    direction: str,
    cross: bool,
    crit_of: Callable[[str], float | None],
    cutoff: float | None,
) -> Cone:
    """The structural cone of a clicked token, below-cut-off lines left out (counted in
    ``hidden``)."""
    nodes = {n for e in edges for n in e[:2]} | {p[0] for p in ports}
    starts = start_nodes(nodes, spans, word, bit)
    cone = Cone(STRUCTURAL, direction, cross)
    if not starts:
        cone.notes.append("the clicked token is not in the HDL graph of this run")
        return cone
    found = walk(edges, ports, starts, direction, cross)
    for node, (lv, kind) in sorted(found.items(), key=lambda kv: (kv[1][0], kv[0])):
        where = split_span(node[0])
        if where is None:
            continue
        crit = crit_of(node[0])
        if cutoff is not None and (crit is None or crit < cutoff - 1e-9):
            cone.hidden += 1
            continue
        cone.nodes.append(ConeNode(where[0], where[1], node[1], node[2], node[3], lv, kind, crit))
    return cone


def timing_cone(
    paths: Sequence[Sequence[PathNodeRow]],
    spans: Sequence[str],
    word: str | None,
    direction: str,
    crit_of: Callable[[str], float | None],
    cutoff: float | None,
) -> Cone:
    """The timing cone: on every path, the steps after (>) or before (<) the clicked node. The
    clicked node is the first step on one of the spans (and with the word, when it matches)."""
    cone = Cone(TIMING, direction, False, notes=[TIMING_NOTE])
    best: dict[tuple[str, int, str, str, int], tuple[int, str]] = {}
    for nodes in paths:
        pos = _clicked_step(nodes, spans, word)
        if pos is None:
            continue
        rng = range(pos + 1, len(nodes)) if direction == FORWARD else range(pos - 1, -1, -1)
        for i in rng:
            n = nodes[i]
            where = n.file_line
            if where is None:
                continue
            key = (where[0], where[1], n.module, n.word, n.bit)
            level = abs(i - pos)
            end = i == (len(nodes) - 1 if direction == FORWARD else 0)
            if key not in best or level < best[key][0]:
                best[key] = (level, REG if end else "")
    for (file, line, module, w, bit), (level, kind) in sorted(best.items(), key=lambda kv: kv[1]):
        crit = crit_of(f"{file}:{line}")
        if cutoff is not None and (crit is None or crit < cutoff - 1e-9):
            cone.hidden += 1
            continue
        cone.nodes.append(ConeNode(file, line, module, w, bit, level, kind, crit))
    return cone


def _clicked_step(
    nodes: Sequence[PathNodeRow], spans: Sequence[str], word: str | None
) -> int | None:
    on = [i for i, n in enumerate(nodes) if n.span in spans]
    if word:
        same = [i for i in on if nodes[i].word == word]
        if same:
            return same[0]
    return on[0] if on else None
