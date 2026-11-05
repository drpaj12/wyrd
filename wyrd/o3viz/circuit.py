"""Cluster sources, Comb and Latched matrices, and the Hutton and Kundarewich layouts (stdlib only).

Kundarewich (2002) sections 3.2 and 3.3.2: a partition of the circuit into k clusters; Comb[i][j]
counts the connections from cluster i that drive combinational nodes in cluster j, Latched[i][j]
those that drive flip-flops in cluster j. Cluster sources here: the HDL hierarchy (from
provenance), VPR's clusters, and a min-cut partition (partition.py).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from wyrd.o3viz import anchors, blif, hutton, partition

Pos = anchors.Pos
Link = tuple[str, str, str, str]
HDL_LEVELS = ("module", "block", "item")
STEP = 0.6  # distance between neighbouring objects in the Hutton layouts
MAX_NAMED = 48  # a source with more clusters than this is not exported (unreadable matrix)


def span_key(span: str) -> tuple[int, int]:
    """Size of an HDL span "l0.c0-l1.c1" as (lines, columns of the last line) for ordering."""
    m = re.fullmatch(r"(\d+)\.(\d+)-(\d+)\.(\d+)", span or "")
    if not m:
        return (10**9, 0)
    l0, c0, l1, c1 = (int(x) for x in m.groups())
    return (l1 - l0, (l1 - l0) * 1000 + c1 - c0)


class Hdl:
    """The HDL constructs of a bundle: type, parent, span size, name."""

    def __init__(
        self,
        ids: Sequence[str],
        types: Sequence[str],
        names: Sequence[str],
        src: Sequence[Sequence[Sequence[str]]],
        parent: Mapping[str, str],
    ) -> None:
        self.type = dict(zip(ids, types, strict=True))
        self.name = dict(zip(ids, names, strict=True))
        self.span = {i: (s[0][1] if s else "") for i, s in zip(ids, src, strict=True)}
        self.parent = {k: v for k, v in parent.items() if k in self.type}

    def chain(self, oid: str) -> list[str]:
        out = [oid]
        while out[-1] in self.parent and len(out) < 10_000:
            out.append(self.parent[out[-1]])
        return out

    def is_level(self, oid: str, level: str) -> bool:
        if level == "module":
            return self.type.get(oid) == "module"
        if level == "block":
            return self.type.get(self.parent.get(oid, "")) == "module"
        return self.type.get(oid) == "branch"

    def label(self, oid: str) -> str:
        sp = self.span.get(oid, "")
        lines = re.sub(r"\.\d+", "", sp) if sp else ""
        nm = self.name.get(oid, oid)
        return (
            f"{self.type.get(oid, '')} {nm} L{lines}" if lines else f"{self.type.get(oid, '')} {nm}"
        )


def hdl_clusters(
    hdl: Hdl, lut_ids: Sequence[str], lut_hdl: Mapping[str, Sequence[str]], level: str
) -> dict[str, Any]:
    """Cluster per LUT-plane object from provenance.

    Candidates are the constructs the object links to, plus their ancestors, at the granularity:
    module, block (a direct child of a module: an always block, an assign, an instance) or item (a
    case item or if/else branch; objects with none fall back to their block). An object with
    several candidates takes the one with the smallest span, and is counted as ambiguous.
    """
    pick: dict[str, str] = {}
    ambiguous = fallback = 0
    for lid in lut_ids:
        cand_all = {c for h in lut_hdl.get(lid, ()) for c in hdl.chain(h)}
        cand = sorted(c for c in cand_all if hdl.is_level(c, level))
        if not cand and level == "item":
            cand = sorted(c for c in cand_all if hdl.is_level(c, "block"))
            fallback += 1 if cand else 0
        if not cand:
            continue
        ambiguous += 1 if len(cand) > 1 else 0
        pick[lid] = min(cand, key=lambda c: (span_key(hdl.span.get(c, "")), c))
    used = sorted(set(pick.values()), key=lambda c: (_start(hdl.span.get(c, "")), c))
    index = {c: k for k, c in enumerate(used)}
    return {
        "names": [hdl.label(c) for c in used],
        "construct": used,
        "of": [index.get(pick.get(lid, "")) for lid in lut_ids],
        "ambiguous": ambiguous,
        "fallback": fallback,
    }


def _start(span: str) -> tuple[int, int]:
    m = re.match(r"(\d+)\.(\d+)", span or "")
    return (int(m.group(1)), int(m.group(2))) if m else (10**9, 0)


def vpr_clusters(
    lut_ids: Sequence[str], links: Sequence[Link], clb_names: Mapping[str, str]
) -> dict[str, Any]:
    owner: dict[str, str] = {}
    for a, b, _k, _c in links:
        if a in clb_names or not b.startswith("clb:"):
            continue
        if a.startswith("luts:"):
            owner.setdefault(a, b)
    used = sorted(set(owner.values()))
    index = {c: k for k, c in enumerate(used)}
    return {
        "names": [clb_names.get(c, c) for c in used],
        "construct": [None] * len(used),
        "of": [index.get(owner.get(lid, "")) for lid in lut_ids],
    }


def netlist_nets(nl: blif.Netlist, cells: set[str]) -> list[list[str]]:
    """Hyperedges over the cells: a net's driver (if a cell) and the cells that read it."""
    sinks: dict[str, list[str]] = defaultdict(list)
    for net in sorted(nl.inputs):
        if net in cells:
            for s in sorted(set(nl.inputs[net])):
                sinks[s].append(net)
    out = []
    for src in sorted(sinks):
        pins = sorted(set(sinks[src] + ([src] if src in cells else [])))
        if len(pins) > 1:
            out.append(pins)
    return out


