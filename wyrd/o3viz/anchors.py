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


def bounds_of(pos: Mapping[str, Mapping[str, Pos]], margin: float = 1.0) -> list[float]:
    """[xmin, ymin, xmax, ymax] over every plane, with a margin."""
    pts = [p for plane in pos.values() for p in plane.values()]
    if not pts:
        return [0.0, 0.0, 1.0, 1.0]
    return [
        round(min(p[0] for p in pts) - margin, 4),
        round(min(p[1] for p in pts) - margin, 4),
        round(max(p[0] for p in pts) + margin, 4),
        round(max(p[1] for p in pts) + margin, 4),
    ]


def tidy_tree(
    ids: Sequence[str], parent: Mapping[str, str], dx: float = 1.4, dy: float = 1.8
) -> dict[str, Pos]:
    """Layered tree: leaves in id order at x = k * dx, a parent over the mean of its children,
    y = -depth * dy (the root on top)."""
    kids: dict[str, list[str]] = defaultdict(list)
    for oid in ids:
        if oid in parent and parent[oid] in set(ids):
            kids[parent[oid]].append(oid)
    roots = [oid for oid in ids if oid not in parent or parent[oid] not in set(ids)]
    out: dict[str, Pos] = {}
    nxt = 0.0
    for root in roots:
        stack: list[tuple[str, int, bool]] = [(root, 0, False)]
        while stack:
            oid, depth, done = stack.pop()
            if not done:
                stack.append((oid, depth, True))
                stack.extend((c, depth + 1, False) for c in reversed(kids.get(oid, [])))
                continue
            if kids.get(oid):
                x = sum(out[c][0] for c in kids[oid]) / len(kids[oid])
            else:
                x = nxt
                nxt += dx
            out[oid] = (round(x, 4), round(-depth * dy, 4))
    return out


def spread_same(pos: Mapping[str, Pos], size: float) -> dict[str, Pos]:
    """Objects at one identical position are spread on a small square sub-grid of the given size."""
    groups: dict[Pos, list[str]] = defaultdict(list)
    for oid, p in pos.items():
        groups[p].append(oid)
    out: dict[str, Pos] = {}
    for (x, y), members in sorted(groups.items()):
        ordered = sorted(members)
        side = 1
        while side * side < len(ordered):
            side += 1
        step = size / side
        for i, oid in enumerate(ordered):
            col, row = i % side, i // side
            out[oid] = (
                round(x - size / 2 + step * (col + 0.5), 4),
                round(y - size / 2 + step * (row + 0.5), 4),
            )
    return out


def column_layout(
    values: Mapping[str, int], keys: Mapping[str, float], gap: float = 1.5
) -> dict[str, Pos]:
    """One square block per value, blocks left to right; inside a block objects are ordered by
    (key, id), objects without a key last."""
    cols: dict[int, list[str]] = defaultdict(list)
    for oid, v in values.items():
        cols[v].append(oid)
    out: dict[str, Pos] = {}
    x0 = 0.0
    for v in sorted(cols):
        members = sorted(cols[v], key=lambda o: (keys.get(o) is None, keys.get(o, 0.0), o))
        side = 1
        while side * side < len(members):
            side += 1
        for i, oid in enumerate(members):
            out[oid] = (round(x0 + (i % side) * 0.6, 4), round((i // side) * 0.6, 4))
        x0 += side * 0.6 + gap
    return out


def top_down_anchor(
    order: Sequence[str],
    ids: Mapping[str, Sequence[str]],
    links: Sequence[tuple[str, str]],
    seed: Mapping[str, Pos],
    seed_plane: str,
    tree_depth: Mapping[str, int],
    centre: Pos,
    fallback: Mapping[str, Pos] | None = None,
) -> tuple[dict[str, dict[str, Pos]], list[str]]:
    """Positions with the seed plane fixed: an object below takes the position of what it links up
    to. From the seed plane it takes the deepest linked object; from other planes the mean. It uses
    the highest plane (nearest the seed) that has a positioned linked object."""
    plane_of = {oid: p for p, lst in ids.items() for oid in lst}
    rank = {p: i for i, p in enumerate(order)}
    above: dict[str, list[str]] = defaultdict(list)
    for up, lo in links:
        if up in plane_of and lo in plane_of and rank[plane_of[up]] < rank[plane_of[lo]]:
            above[lo].append(up)
    pos: dict[str, Pos] = dict(seed)
    unanchored: list[str] = []
    fb = fallback or {}
    for plane in order[rank[seed_plane] + 1 :]:
        raw: dict[str, Pos] = {}
        for oid in ids[plane]:
            by_plane: dict[int, list[str]] = defaultdict(list)
            for u in above.get(oid, ()):
                if u in pos:
                    by_plane[rank[plane_of[u]]].append(u)
            if by_plane:
                top = min(by_plane)
                ups = by_plane[top]
                if order[top] == seed_plane:
                    best = max(tree_depth.get(u, 0) for u in ups)
                    ups = [u for u in ups if tree_depth.get(u, 0) == best]
                raw[oid] = mean([pos[u] for u in ups])
            elif oid in fb:
                raw[oid] = fb[oid]
            else:
                raw[oid] = centre
                unanchored.append(oid)
        pos.update(spread_same(raw, 0.9))
    return {p: {oid: pos[oid] for oid in ids[p]} for p in order}, sorted(set(unanchored))


def strip_unanchored(
    pos: dict[str, dict[str, Pos]], unanchored: Sequence[str], step: float = 0.6
) -> dict[str, dict[str, Pos]]:
    """Move objects that have no position of their own to a strip below the plane, so a guess at the
    centre is never mistaken for a measurement."""
    if not unanchored:
        return pos
    bad = set(unanchored)
    keep = [p for plane in pos.values() for i, p in plane.items() if i not in bad]
    xs = [p[0] for p in keep] or [0.0]
    ys = [p[1] for p in keep] or [0.0]
    width = max(xs) - min(xs)
    per_row = max(1, int(width / step) + 1)
    out: dict[str, dict[str, Pos]] = {}
    for name, plane in pos.items():
        mine = sorted(i for i in plane if i in bad)
        moved = {
            i: (
                round(min(xs) + (k % per_row) * step, 4),
                round(min(ys) - 1.8 - (k // per_row) * step, 4),
            )
            for k, i in enumerate(mine)
        }
        out[name] = {i: moved.get(i, p) for i, p in plane.items()}
    return out
