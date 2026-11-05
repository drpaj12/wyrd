"""Hutton and Kundarewich layouts and cluster sources for a bundle (stdlib only)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from wyrd.o3viz import anchors, anchorset, blif, circuit, hutton

Pos = anchors.Pos


def band_anchor(
    order: Sequence[str],
    planes: Mapping[str, anchorset.PlaneLike],
    ulinks: Sequence[tuple[str, str]],
    parent: Mapping[str, str],
    edges: Sequence[tuple[str, str]],
    band: Mapping[str, int],
    top: str,
    kind: str,
) -> dict[str, Any]:
    """x = delay level, one strip per band (all one, a sequential level, or a cluster); flip-flops
    sit at level 0 with the primary inputs and are not attached to their driver."""
    lut, placed = planes["lut"], planes["placed"]
    level = {i: int(v) for i, v in anchorset.column(lut, "logic_level").items() if i in band}
    pos, labels = circuit.grid_layout(level, band, anchorset.column(lut, "slack_worst"))
    labels = [x for x in labels if kind or "band" not in x]
    seed = dict(pos)
    for pid, name in zip(placed.ids, placed.name, strict=True):
        if (lid := f"luts:{top}/{name}") in pos:
            seed[pid] = pos[lid]
    xs = [p[0] for p in seed.values()] or [0.0]
    zs = [p[1] for p in seed.values()] or [0.0]
    centre = ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2)
    ids = {p: planes[p].ids for p in order}
    out, un = anchors.placement_anchor(order, ids, ulinks, seed, centre, parent, edges)
    out = anchors.strip_unanchored(out, un)
    res = anchorset.packed(out, un, anchors.bounds_of(out, 2.0))
    res.update({"ff_attached": False, "labels": labels, "band_kind": kind, "step": circuit.STEP})
    return res


def node_columns(nl: blif.Netlist, nets: Sequence[str | None]) -> dict[str, list[float | None]]:
    """Measured Hutton columns for a plane whose objects are the nets `nets` (None: no net)."""
    seq = hutton.seq_levels(nl)
    latched = hutton.latched_nodes(nl)
    cfan = hutton.comb_fanout(nl)

    def col(f: Mapping[str, float]) -> list[float | None]:
        return [float(f[n]) if n is not None and n in f else None for n in nets]

    return {
        "seq_level": col(seq),
        "is_latched": [1.0 if n in latched else None for n in nets],
        "is_po": [1.0 if n in nl.primary_outputs else None for n in nets],
        "fanout_comb": col(cfan),
    }


def build(
    order: Sequence[str],
    planes: Mapping[str, Any],
    links: Sequence[tuple[str, str, str, str]],
    edges: Sequence[tuple[str, str, str]],
    parent: Mapping[str, str],
    nl: blif.Netlist,
    top: str,
    k: int | None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """clusters.json and the extra anchor sets: hutton, hutton_seq, kundarewich-<source>."""
    lut = planes["lut"]
    pre = f"luts:{top}/"
    nets = [i[len(pre) :] if i.startswith(pre) else None for i in lut.ids]
    h = planes["hdl"]
    hdl = circuit.Hdl(h.ids, h.type, h.name, h.src, parent)
    clb_names = dict(zip(planes["clb"].ids, planes["clb"].name, strict=True))
    clusters = circuit.build_sources(nl, lut.ids, nets, hdl, links, clb_names, k)
    ulinks = [(a, b) for a, b, _, _ in links]
    e2 = [(a, b) for a, b, _ in edges]
    sets: dict[str, dict[str, Any]] = {}
    sets["hutton"] = band_anchor(
        order, planes, ulinks, parent, e2, {i: 0 for i in lut.ids}, top, ""
    )
    seq = dict(zip(lut.ids, lut.metrics.get("seq_level", []), strict=False))
    sets["hutton_seq"] = band_anchor(
        order,
        planes,
        ulinks,
        parent,
        e2,
        {i: int(v) for i, v in seq.items() if v is not None},
        top,
        "seq",
    )
    for key, src in clusters["sources"].items():
        band = dict(zip(lut.ids, src["of"], strict=True))
        a = band_anchor(order, planes, ulinks, parent, e2, band, top, "cluster")
        a["source"] = key
        sets[f"kundarewich-{key}"] = a
    clusters["pis"] = hutton.characterize(nl)["pis"]
    return clusters, sets
