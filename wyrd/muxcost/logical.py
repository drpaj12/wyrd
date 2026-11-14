"""Logical muxes: chains of word-level muxes that one HDL construct made (an if-else chain).

A mux cell joins its parent's group when its whole output feeds one data port of that single parent
mux, the widths agree and nothing else reads it. The group's arms are the arms no member drives.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from wyrd.muxcost.netlist import CHAIN_TYPES, Arm, Bit, MuxCell, Netlist


def is_const(arm: Arm) -> bool:
    return bool(arm) and all(isinstance(b, str) for b in arm)


def related_arms(arms: tuple[Arm, ...]) -> int:
    """Arms that share a signal pattern with a different arm (they differ in constant bits only).

    Two arms are related when every bit position is the same signal in both or constant in both,
    the arms are not identical, and at least one bit is a signal. All-constant arms are counted as
    constant arms, not here. Counted by signature, so linear in the number of arms.
    """
    classes: dict[tuple[Bit | None, ...], set[Arm]] = defaultdict(set)
    members: dict[tuple[Bit | None, ...], int] = defaultdict(int)
    for arm in arms:
        if is_const(arm):
            continue
        sig = tuple(b if isinstance(b, int) else None for b in arm)
        classes[sig].add(arm)
        members[sig] += 1
    return sum(members[s] for s, distinct in classes.items() if len(distinct) > 1)


@dataclass(frozen=True)
class Logical:
    root: str
    cells: tuple[str, ...]
    leaf_arms: tuple[Arm, ...]
    select: tuple[int, ...]
    width: int
    bits: int

    @property
    def const_arms(self) -> int:
        return sum(1 for a in self.leaf_arms if is_const(a))

    @property
    def dup_arms(self) -> int:
        return len(self.leaf_arms) - len(set(self.leaf_arms))

    @property
    def related(self) -> int:
        return related_arms(self.leaf_arms)


def _parent_of(nl: Netlist, cell: MuxCell) -> str | None:
    """The one chainable mux whose data ports read all of this cell's output, else None."""
    parent: str | None = None
    for bit in cell.out:
        if not isinstance(bit, int):
            continue
        if bit in nl.port_out_bits:
            return None
        for reader, port in nl.readers.get(bit, ()):
            other = nl.muxes.get(reader)
            if port not in ("A", "B") or other is None or other.type not in CHAIN_TYPES:
                return None
            if parent is not None and reader != parent:
                return None
            parent = reader
    return parent


def _joins(nl: Netlist) -> dict[str, str]:
    """Child cell to parent cell for every cell that joins its parent's group."""
    joins: dict[str, str] = {}
    for name, cell in nl.muxes.items():
        if cell.type not in CHAIN_TYPES:
            continue
        parent = _parent_of(nl, cell)
        if parent is not None and nl.muxes[parent].width == cell.width:
            joins[name] = parent
    return joins


def _members(root: str, children: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    stack = [root]
    while stack:
        x = stack.pop()
        out.append(x)
        stack.extend(children.get(x, ()))
    return sorted(out)


def _leaf_arms(nl: Netlist, members: list[str]) -> list[Arm]:
    inside = set(members)
    leaves: list[Arm] = []
    for name in members:
        for arm in nl.muxes[name].arms:
            driver = nl.driver.get(arm[0]) if arm and isinstance(arm[0], int) else None
            if driver in inside and driver != name and nl.muxes[driver].out == arm:
                continue
            leaves.append(arm)
    return leaves


def _logical(nl: Netlist, root: str, members: list[str]) -> Logical:
    select: dict[int, None] = {}
    for name in members:
        for bit in nl.muxes[name].select:
            if isinstance(bit, int):
                select[bit] = None
    return Logical(
        root,
        tuple(members),
        tuple(_leaf_arms(nl, members)),
        tuple(select),
        nl.muxes[root].width,
        sum(nl.muxes[m].bits for m in members),
    )


def group(nl: Netlist) -> list[Logical]:
    """All logical muxes of the netlist, ordered by root cell name."""
    joins = _joins(nl)
    children: dict[str, list[str]] = defaultdict(list)
    for child, parent in joins.items():
        children[parent].append(child)
    return [
        _logical(nl, root, _members(root, children))
        for root in sorted(nl.muxes)
        if root not in joins
    ]
