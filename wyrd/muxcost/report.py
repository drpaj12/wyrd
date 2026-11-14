"""The mux cost report: one row per logical mux, rolled up per HDL construct. JSON schema 1."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from wyrd.muxcost import blif as blifmod
from wyrd.muxcost import construct, lateness, logical, lutcost, netlist, provmap

SCHEMA = "wyrd-mux-cost"
SCHEMA_VERSION = 1
SORTS = ("bits", "luts", "crit")


@dataclass(frozen=True)
class Inputs:
    """The files of one analysis: the word-level snapshot, the mapped BLIF and the two name maps."""

    snapshot: Path
    snapshot_map: Path
    blif: Path
    blif_map: Path
    net_timing: Path | None = None
    lut_k: int = 6
    timing_optional: bool = False
    """The timing file was found, not asked for: when no pin of it joins, say so and go on."""


class ReportError(Exception):
    """The report cannot be made; the message says why, in one line."""


def _share(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


def _timing_fields(late: lateness.Lateness | None) -> dict[str, object]:
    if late is None:
        return {"sel_crit": None, "data_crit": None, "late": None, "witness": None}
    return {
        "sel_crit": round(late.sel_crit, 6),
        "data_crit": round(late.data_crit, 6),
        "late": round(late.late, 6),
        "witness": late.witness,
    }


@dataclass
class _Ctx:
    nl: netlist.Netlist
    snap: provmap.NameMap
    attr: lutcost.Attribution
    blif: blifmod.Blif
    k: int
    crit: dict[tuple[str, int], float] | None
    names: dict[int, list[str]]
    rng: random.Random


def _row(
    ctx: _Ctx, mux: logical.Logical, where: construct.Where, total_bits: int
) -> dict[str, object]:
    cost = lutcost.cost(mux, ctx.attr, ctx.k)
    root = ctx.nl.muxes[mux.root]
    row: dict[str, object] = {
        "id": mux.root,
        "kind": root.type,
        "cells": len(mux.cells),
        "construct": where.kind,
        "file": where.file,
        "line": where.line,
        "span": where.span,
        "width": mux.width,
        "arms": len(mux.leaf_arms),
        "const_arms": mux.const_arms,
        "dup_arms": mux.dup_arms,
        "related_arms": mux.related,
        "select_width": len(mux.select),
        "mux_bits": mux.bits,
        "share": _share(mux.bits, total_bits),
        "luts": len(cost.luts),
        "luts_shared": cost.shared,
        "lut_lower_bound": cost.lower_bound,
    }
    if ctx.crit is not None:
        late = _late(ctx, mux, cost.luts)
        row.update(_timing_fields(late))
    return row


def _late(ctx: _Ctx, mux: logical.Logical, luts: frozenset[str]) -> lateness.Lateness | None:
    assert ctx.crit is not None
    nets = ctx.blif.nets
    sel = lateness.cone_leaves(ctx.nl, tuple(mux.select), ctx.names, nets)
    data = lateness.arm_nets(mux, ctx.names, nets)
    return lateness.lateness(luts, ctx.blif, ctx.crit, sel, data, ctx.rng)


def _rollup(
    rows: list[dict[str, object]],
    luts_of: dict[str, frozenset[str]],
    cells_of: dict[str, frozenset[str]],
    attr: lutcost.Attribution,
    total_bits: int,
    timing: bool,
) -> list[dict[str, object]]:
    groups: dict[tuple[str, int, str, str], list[dict[str, object]]] = {}
    for r in rows:
        key = (str(r["file"]), int(str(r["line"])), str(r["span"]), str(r["construct"]))
        groups.setdefault(key, []).append(r)
    out: list[dict[str, object]] = []
    for (file, line, span, kind), members in sorted(groups.items()):
        luts = frozenset().union(*(luts_of[str(m["id"])] for m in members))
        cells = frozenset().union(*(cells_of[str(m["id"])] for m in members))
        bits = sum(int(str(m["mux_bits"])) for m in members)
        row: dict[str, object] = {
            "construct": kind,
            "file": file,
            "line": line,
            "span": span,
            "muxes": len(members),
            "mux_bits": bits,
            "share": _share(bits, total_bits),
            "arms": sum(int(str(m["arms"])) for m in members),
            "luts": len(luts),
            "luts_shared": sum(1 for lut in luts if not attr.lut_cells[lut] <= cells),
            "lut_lower_bound": sum(int(str(m["lut_lower_bound"])) for m in members),
        }
        if timing:
            lates = [float(str(m["late"])) for m in members if m["late"] is not None]
            row["late"] = round(max(lates), 6) if lates else None
        out.append(row)
    return out


def _sort_key(sort: str, timing: bool) -> tuple[str, bool]:
    if sort == "crit" and not timing:
        raise ReportError("--sort crit needs a routed timing report (--net-timing)")
    return {"bits": ("mux_bits", False), "luts": ("luts", False), "crit": ("late", True)}[sort]


def _order(rows: list[dict[str, object]], field: str, nullable: bool) -> list[dict[str, object]]:
    def key(r: dict[str, object]) -> tuple[float, str, int, str]:
        v = r.get(field)
        num = float(str(v)) if v is not None else float("-inf") if nullable else 0.0
        return (-num, str(r["file"]), int(str(r["line"])), str(r.get("id", "")))

    return sorted(rows, key=key)


def build(inp: Inputs, sort: str = "bits", limit: int | None = None) -> dict[str, object]:
    """Analyse one design. Raise ``ReportError`` (or a reader error) when the inputs do not join."""
    try:
        return _build(inp, sort, limit)
    except (
        netlist.NetlistError,
        provmap.MapError,
        blifmod.BlifError,
        lateness.TimingFileError,
    ) as e:
        raise ReportError(str(e)) from e


def _build(inp: Inputs, sort: str, limit: int | None) -> dict[str, object]:
    nl = netlist.load(inp.snapshot)
    snap, final = provmap.read(inp.snapshot_map), provmap.read(inp.blif_map)
    lutcost.require_uid(snap)
    lutcost.require_uid(final)
    blif = blifmod.read(inp.blif)
    attr = lutcost.attribute(blif, final, lutcost.uid_cells(nl, snap))
    groups = logical.group(nl)
    total_bits = sum(g.bits for g in groups)
    notes: list[str] = []
    crit = _load_crit(inp, blif, notes)
    ctx = _Ctx(
        nl, snap, attr, blif, inp.lut_k, crit, lateness.bit_names(nl), random.Random(lateness.SEED)
    )
    rows = [
        _row(ctx, g, construct.of_cell(snap, g.root, nl.muxes[g.root].src), total_bits)
        for g in groups
    ]
    luts_of = {g.root: lutcost.cost(g, attr, inp.lut_k).luts for g in groups}
    cells_of = {g.root: frozenset(g.cells) for g in groups}
    cons = _rollup(rows, luts_of, cells_of, attr, total_bits, crit is not None)
    field, nullable = _sort_key(sort, crit is not None)
    rows = _order(rows, field, nullable)
    cons = _order(cons, field if field != "late" else "late", nullable)
    return _document(inp, nl, blif, attr, groups, crit, (rows, cons), (sort, limit), notes)


NO_JOIN = (
    "has no pin of a LUT of this netlist: run VPR on the BLIF this report wrote, "
    "with --generate_net_timing_report on"
)


def _load_crit(
    inp: Inputs, blif: blifmod.Blif, notes: list[str]
) -> dict[tuple[str, int], float] | None:
    if inp.net_timing is None:
        return None
    pins = lateness.read_pin_slacks(inp.net_timing)
    if any(k[0] in blif.luts for k in pins):
        return lateness.criticality(pins)
    if not inp.timing_optional:
        raise ReportError(f"{inp.net_timing.name} {NO_JOIN}")
    notes.append(f"{inp.net_timing.name} found but not used: it {NO_JOIN}")
    return None


def _document(
    inp: Inputs,
    nl: netlist.Netlist,
    blif: blifmod.Blif,
    attr: lutcost.Attribution,
    groups: list[logical.Logical],
    crit: dict[tuple[str, int], float] | None,
    tables: tuple[list[dict[str, object]], list[dict[str, object]]],
    order: tuple[str, int | None],
    notes: list[str],
) -> dict[str, object]:
    rows, cons = tables
    sort, limit = order
    doc: dict[str, object] = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "design": {"top": nl.top, "lut_k": inp.lut_k},
        "totals": {
            "logical_muxes": len(groups),
            "mux_cells": len(nl.muxes),
            "mux_bits": sum(g.bits for g in groups),
            "luts": len(blif.luts),
            "luts_attributed": len({lut for lut in attr.lut_cells if attr.lut_cells[lut]}),
            "cuts": {k: attr.cuts.get(k, 0) for k in ("exact", "approx", "none")},
        },
        "sort": sort,
        "timing": crit is not None,
        "muxes": rows if limit is None else rows[:limit],
        "constructs": cons if limit is None else cons[:limit],
    }
    if notes:
        doc["notes"] = notes
    if crit is not None:
        doc["timing_note"] = (
            "criticality = (s_max - slack) / (s_max - s_min) over the pin slacks of the report; "
            "late = worst select-pin criticality - worst data-pin criticality"
        )
    return doc