def mincut_clusters(
    nl: blif.Netlist, lut_nets: Sequence[str | None], k: int, seed: int = 1
) -> dict[str, Any]:
    used = hutton.objects(nl)
    cells = {n for n in lut_nets if n is not None and n in used}
    got = partition.partition(sorted(cells), netlist_nets(nl, cells), k, seed)
    kk = len(set(got.values()))
    cut = partition.cut_size(netlist_nets(nl, cells), got) if cells else 0
    return {
        "names": [f"part {i}" for i in range(kk)],
        "construct": [None] * kk,
        "of": [got.get(n) if n is not None else None for n in lut_nets],
        "cut": cut,
        "seed": seed,
    }


def matrices(
    nl: blif.Netlist, lut_nets: Sequence[str | None], of: Sequence[int], k: int
) -> tuple[list[list[int]], list[list[int]]]:
    """Comb and Latched (Kundarewich 3.3.2). `of` is a full assignment, 0..k-1 per object."""
    cl = {n: c for n, c in zip(lut_nets, of, strict=True) if n is not None}
    comb = [[0] * k for _ in range(k)]
    latched = [[0] * k for _ in range(k)]
    for net in sorted(cl):
        for s in sorted(set(nl.inputs.get(net, ()))):
            if s not in cl:
                continue
            (latched if nl.drivers[net] == "latch" else comb)[cl[s]][cl[net]] += 1
    return comb, latched


def shape_by_cluster(
    nl: blif.Netlist, lut_nets: Sequence[str | None], of: Sequence[int], k: int, dmax: int
) -> list[list[int]]:
    level = nl.levels()
    out = [[0] * (dmax + 1) for _ in range(k)]
    for n, c in zip(lut_nets, of, strict=True):
        if n is not None:
            out[c][min(level.get(n, 0), dmax)] += 1
    return out


def nmi(a: Sequence[int], b: Sequence[int]) -> float | None:
    """Normalised mutual information of two partitions of one object set (0 unrelated, 1 same)."""
    n = len(a)
    if n == 0:
        return None
    pa: dict[int, int] = defaultdict(int)
    pb: dict[int, int] = defaultdict(int)
    pab: dict[tuple[int, int], int] = defaultdict(int)
    for x, y in zip(a, b, strict=True):
        pa[x] += 1
        pb[y] += 1
        pab[(x, y)] += 1
    ha = -sum(c / n * math.log(c / n) for c in pa.values())
    hb = -sum(c / n * math.log(c / n) for c in pb.values())
    if ha == 0 or hb == 0:
        return None
    mi = sum(c / n * math.log(c * n / (pa[x] * pb[y])) for (x, y), c in pab.items())
    return float(round(mi / math.sqrt(ha * hb), 6))


def complete(src: dict[str, Any]) -> int:
    """Give objects without a cluster the last index (named "(none)"); returns k."""
    k = len(src["names"])
    if any(c is None for c in src["of"]):
        src["names"] = [*src["names"], "(none)"]
        src["construct"] = [*src["construct"], None]
        src["of"] = [k if c is None else c for c in src["of"]]
        src["unassigned"] = sum(1 for c in src["of"] if c == k)
        k += 1
    else:
        src["unassigned"] = 0
    return k


def source_entry(
    nl: blif.Netlist, lut_nets: Sequence[str | None], src: dict[str, Any], label: str, dmax: int
) -> dict[str, Any]:
    k = complete(src)
    comb, latched = matrices(nl, lut_nets, src["of"], k)
    inter = sum(v for i, row in enumerate(comb) for j, v in enumerate(row) if i != j)
    inter += sum(v for i, row in enumerate(latched) for j, v in enumerate(row) if i != j)
    total = sum(map(sum, comb)) + sum(map(sum, latched))
    src.update(
        {
            "label": label,
            "k": k,
            "sizes": [src["of"].count(i) for i in range(k)],
            "comb": comb,
            "latched": latched,
            "shape": shape_by_cluster(nl, lut_nets, src["of"], k, dmax),
            "edges": total,
            "inter_edges": inter,
            "inter_pct": round(100.0 * inter / total, 3) if total else None,
        }
    )
    return src


