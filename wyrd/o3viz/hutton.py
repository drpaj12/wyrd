"""Hutton and Kundarewich circuit measures on a BLIF netlist (standard library only).

Definitions follow P. D. Kundarewich, "Synthetic Circuit Generation Using Clustering and
Iteration", MASc thesis, University of Toronto, 2002, section 2.1 (Hutton's combinational and
sequential model) and 3.1 (flip-flops at delay level 0, latched nodes, DFF edges of length 0).

Objects are the nets some LUT, flip-flop or hard block drives, and the primary inputs that some
object reads (delay level 0, like the flip-flops).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Collection

from wyrd.o3viz import blif


def seq_levels(nl: blif.Netlist) -> dict[str, int]:
    """Hutton's sequential level: 0 at a primary input, one more through each flip-flop.

    The thesis recursion (1 + level of the input for a flip-flop, MIN over the inputs otherwise) has
    no unique solution on a circuit with feedback; this is its least solution, the fewest
    flip-flops on any path from a primary input. A net no primary input reaches (a constant) has no
    level and is left out.
    """
    sinks: dict[str, list[str]] = {}
    for net, srcs in nl.inputs.items():
        for s in set(srcs):
            sinks.setdefault(s, []).append(net)
    out: dict[str, int] = {}
    todo: deque[tuple[int, str]] = deque((0, pi) for pi in sorted(nl.primary_inputs))
    while todo:
        lvl, net = todo.popleft()
        if net in out and out[net] <= lvl:
            continue
        out[net] = lvl
        for t in sorted(sinks.get(net, ())):
            if nl.drivers[t] == "latch":
                todo.append((lvl + 1, t))
            else:
                todo.appendleft((lvl, t))
    return {n: v for n, v in out.items() if n in nl.drivers}


def latched_nodes(nl: blif.Netlist) -> set[str]:
    """The LUTs whose output drives the D input of a flip-flop."""
    return {
        srcs[0]
        for net, srcs in nl.inputs.items()
        if nl.drivers[net] == "latch" and srcs
        if nl.drivers.get(srcs[0]) == "names"
    }


def comb_fanout(nl: blif.Netlist) -> dict[str, int]:
    """Hutton's fanout: how many LUTs a net drives (flip-flop D inputs and block pins left out)."""
    count = {net: 0 for net in objects(nl)}
    for net, srcs in nl.inputs.items():
        if nl.drivers[net] != "names":
            continue
        for s in set(srcs):
            if s in count:
                count[s] += 1
    return count


def objects(nl: blif.Netlist) -> set[str]:
    """Driven nets and the primary inputs something reads."""
    read = {s for srcs in nl.inputs.values() for s in srcs}
    return set(nl.drivers) | (read & nl.primary_inputs)


def _bump(hist: list[int], at: int, by: int = 1) -> None:
    while len(hist) <= at:
        hist.append(0)
    hist[at] += by


def characterize(nl: blif.Netlist, members: Collection[str] | None = None) -> dict[str, object]:
    """Shapes and distributions of the objects in `members` (default: every object).

    node/input/output/PO shape: per delay level, the objects, the LUT input pins, the objects that
    drive something, the objects that drive a primary output. fanout: how many objects have each
    combinational fanout. edge_length: edges into LUTs with both ends inside the set, by
    delay_level(sink) - delay_level(source); dff_edges (into a flip-flop, length 0) and
    block_edges (into a hard block) are counted apart.
    """
    level = nl.levels()
    fan, cfan = nl.fanout(), comb_fanout(nl)
    nodes = sorted(n for n in objects(nl) if members is None or n in members)
    inside = set(nodes)
    shape: dict[str, list[int]] = {k: [0] for k in ("node", "input", "output", "po")}
    fanout_dist: list[int] = [0]
    edge_len: list[int] = [0]
    dff = block = pis = 0
    for n in nodes:
        lv = level.get(n, 0)
        kind = nl.drivers.get(n, "pi")
        pis += kind == "pi"
        _bump(shape["node"], lv)
        _bump(fanout_dist, cfan[n])
        if fan.get(n, 0) > 0 or kind == "pi":
            _bump(shape["output"], lv)
        if n in nl.primary_outputs:
            _bump(shape["po"], lv)
        if kind == "names":
            _bump(shape["input"], lv, len(set(nl.inputs[n])))
        for s in sorted(set(nl.inputs.get(n, ()))) if kind != "pi" else ():
            if s not in inside:
                continue
            if kind == "latch":
                dff += 1
            elif kind == "subckt":
                block += 1
            else:
                _bump(edge_len, level.get(n, 0) - level.get(s, 0))
    dmax = max((level.get(n, 0) for n in nodes), default=0)
    width = dmax + 1
    for hist in shape.values():
        hist.extend([0] * (width - len(hist)))
    return {
        "nodes": len(nodes),
        "dmax": dmax,
        "pis": pis,
        "node_shape": shape["node"],
        "input_shape": shape["input"],
        "output_shape": shape["output"],
        "po_shape": shape["po"],
        "fanout": fanout_dist,
        "edge_length": edge_len,
        "dff_edges": dff,
        "block_edges": block,
    }
