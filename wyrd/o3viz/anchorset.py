"""The four anchors of a bundle: placement, ast, pipeline, level."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from wyrd.o3viz import anchors

Pos = anchors.Pos


class PlaneLike(Protocol):
    ids: list[str]
    metrics: dict[str, list[float | None]]


def column(plane: PlaneLike, name: str) -> dict[str, float]:
    vals = plane.metrics.get(name, [])
    return {i: v for i, v in zip(plane.ids, vals, strict=False) if v is not None}


def packed(
    pos: Mapping[str, Mapping[str, Pos]], unanchored: Sequence[str], bounds: Sequence[float]
) -> dict[str, Any]:
    return {
        "bounds": list(bounds),
        "unanchored": list(unanchored),
        "pos": {p: {i: list(xy) for i, xy in d.items()} for p, d in pos.items()},
    }


def column_anchor(
    order: Sequence[str],
    planes: Mapping[str, PlaneLike],
    ulinks: Sequence[tuple[str, str]],
    parent: Mapping[str, str],
    edges: Sequence[tuple[str, str]],
    value: str,
    key: str,
) -> dict[str, Any]:
    """x = the metric `value` (columns of squares), ordered inside a column by metric `key`;
    planes without that metric take the centroid of what they link to."""
    seed: dict[str, Pos] = {}
    for p in ("lut", "placed"):
        if p in planes:
            vals = {i: int(v) for i, v in column(planes[p], value).items()}
            seed.update(anchors.column_layout(vals, column(planes[p], key)))
    ids = {p: planes[p].ids for p in order}
    xs = [p[0] for p in seed.values()] or [0.0]
    ys = [p[1] for p in seed.values()] or [0.0]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    pos, un = anchors.placement_anchor(order, ids, ulinks, seed, centre, parent, edges)
    pos = anchors.strip_unanchored(pos, un)
    return packed(pos, un, anchors.bounds_of(pos))


def ast_anchor(
    order: Sequence[str],
    planes: Mapping[str, PlaneLike],
    ulinks: Sequence[tuple[str, str]],
    parent: Mapping[str, str],
) -> dict[str, Any]:
    ids = {p: planes[p].ids for p in order}
    tree = anchors.tidy_tree(planes["hdl"].ids, parent)
    depth = {i: int(v) for i, v in column(planes["hdl"], "depth").items()}
    xs = [p[0] for p in tree.values()] or [0.0]
    centre = ((min(xs) + max(xs)) / 2, -1.0)
    pos, un = anchors.top_down_anchor(order, ids, ulinks, tree, "hdl", depth, centre)
    pos = anchors.strip_unanchored(pos, un)
    return packed(pos, un, anchors.bounds_of(pos))


def compute_all(
    order: Sequence[str],
    planes: Mapping[str, PlaneLike],
    links: Sequence[tuple[str, str, str, str]],
    edges: Sequence[tuple[str, str, str]],
    parent: Mapping[str, str],
    bottom: Mapping[str, Pos],
    fallback: Mapping[str, Pos],
    grid: tuple[int, int],
) -> dict[str, dict[str, Any]]:
    ulinks = [(a, b) for a, b, _, _ in links]
    e2 = [(a, b) for a, b, _ in edges]
    ids = {p: planes[p].ids for p in order}
    centre = ((grid[0] + 1) / 2, (grid[1] + 1) / 2)
    pos, un = anchors.placement_anchor(order, ids, ulinks, bottom, centre, parent, e2, fallback)
    pos = anchors.strip_unanchored(pos, un)
    b = anchors.bounds_of(pos, 0.0)
    box = [min(b[0], 0), min(b[1], 0), max(b[2], grid[0] + 1), max(b[3], grid[1] + 1)]
    out = {"placement": packed(pos, un, box)}
    out["ast"] = ast_anchor(order, planes, ulinks, parent)
    out["pipeline"] = column_anchor(order, planes, ulinks, parent, e2, "stage", "logic_level")
    out["level"] = column_anchor(order, planes, ulinks, parent, e2, "logic_level", "slack_worst")
    return out
