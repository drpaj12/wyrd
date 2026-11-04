"""Anchors: an (x, y) per object per plane.

M1 has the `placement` anchor: the bottom plane is the real grid, every upper plane sits at the
centroid of the objects below it that it links to.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

Pos = tuple[float, float]


def tile_spread(members: Mapping[tuple[int, int], Sequence[str]]) -> dict[str, Pos]:
    """Spread the objects of each grid tile on a small square sub-grid inside it (sorted by id)."""
    out: dict[str, Pos] = {}
    for (x, y), ids in sorted(members.items()):
        ordered = sorted(ids)
        side = 1
        while side * side < len(ordered):
            side += 1
        step = 0.8 / side
        for i, oid in enumerate(ordered):
            col, row = i % side, i // side
            out[oid] = (
                round(x - 0.4 + step * (col + 0.5), 4),
                round(y - 0.4 + step * (row + 0.5), 4),
            )
    return out


def mean(points: Sequence[Pos]) -> Pos:
    n = len(points)
    return (round(sum(p[0] for p in points) / n, 4), round(sum(p[1] for p in points) / n, 4))


def placement_anchor(
    order: Sequence[str],
    ids: Mapping[str, Sequence[str]],
    links: Sequence[tuple[str, str]],
    bottom: Mapping[str, Pos],
    centre: Pos,
    tree_parent: Mapping[str, str] | None = None,
    edges: Sequence[tuple[str, str]] = (),
    fallback: Mapping[str, Pos] | None = None,
) -> tuple[dict[str, dict[str, Pos]], list[str]]:
    """Positions per plane (order is top to bottom) and the ids that had no link-derived position.

    `links` are (upper id, lower id) pairs. An id with no linked lower object takes the mean of its
    children in `tree_parent` (child -> parent, same plane), then its own `fallback` position (a
    cluster's tile), then the mean of its netlist neighbours already placed, then the grid centre.
    Those last three cases are returned as unanchored.
    """
    plane_of = {oid: p for p, lst in ids.items() for oid in lst}
    rank = {p: i for i, p in enumerate(order)}
    below: dict[str, list[str]] = defaultdict(list)
    for up, lo in links:
        if up in plane_of and lo in plane_of and rank[plane_of[lo]] > rank[plane_of[up]]:
            below[up].append(lo)
    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in (tree_parent or {}).items():
        children[parent].append(child)
    nbrs: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        nbrs[a].append(b)
        nbrs[b].append(a)

    fb = fallback or {}
    pos: dict[str, Pos] = dict(bottom)
    unanchored: list[str] = []
    for plane in reversed(order[:-1]):
        todo = [oid for oid in ids[plane] if oid not in pos]
        for oid in todo:
            by_plane: dict[int, list[Pos]] = defaultdict(list)
            for lo in below.get(oid, ()):
                if lo in pos:
                    by_plane[rank[plane_of[lo]]].append(pos[lo])
            if by_plane:
                pos[oid] = mean(by_plane[max(by_plane)])
        for oid in sorted(todo, key=lambda o: -_depth(o, tree_parent or {})):
            if oid not in pos:
                kids = [pos[c] for c in children.get(oid, ()) if c in pos]
                if kids:
                    pos[oid] = mean(kids)
        for oid in todo:
            if oid not in pos and oid in fb:
                pos[oid] = fb[oid]
        for oid in todo:
            if oid not in pos:
                near = [pos[n] for n in nbrs.get(oid, ()) if n in pos]
                pos[oid] = mean(near) if near else centre
                unanchored.append(oid)
    for oid in ids[order[-1]]:
        if oid not in pos:
            pos[oid] = centre
            unanchored.append(oid)
    return {p: {oid: pos[oid] for oid in ids[p]} for p in order}, sorted(set(unanchored))


def _depth(oid: str, parent: Mapping[str, str]) -> int:
    d = 0
    while oid in parent and d < 10_000:
        oid = parent[oid]
        d += 1
    return d
