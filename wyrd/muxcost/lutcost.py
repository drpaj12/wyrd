"""LUT cost of a mux: the LUTs the provenance map attributes to it, and a lower bound.

Attribution: a LUT made with ``abc --prov-cut on`` and flagged ``cut=exact`` has as parents the
``lower`` records of the word cells its function covers (flag ``cell=``). The parent of such a
record is the word record the snapshot netlist also names (flag ``uid=``, written with
``ODIN3_PROV_UID=1``), which joins it to the cell. A LUT with ``cut=approx`` or no cut is not
attributed to a cell; the report counts them.

Lower bound: a cone of L LUTs of at most k inputs has at most L(k-1)+1 distinct leaf signals
(each of the L LUTs has at most k input edges and at least L-1 of the edges join two LUTs of
the cone), so a function of n signals needs L >= (n-1)/(k-1), rounded up. Per output bit n is the
number of distinct non-constant data bits of that bit position plus the distinct select bits.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from wyrd.muxcost.blif import Blif
from wyrd.muxcost.logical import Logical
from wyrd.muxcost.netlist import Netlist
from wyrd.muxcost.provmap import MapError, NameMap


@dataclass
class Attribution:
    """``cell_luts``: snapshot cell name to the LUTs (atoms) whose exact cut covers it."""

    cell_luts: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    lut_cells: dict[str, frozenset[str]] = field(default_factory=dict)
    cuts: Counter[str] = field(default_factory=Counter)


def uid_cells(nl: Netlist, snap: NameMap) -> dict[str, list[str]]:
    """Record uid to the snapshot cells whose naming record has it."""
    out: dict[str, list[str]] = defaultdict(list)
    for name in nl.cells:
        rec = snap.record_of("node", name)
        if rec is not None and rec.uid is not None:
            out[rec.uid].append(name)
    return out


def gate_records(final: NameMap, rid: str) -> list[str]:
    """Records with a ``cell=`` flag reached from ``rid``'s parents, not passing through one."""
    found: dict[str, None] = {}
    seen: set[str] = set()
    stack = list(final.records[rid].parents)
    while stack:
        x = stack.pop()
        rec = final.records.get(x)
        if rec is None or x in seen:
            continue
        seen.add(x)
        if rec.cell_type is not None:
            found[x] = None
        else:
            stack.extend(rec.parents)
    return list(found)


def _cells_of_gate(final: NameMap, gate: str, by_uid: dict[str, list[str]]) -> list[str]:
    for parent in final.records[gate].parents:
        rec = final.records.get(parent)
        if rec is not None and rec.uid is not None:
            return by_uid.get(rec.uid, [])
    return []


def attribute(blif: Blif, final: NameMap, by_uid: dict[str, list[str]]) -> Attribution:
    out = Attribution()
    for lut in sorted(blif.luts):
        rec_id = final.objects.get(("net", lut), ("", ""))[0]
        rec = final.records.get(rec_id)
        cut = rec.flags.get("cut", "none") if rec is not None and rec.level == "lut" else "none"
        out.cuts[cut] += 1
        if rec is None or cut != "exact":
            continue
        cells = {c for g in gate_records(final, rec_id) for c in _cells_of_gate(final, g, by_uid)}
        out.lut_cells[lut] = frozenset(cells)
        for cell in cells:
            out.cell_luts[cell].add(lut)
    return out


def require_uid(final: NameMap) -> None:
    """Raise ``MapError`` when the map has no ``uid`` flag (written without ODIN3_PROV_UID=1)."""
    if not any(r.uid is not None for r in final.records.values()):
        raise MapError(
            "the name map has no uid flags: write it with ODIN3_PROV_UID=1 in the environment"
        )


@dataclass(frozen=True)
class LutCost:
    luts: frozenset[str]
    shared: int
    lower_bound: int


def lower_bound(mux: Logical, k: int) -> int:
    """Sum over output bit positions of ceil((n - 1) / (k - 1)), n >= 2 (0 for n < 2)."""
    total = 0
    sel = set(mux.select)
    for pos in range(mux.width):
        leaves = set(sel)
        for arm in mux.leaf_arms:
            bit = arm[pos] if pos < len(arm) else None
            if isinstance(bit, int):
                leaves.add(bit)
        n = len(leaves)
        total += -(-(n - 1) // (k - 1)) if n >= 2 else 0
    return total


def cost(mux: Logical, attr: Attribution, k: int) -> LutCost:
    members = set(mux.cells)
    luts: set[str] = set()
    for cell in members:
        luts |= attr.cell_luts.get(cell, set())
    shared = sum(1 for lut in luts if not attr.lut_cells[lut] <= members)
    return LutCost(frozenset(luts), shared, lower_bound(mux, k))