def default_k(sources: Mapping[str, Mapping[str, Any]]) -> int:
    """Min-cut k: as many clusters as the HDL block level has, within 2 to 16."""
    blk = sources.get("hdl-block")
    n = len(blk["names"]) - (1 if blk and blk.get("unassigned") else 0) if blk else 8
    return max(2, min(16, n))


def build_sources(
    nl: blif.Netlist,
    lut_ids: Sequence[str],
    lut_nets: Sequence[str | None],
    hdl: Hdl,
    links: Sequence[Link],
    clb_names: Mapping[str, str],
    k: int | None,
    seed: int = 1,
) -> dict[str, Any]:
    """The cluster sources of a bundle (clusters.json)."""
    lut_hdl: dict[str, list[str]] = defaultdict(list)
    for a, b, _k, _c in links:
        if a in hdl.type and b.startswith("luts:"):
            lut_hdl[b].append(a)
    dmax = max((nl.levels().get(n, 0) for n in lut_nets if n is not None), default=0)
    ffs = {n for n in lut_nets if n is not None and nl.drivers.get(n) == "latch"}
    srcs: dict[str, dict[str, Any]] = {}
    for level in HDL_LEVELS:
        s = hdl_clusters(hdl, lut_ids, lut_hdl, level)
        _inherit_ff(nl, lut_nets, s["of"], ffs)
        if 2 <= len(s["names"]) <= MAX_NAMED:
            srcs[f"hdl-{level}"] = source_entry(nl, lut_nets, s, f"HDL {level}", dmax)
    v = vpr_clusters(lut_ids, links, clb_names)
    if len(v["names"]) >= 2:
        srcs["vpr"] = source_entry(nl, lut_nets, v, "VPR clusters", dmax)
    kk = k or default_k(srcs)
    if len(set(lut_nets)) > 2:
        m = mincut_clusters(nl, lut_nets, kk, seed)
        srcs["mincut"] = source_entry(nl, lut_nets, m, f"min-cut, k={kk}", dmax)
    order = list(srcs)
    pair = {
        f"{a}|{b}": nmi(srcs[a]["of"], srcs[b]["of"])
        for i, a in enumerate(order)
        for b in order[i + 1 :]
    }
    return {"order": order, "dmax": dmax, "sources": srcs, "nmi": pair}


def _inherit_ff(
    nl: blif.Netlist, lut_nets: Sequence[str | None], of: list[int | None], ffs: set[str]
) -> None:
    """A flip-flop with no HDL cluster of its own takes the cluster of the LUT driving its D."""
    at = {n: i for i, n in enumerate(lut_nets) if n is not None}
    for n in ffs:
        i = at[n]
        d = nl.inputs[n][0] if nl.inputs.get(n) else None
        if of[i] is None and d in at:
            of[i] = of[at[d]]


def grid_layout(
    level: Mapping[str, int],
    band: Mapping[str, int],
    key: Mapping[str, float],
    step: float = STEP,
    gap: float = 1.6,
) -> tuple[dict[str, Pos], list[dict[str, Any]]]:
    """x = delay level; one strip (along z) per band; inside a strip the objects of a level are
    stacked in a column that wraps. Returns positions and labels (level ticks, band names)."""
    cnt: dict[tuple[int, int], list[str]] = defaultdict(list)
    for oid, lv in level.items():
        if oid in band:
            cnt[(band[oid], lv)].append(oid)
    if not cnt:
        return {}, []
    cap = max(6, math.ceil(1.6 * math.sqrt(max(len(v) for v in cnt.values()))))
    bands = sorted({b for b, _ in cnt})
    levels = sorted({lv for _, lv in cnt})
    rows = {b: min(cap, max(len(v) for (bb, _), v in cnt.items() if bb == b)) for b in bands}
    wide = {
        lv: max(math.ceil(len(v) / rows[b]) for (b, ll), v in cnt.items() if ll == lv)
        for lv in levels
    }
    x0: dict[int, float] = {}
    x = 0.0
    for lv in levels:
        x0[lv] = x
        x += wide[lv] * step + gap
    z0: dict[int, float] = {}
    z = 0.0
    for b in bands:
        z0[b] = z
        z += rows[b] * step + gap
    pos: dict[str, Pos] = {}
    for (b, lv), members in cnt.items():
        ordered = sorted(members, key=lambda o: (key.get(o) is None, key.get(o, 0.0), o))
        for i, oid in enumerate(ordered):
            pos[oid] = (
                round(x0[lv] + (i // rows[b]) * step, 4),
                round(z0[b] + (i % rows[b]) * step, 4),
            )
    labels = [{"text": f"L{lv}", "x": round(x0[lv], 4), "z": -0.9} for lv in levels]
    labels += [{"text": str(b), "x": -1.4, "z": round(z0[b], 4), "band": b} for b in bands]
    return pos, labels
