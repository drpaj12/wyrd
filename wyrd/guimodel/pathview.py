"""Path view model (Qt-free): the near-critical cut-off, the source-view overlay of one path or of
the union of the near-critical paths through an object, and the step rows of the Paths panel.

Data comes from the Mímir schema 6 tables via ``mimirview.MimirView.paths_through`` and
``path_detail``. Spec: docs/specs/2026-10-28-path-view.md.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from wyrd.mimirview import PathNodeRow

CUTOFFS: tuple[float | None, ...] = (0.90, 0.95, 0.99, None)
CUTOFF_LABELS = ("0.90", "0.95", "0.99", "off")
DEFAULT_CUTOFF_INDEX = 0
UNION_THETA = 0.90
STEP_HEADERS = ["Step", "Location", "Word[bit]", "Module", "Delay (ns)"]
PATH_HEADERS = ["Rank", "Crit", "Slack (ns)", "Startpoint -> Endpoint", "Nodes"]


def cutoff_at(index: int) -> float | None:
    """The cut-off for a combo index; anything unreadable is the default."""
    return CUTOFFS[index] if 0 <= index < len(CUTOFFS) else CUTOFFS[DEFAULT_CUTOFF_INDEX]


def cutoff_index(raw: object) -> int:
    """Index of a stored setting (the label text); anything unreadable is the default."""
    text = str(raw)
    return CUTOFF_LABELS.index(text) if text in CUTOFF_LABELS else DEFAULT_CUTOFF_INDEX


def cutoff_header(cutoff: float | None) -> str:
    if cutoff is None:
        return "showing all stored paths (cut-off off)"
    return f"showing paths with crit >= {cutoff:.2f}"


def visible(crit: float | None, cutoff: float | None) -> bool:
    """True when a path of this crit is shown: no cut-off shows all, a path without a crit is
    shown only then."""
    if cutoff is None:
        return True
    return crit is not None and round(crit, 9) >= cutoff


def union_theta(cutoff: float | None) -> float:
    """The threshold of the 'all paths through here' union: 0.90 or the cut-off when higher."""
    return max(UNION_THETA, cutoff) if cutoff is not None else UNION_THETA


@dataclass(frozen=True)
class Overlay:
    """What the source view draws for one file: the lines on the path(s), the step markers
    (path mode) or a heat colour per line (union mode); every other line is dimmed."""

    steps: dict[int, list[tuple[int, float]]] = field(default_factory=dict)
    colors: dict[int, float] = field(default_factory=dict)
    union: bool = False

    def lines(self) -> set[int]:
        return set(self.steps) | set(self.colors)

    def marker(self, line: int) -> str:
        """Gutter text of a line: its step numbers and their summed delay."""
        got = self.steps.get(line)
        if not got:
            return ""
        return f"{','.join(str(s) for s, _ in got)} {sum(d for _, d in got):.2f}"


def path_overlay(
    nodes: Sequence[PathNodeRow],
    crit: float | None,
    in_file: Callable[[str], bool],
    cutoff: float | None,
) -> Overlay:
    """Step markers of one path in the open file (``in_file`` tells a span file from it). A path
    below the cut-off gives nothing."""
    if not visible(crit, cutoff):
        return Overlay()
    steps: dict[int, list[tuple[int, float]]] = {}
    for n in nodes:
        where = n.file_line
        if where is not None and in_file(where[0]):
            steps.setdefault(where[1], []).append((n.step, n.delay_ns))
    return Overlay(steps)


def union_overlay(
    paths: Sequence[tuple[float | None, Sequence[PathNodeRow]]],
    in_file: Callable[[str], bool],
    cutoff: float | None,
) -> Overlay:
    """Lines of the near-critical paths, each coloured by the largest crit among them. Paths
    below ``union_theta(cutoff)`` count for nothing."""
    theta = union_theta(cutoff)
    colors: dict[int, float] = {}
    for crit, nodes in paths:
        if crit is None or round(crit, 9) < theta:
            continue
        for n in nodes:
            where = n.file_line
            if where is not None and in_file(where[0]):
                colors[where[1]] = max(colors.get(where[1], 0.0), crit)
    return Overlay({}, colors, True)


Query = tuple[tuple[str, ...], str | None, int | None]
"""(spans, word, bit): paths through any of the spans (``file:line``) that also touch the word and
bit; no span means the word anywhere."""


def click_queries(spans: Sequence[str], word: str | None, bit: int | None) -> list[Query]:
    """What to ask for a clicked token, most specific first; the first query that finds paths
    wins: the bit of the word on the line, the word on the line, then the line."""
    here = tuple(spans)
    out: list[Query] = []
    if word:
        if bit is not None:
            out.append((here, word, bit))
        out.append((here, word, None))
    out.append((here, None, None))
    return out


def word_text(n: PathNodeRow) -> str:
    if not n.word:
        return ""
    return f"{n.word}[{n.bit}]" if n.bit >= 0 and n.word_via in ("name", "pad") else n.word


def step_cells(n: PathNodeRow) -> list[str]:
    where = n.file_line
    place = f"{where[0].rsplit('/', 1)[-1]}:{where[1]}" if where else f"({n.block_type or 'I/O'})"
    return [str(n.step), place, word_text(n), n.module, f"{n.delay_ns:.3f}"]


def path_cells(rank: int, crit: float | None, slack: float | None, start: str, end: str,
               nodes: int) -> list[str]:  # fmt: skip
    c = "n/a" if crit is None else f"{crit:.3f}"
    s = "n/a" if slack is None else f"{slack:.3f}"
    return [str(rank), c, s, f"{_short(start)} -> {_short(end)}", str(nodes)]


def _short(point: str) -> str:
    """A start or end point without its '(block clocked by clk)' tail."""
    return point.split(" (", 1)[0]
