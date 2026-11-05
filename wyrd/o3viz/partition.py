"""Min-cut partition into k clusters: recursive Fiduccia-Mattheyses bipartition (standard library).

Kundarewich (2002, section 3.2) took the natural hierarchy of a circuit from hMETIS; this stands in
for it without a new install. Cells are objects, nets are hyperedges (a driver and its sinks). The
result is deterministic for a given seed. It is a heuristic: the cut is small, not proven minimal.
"""

from __future__ import annotations

import heapq
import random
from collections.abc import Mapping, Sequence

Net = Sequence[str]


def cut_size(nets: Sequence[Net], side: Mapping[str, int]) -> int:
    """Nets with cells on both sides."""
    return sum(1 for n in nets if len({side[c] for c in n}) > 1)


def _gain(
    c: str, side: Mapping[str, int], cnt: Sequence[list[int]], inc: Mapping[str, list[int]]
) -> int:
    s, g = side[c], 0
    for e in inc[c]:
        if cnt[e][s] == 1:
            g += 1
        if cnt[e][1 - s] == 0:
            g -= 1
    return g


def _pass(
    cells: Sequence[str],
    nets: Sequence[Net],
    inc: Mapping[str, list[int]],
    side: dict[str, int],
    lo: int,
    hi: int,
) -> int:
    """One FM pass: move every cell once, keep the best prefix. Returns the cut gain (>= 0)."""
    cnt = [[0, 0] for _ in nets]
    for e, n in enumerate(nets):
        for c in n:
            cnt[e][side[c]] += 1
    gain = {c: _gain(c, side, cnt, inc) for c in cells}
    heap = [(-g, i, c) for i, (c, g) in enumerate((c, gain[c]) for c in cells)]
    heapq.heapify(heap)
    size0 = sum(1 for c in cells if side[c] == 0)
    locked: set[str] = set()
    moves: list[str] = []
    total = best = best_at = 0
    stash: list[tuple[int, int, str]] = []
    order = {c: i for i, c in enumerate(cells)}
    while heap:
        ng, i, c = heapq.heappop(heap)
        if c in locked or -ng != gain[c]:
            continue
        new0 = size0 + (1 if side[c] == 1 else -1)
        if not lo <= new0 <= hi:
            stash.append((ng, i, c))
            continue
        for item in stash:
            heapq.heappush(heap, item)
        stash.clear()
        total += gain[c]
        src = side[c]
        locked.add(c)
        moves.append(c)
        size0 = new0
        touched: set[str] = set()
        for e in inc[c]:
            f_old, t_old = cnt[e][src], cnt[e][1 - src]
            cnt[e][src] -= 1
            cnt[e][1 - src] += 1
            if f_old <= 2 or t_old <= 1:
                touched.update(p for p in nets[e] if p not in locked)
        side[c] = 1 - src
        for p in touched:
            g = _gain(p, side, cnt, inc)
            if g != gain[p]:
                gain[p] = g
            heapq.heappush(heap, (-g, order[p], p))
        if total > best:
            best, best_at = total, len(moves)
    for c in moves[best_at:]:
        side[c] = 1 - side[c]
    return best


def bipartition(
    cells: Sequence[str], nets: Sequence[Net], frac: float, rng: random.Random, tol: float = 0.1
) -> dict[str, int]:
    """Side 0 or 1 per cell; side 0 holds about `frac` of the cells (within `tol`, at least one)."""
    n = len(cells)
    target = max(1, min(n - 1, round(n * frac)))
    slack = max(1, int(tol * n))
    lo, hi = max(1, target - slack), min(n - 1, target + slack)
    mixed = list(cells)
    rng.shuffle(mixed)
    side = {c: (0 if k < target else 1) for k, c in enumerate(mixed)}
    inc: dict[str, list[int]] = {c: [] for c in cells}
    for e, net in enumerate(nets):
        for c in net:
            inc[c].append(e)
    for _ in range(30):
        if _pass(cells, nets, inc, side, lo, hi) <= 0:
            break
    return side


def _restrict(nets: Sequence[Net], keep: set[str]) -> list[list[str]]:
    out = []
    for n in nets:
        sub = [c for c in n if c in keep]
        if len(sub) > 1:
            out.append(sub)
    return out


def partition(cells: Sequence[str], nets: Sequence[Net], k: int, seed: int = 1) -> dict[str, int]:
    """Cluster index 0..k-1 per cell by recursive bipartition (k is capped at the cell count)."""
    base = sorted(set(cells))
    k = max(1, min(k, len(base)))
    rng = random.Random(seed)
    out: dict[str, int] = {}
    stack: list[tuple[list[str], list[list[str]], int, int]] = [
        (base, [sorted(set(n)) for n in nets if len(set(n)) > 1], k, 0)
    ]
    while stack:
        part, pnets, kk, first = stack.pop()
        if kk == 1 or len(part) <= 1:
            out.update({c: first for c in part})
            continue
        k0 = kk // 2
        side = bipartition(part, pnets, k0 / kk, rng)
        a = [c for c in part if side[c] == 0]
        b = [c for c in part if side[c] == 1]
        stack.append((b, _restrict(pnets, set(b)), kk - k0, first + k0))
        stack.append((a, _restrict(pnets, set(a)), k0, first))
    return out
