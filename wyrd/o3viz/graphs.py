"""Graph planes above the HDL plane: STG, CFG and signal DDG from `write_graph` (stdlib only).

Input: the parsed `odin3-graph` files of `nets.Dumps.graphs` (and the SCOAP rows with `--prov`).
Output per kind: plane columns, the edge table, links to the HDL, cell and signal objects, and a
layered layout in the unit square. Nothing here runs a tool.

The graph files carry a provenance record ID (`prov`). In the name map used by this exporter the
records are renumbered, so the ID is kept in the bundle but not used as a join key; nodes are joined
to the HDL and to the cell plane by exact HDL span (and, for a case item, by the constant its select
`$eq` compares with). The manifest says how many nodes found a link.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from wyrd.o3viz import cells

PLANES = ("stg", "cfg", "ddg")  # top to bottom, all above hdl
INF = 10**17  # SCOAP infinity is 10^18

Link = tuple[str, str, str, str]


@dataclass
class GraphData:
    kind: str
    ids: list[str] = field(default_factory=list)
    nkind: list[str] = field(default_factory=list)
    ntype: list[str] = field(default_factory=list)
    name: list[str] = field(default_factory=list)
    src: list[list[list[str]]] = field(default_factory=list)
    metrics: dict[str, dict[str, float]] = field(default_factory=dict)
    edges: list[list[Any]] = field(default_factory=list)  # [from, to, kind, label, seq, src]
    links: list[Link] = field(default_factory=list)
    layout: dict[str, tuple[float, float]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    detail: dict[str, dict[str, Any]] = field(default_factory=dict)  # node id -> panel facts


def span_list(src: Sequence[str]) -> list[list[str]]:
    """["a.v:3.1-4.2", ...] -> [[file, span], ...] (basename of the file)."""
    return cells.parse_src("|".join(src))


def bare(label: str) -> str:
    """`\\cur_state` or `memset.cur_state` -> `cur_state`."""
    s = label.lstrip("\\")
    return s.rsplit(".", 1)[-1] if "." in s else s


class Index:
    """Span and name lookups over the hdl and cell planes."""

    def __init__(self, hdl_ids: Sequence[str], hdl_src: Sequence[Any], cd: cells.CellData | None):
        self.hdl_by_span: dict[str, list[str]] = defaultdict(list)
        self.hdl_ids = set(hdl_ids)
        for oid, srcs in zip(hdl_ids, hdl_src, strict=True):
            for _f, sp in srcs[:1]:
                self.hdl_by_span[sp].append(oid)
        self.cell_by_span: dict[str, list[int]] = defaultdict(list)
        self.cd = cd
        if cd:
            for k, srcs in enumerate(cd.src):
                for _f, sp in srcs[:1]:
                    self.cell_by_span[sp].append(k)

    def cells_named(self, name: str) -> list[str]:
        """Cells whose output bus is the signal `name`."""
        if not self.cd:
            return []
        return [c for c in self.cd.ids if self.cd.bus.get(c, ("",))[0] == name]

    def hdl_for(self, spans: Sequence[Sequence[str]]) -> list[str]:
        out: list[str] = []
        for _f, sp in spans:
            out.extend(self.hdl_by_span.get(sp, ()))
        return sorted(set(out))

    def cells_for(self, spans: Sequence[Sequence[str]], types: Sequence[str] = ()) -> list[str]:
        if not self.cd:
            return []
        ks = {k for _f, sp in spans for k in self.cell_by_span.get(sp, ())}
        return sorted(self.cd.ids[k] for k in ks if not types or self.cd.types[k] in types)


def const_value(text: str) -> int | None:
    """`4'0011` -> 3, `1'1` -> 1, a bare decimal -> itself, else None."""
    m = re.fullmatch(r"\s*(\d+)'([bBoOdDhH]?)([0-9a-fA-FxXzZ_]+)\s*", text)
    if m:
        base = {"": 2, "b": 2, "o": 8, "d": 10, "h": 16}[m.group(2).lower()]
        try:
            return int(m.group(3).replace("_", ""), base)
        except ValueError:
            return None
    return int(text) if text.strip().isdigit() else None


def eq_cells_with(cd: cells.CellData | None, cand: Sequence[str], value: int) -> list[str]:
    """Select `$eq` cells among `cand` that compare with the constant `value`."""
    if not cd or not cd.consts:
        return []
    return [c for c in cand if cd.consts.get(c) == value]


# ---- layered layout ----


def layers_dag(nodes: Sequence[str], edges: Sequence[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layer of each node over the DAG edges (Kahn); nodes on a cycle go after their
    assigned predecessors."""
    succ: dict[str, list[str]] = defaultdict(list)
    pred: dict[str, list[str]] = defaultdict(list)
    indeg = dict.fromkeys(nodes, 0)
    for a, b in edges:
        if a == b or a not in indeg or b not in indeg:
            continue
        succ[a].append(b)
        pred[b].append(a)
        indeg[b] += 1
    layer = dict.fromkeys(nodes, 0)
    queue = deque(n for n in nodes if indeg[n] == 0)
    done: set[str] = set()
    while queue:
        n = queue.popleft()
        done.add(n)
        for m in succ[n]:
            layer[m] = max(layer[m], layer[n] + 1)
            indeg[m] -= 1
            if indeg[m] == 0:
                queue.append(m)
    for n in nodes:  # cycle leftovers: after the predecessors that were placed so far
        if n not in done:
            layer[n] = 1 + max((layer[p] for p in pred[n] if p in done), default=-1)
            done.add(n)
    return layer


def layers_bfs(nodes: Sequence[str], edges: Sequence[tuple[str, str]], root: str) -> dict[str, int]:
    """Distance from `root` (STG); unreachable nodes go one layer below the deepest."""
    succ: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        succ[a].append(b)
    dist = {root: 0}
    queue = deque([root])
    while queue:
        n = queue.popleft()
        for m in succ[n]:
            if m not in dist:
                dist[m] = dist[n] + 1
                queue.append(m)
    deepest = max(dist.values()) + 1
    return {n: dist.get(n, deepest) for n in nodes}


CIRCLE_MAX = 30  # an STG with up to this many states is drawn on a circle


def layout_circle(layer: Mapping[str, int], root: str) -> dict[str, tuple[float, float]]:
    """States on a circle, the reset state at the top, the others by distance from it (then name),
    clockwise; unit radius, centre (0, 0)."""
    order = sorted(layer, key=lambda n: (n != root, layer[n], n))
    n = len(order)
    return {
        s: (math.sin(2 * math.pi * k / n), -math.cos(2 * math.pi * k / n))
        for k, s in enumerate(order)
    }


def order_layers(
    layer: Mapping[str, int], edges: Sequence[tuple[str, str]], sweeps: int = 4
) -> dict[str, float]:
    """Position inside each layer by the barycentre heuristic; returns x per node, spacing 1."""
    rows: dict[int, list[str]] = defaultdict(list)
    for n, k in layer.items():
        rows[k].append(n)
    nb: dict[str, list[str]] = defaultdict(list)
    for a, b in edges:
        if a in layer and b in layer and a != b:
            nb[a].append(b)
            nb[b].append(a)
    x: dict[str, float] = {}
    for k in sorted(rows):
        for i, n in enumerate(rows[k]):
            x[n] = float(i)
    for s in range(sweeps):
        ks = sorted(rows) if s % 2 == 0 else sorted(rows, reverse=True)
        for k in ks:
            ref = {n: [x[m] for m in nb[n] if layer[m] != k] for n in rows[k]}
            rows[k].sort(key=lambda n: (sum(ref[n]) / len(ref[n]) if ref[n] else x[n], n))
            for i, n in enumerate(rows[k]):
                x[n] = float(i)
    return x


ROW_MAX = 40  # a layer wider than this is wrapped into several rows


def layout_graph(
    layer: Mapping[str, int], edges: Sequence[tuple[str, str]]
) -> dict[str, tuple[float, float]]:
    """(column, row): each layer centred; y grows down the layers. A layer of more than ROW_MAX
    nodes is wrapped into rows (a quarter of a layer apart), nodes kept in barycentre order."""
    x = order_layers(layer, edges)
    rows: dict[int, list[str]] = defaultdict(list)
    for n, k in layer.items():
        rows[k].append(n)
    wmax = max((min(len(v), ROW_MAX) for v in rows.values()), default=1)
    out: dict[str, tuple[float, float]] = {}
    y = 0.0
    for k in sorted(rows):
        nodes = sorted(rows[k], key=lambda n: (x[n], n))
        chunks = [nodes[i : i + ROW_MAX] for i in range(0, len(nodes), ROW_MAX)]
        for j, chunk in enumerate(chunks):
            for i, n in enumerate(chunk):
                out[n] = (i + (wmax - len(chunk)) / 2.0, y + 0.25 * j)
        y += 1.0 + 0.25 * (len(chunks) - 1)
    return out


def to_unit(
    parts: Sequence[dict[str, tuple[float, float]]],
) -> dict[str, tuple[float, float]]:
    """Several layouts side by side (one row), the whole in [0,1] x [0,1] (stretched)."""
    out: dict[str, tuple[float, float]] = {}
    x0 = 0.0
    shifted: list[dict[str, tuple[float, float]]] = []
    for p in parts:
        if not p:
            continue
        xs = [v[0] for v in p.values()]
        lo = min(xs)
        ylo = min(v[1] for v in p.values())
        shifted.append({n: (v[0] - lo + x0, v[1] - ylo) for n, v in p.items()})
        x0 += max(xs) - lo + 2.0
    allp = [v for p in shifted for v in p.values()]
    if not allp:
        return out
    xmax = max(v[0] for v in allp) or 1.0
    ymax = max(v[1] for v in allp) or 1.0
    for p in shifted:
        for n, (x, y) in p.items():
            out[n] = (x / xmax, y / ymax)
    return out


# ---- readers per kind ----


def module_graphs(doc: Mapping[str, Any], top: str) -> list[dict[str, Any]]:
    for m in doc.get("modules", []):
        if m.get("name") == top:
            return list(m.get("graphs", []))
    return []


def add_node(g: GraphData, plane: str, n: Mapping[str, Any], src: Sequence[str]) -> str:
    oid = f"{plane}:{n['id']}"
    g.ids.append(oid)
    g.nkind.append(str(n.get("kind", "")))
    g.ntype.append(str(n.get("kind", "")))
    g.name.append(str(n.get("label", "")))
    g.src.append(span_list(src))
    return oid


def add_edges(
    g: GraphData, plane: str, edges: Sequence[Mapping[str, Any]]
) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for e in edges:
        a, b = f"{plane}:{e['from']}", f"{plane}:{e['to']}"
        g.edges.append(
            [
                a,
                b,
                e.get("kind", ""),
                e.get("label", ""),
                1 if e.get("seq") else 0,
                span_list(e.get("src", [])),
            ]
        )
        pairs.append((a, b))
    return pairs


def degrees(g: GraphData) -> None:
    din: dict[str, float] = dict.fromkeys(g.ids, 0.0)
    dout: dict[str, float] = dict.fromkeys(g.ids, 0.0)
    for a, b, *_ in g.edges:
        dout[a] = dout.get(a, 0.0) + 1
        din[b] = din.get(b, 0.0) + 1
    g.metrics["graph_in"] = din
    g.metrics["graph_out"] = dout


def link_exact(g: GraphData, ix: Index, oid: str, spans: Sequence[Sequence[str]]) -> None:
    for h in ix.hdl_for(spans):
        g.links.append((oid, h, "span", "high"))


def build_stg(doc: Mapping[str, Any], top: str, ix: Index, cd: cells.CellData | None) -> GraphData:
    g = GraphData("stg")
    parts: list[dict[str, tuple[float, float]]] = []
    reset: dict[str, float] = {}
    for gr in module_graphs(doc, top):
        ids = [add_node(g, "stg", n, n.get("src", [])) for n in gr["nodes"]]
        pairs = add_edges(g, "stg", gr["edges"])
        root = next(
            (f"stg:{n['id']}" for n in gr["nodes"] if n.get("reset")), ids[0] if ids else ""
        )
        for n in gr["nodes"]:
            reset[f"stg:{n['id']}"] = 1.0 if n.get("reset") else 0.0
            g.detail[f"stg:{n['id']}"] = {
                "code": n.get("code", ""),
                "graph": gr["id"],
                "wire": gr.get("label", ""),
            }
        if ids:
            lay = layers_bfs(ids, pairs, root)
            parts.append(
                layout_circle(lay, root) if len(ids) <= CIRCLE_MAX else layout_graph(lay, pairs)
            )
        link_stg(g, gr, ids, ix, cd)
    g.metrics["is_reset"] = reset
    g.layout = to_unit(parts)
    degrees(g)
    return g


def link_stg(
    g: GraphData, gr: Mapping[str, Any], ids: Sequence[str], ix: Index, cd: cells.CellData | None
) -> None:
    """A state links to the state register (HDL span, declared signal, its flip-flop cells) and to
    the
    next-state selection logic (the spans and cells of `select_nodes`): the fsm pass does not
    attribute a state to one case item."""
    name = bare(str(gr.get("label", "")))
    spans = span_list(gr.get("src", []))
    sel_spans = [s for sn in gr.get("select_nodes", []) for s in span_list(sn.get("src", []))]
    hdl = set(ix.hdl_for(spans + sel_spans))
    sig = f"hdl:sig.{name}"
    if sig in ix.hdl_ids:
        hdl.add(sig)
    cs: set[str] = set(ix.cells_for(sel_spans, ("$mux", "$pmux", "$eq")))
    if cd:
        cs.update(c for c in cd.ids if cd.bus.get(c, ("",))[0] == name and c in cd.ff)
    for oid in ids:
        for h in sorted(hdl):
            g.links.append((oid, h, "span", "medium"))
        for c in sorted(cs):
            g.links.append((oid, c, "state_logic", "medium"))


def build_cfg(doc: Mapping[str, Any], top: str, ix: Index) -> GraphData:
    g = GraphData("cfg")
    parts: list[dict[str, tuple[float, float]]] = []
    acts: dict[str, float] = {}
    for gr in module_graphs(doc, top):
        ids = [add_node(g, "cfg", n, n.get("src", [])) for n in gr["nodes"]]
        pairs = add_edges(g, "cfg", gr["edges"])
        for n in gr["nodes"]:
            oid = f"cfg:{n['id']}"
            acts[oid] = float(len(n.get("actions", [])))
            g.detail[oid] = {
                "compares": n.get("compares", []),
                "signal": n.get("signal", ""),
                "prov": n.get("prov", 0),
                "actions": [[a.get("lhs", ""), a.get("rhs", "")] for a in n.get("actions", [])][
                    :12
                ],
            }
        if ids:
            root = ids[0]
            parts.append(layout_graph(layers_dag(ids, pairs) if pairs else {root: 0}, pairs))
        link_cfg(g, gr, ix)
    g.metrics["n_actions"] = acts
    g.layout = to_unit(parts)
    degrees(g)
    return g


def link_cfg(g: GraphData, gr: Mapping[str, Any], ix: Index) -> None:
    """Every node to the HDL constructs with its exact span; a switch to the cells with its span;
    a case
    to the select `$eq` cells of its switch that compare with one of its patterns."""
    by_id = {n["id"]: n for n in gr["nodes"]}
    parent_sw: dict[str, str] = {}
    for e in gr["edges"]:
        if e.get("kind") == "control":
            parent_sw[e["to"]] = e["from"]
    for n in gr["nodes"]:
        oid, spans = f"cfg:{n['id']}", span_list(n.get("src", []))
        link_exact(g, ix, oid, spans)
        kind = n.get("kind")
        if kind == "switch" or kind == "entry":
            for c in ix.cells_for(spans):
                g.links.append((oid, c, "span", "medium"))
        elif kind == "case" and n["id"] in parent_sw:
            sw = by_id[parent_sw[n["id"]]]
            cand = ix.cells_for(span_list(sw.get("src", [])), ("$eq",))
            for pat in n.get("compares", []):
                v = const_value(pat)
                for c in eq_cells_with(ix.cd, cand, v) if v is not None else []:
                    g.links.append((oid, c, "structural_match", "medium"))


def build_ddg(
    doc: Mapping[str, Any],
    top: str,
    ix: Index,
    scoap: Sequence[Mapping[str, Any]],
    mapped: Mapping[str, Any] | None = None,
    named: Mapping[str, tuple[int, int, int]] | None = None,
) -> GraphData:
    g = GraphData("ddg")
    parts: list[dict[str, tuple[float, float]]] = []
    width: dict[str, float] = {}
    ff: dict[str, float] = {}
    for gr in module_graphs(doc, top):
        ids = [add_node(g, "ddg", n, n.get("src", [])) for n in gr["nodes"]]
        for n in gr["nodes"]:
            oid = f"ddg:{n['id']}"
            g.ntype[g.ids.index(oid)] = str(n.get("port") or n.get("kind", ""))
            width[oid] = float(n.get("width", 1))
        pairs = add_edges(g, "ddg", gr["edges"])
        for e in gr["edges"]:
            if e.get("seq"):
                ff[f"ddg:{e['to']}"] = 1.0
        comb = [(a, b) for (a, b), e in zip(pairs, gr["edges"], strict=True) if not e.get("seq")]
        if ids:
            lay = layers_dag(ids, comb)
            lay = ends_at_ports(gr, lay)
            parts.append(layout_graph(lay, pairs))
        for n in gr["nodes"]:
            oid = f"ddg:{n['id']}"
            link_exact(g, ix, oid, span_list(n.get("src", [])))
            nm = f"hdl:sig.{bare(str(n.get('label', '')))}"
            if nm in ix.hdl_ids:
                g.links.append((oid, nm, "name", "exact"))
            for c in ix.cells_named(bare(str(n.get("label", "")))):
                g.links.append((oid, c, "name", "high"))
    g.metrics["width"] = width
    g.metrics["is_ff"] = ff
    g.layout = to_unit(parts)
    degrees(g)
    join_scoap(g, scoap, mapped_labels(mapped, top), named)
    return g


def ends_at_ports(gr: Mapping[str, Any], lay: dict[str, int]) -> dict[str, int]:
    """Inputs at layer 0 and outputs on the last layer (the ports at the ends)."""
    last = max(lay.values(), default=0)
    out = dict(lay)
    for n in gr["nodes"]:
        if n.get("port") == "in":
            out[f"ddg:{n['id']}"] = 0
        elif n.get("port") == "out":
            out[f"ddg:{n['id']}"] = last
    return out


def mapped_labels(mapped: Mapping[str, Any] | None, top: str) -> dict[int, str] | None:
    """Wire ID -> signal name in the DDG of the mapped netlist (where `scoap` ran), or None."""
    if mapped is None:
        return None
    return {
        int(n["wire"]): bare(str(n["label"]))
        for gr in module_graphs(mapped, top)
        for n in gr["nodes"]
        if n.get("wire")
    }


def scoap_key(
    r: Mapping[str, Any], wire_name: Mapping[int, str] | None, by_name: Mapping[str, str]
) -> str:
    if wire_name is not None:
        return by_name.get(wire_name.get(int(r.get("wire") or 0), ""), "")
    return f"ddg:w{r['wire']}" if r.get("wire") else f"ddg:n{r['id']}"


def join_scoap(
    g: GraphData,
    rows: Sequence[Mapping[str, Any]],
    wire_name: Mapping[int, str] | None = None,
    named: Mapping[str, tuple[int, int, int]] | None = None,
) -> None:
    """CC0, CC1 and CO per signal node from the `scoap --prov` rows: a signal takes the worst (max)
    value over the nets of its wire (`wire` is the ID of node `w<wire>`); a net outside a wire
    joins `n<net>` by its ID. Unreachable (>= 10^17) is no value.

    The scoap pass runs on the mapped netlist, where most word-level wires are gone, so its
    wire IDs belong to the DDG of that netlist, not to the post-`proc` one in the plane. With
    `wire_name` (the mapped DDG's wire -> name) a row joins the plane's signal of the same name;
    without it (fixtures) by wire ID."""
    best: dict[str, list[float | None]] = {}
    have = set(g.ids)
    by_name = {bare(nm): i for i, nm in zip(g.ids, g.name, strict=True) if i.startswith("ddg:w")}
    for r in rows:
        if "wire" not in r:
            return
        key = scoap_key(r, wire_name, by_name)
        if key not in have:
            continue
        cur = best.setdefault(key, [None, None, None])
        for k, f in enumerate(("cc0", "cc1", "co")):
            v = r.get(f)
            if v is None or v >= INF:
                continue
            cur[k] = float(v) if cur[k] is None else max(cur[k] or 0.0, float(v))
    for (
        nm,
        i,
    ) in by_name.items():  # registers: the mapped nets of their bus (no wire ID in the rows)
        if i not in best and named and nm in named:
            best[i] = [float(x) for x in named[nm]]
    for k, f in enumerate(("cc0", "cc1", "co")):
        g.metrics[f] = {i: x for i, v in best.items() if (x := v[k]) is not None}
    g.notes.append(f"scoap joined to {len(best)} of {len(g.ids)} ddg signals")


def build_all(
    graphs: Mapping[str, Any],
    top: str,
    hdl_ids: Sequence[str],
    hdl_src: Sequence[Any],
    cd: cells.CellData | None,
    scoap: Sequence[Mapping[str, Any]],
    named: Mapping[str, tuple[int, int, int]] | None = None,
) -> dict[str, GraphData]:
    ix = Index(hdl_ids, hdl_src, cd)
    out: dict[str, GraphData] = {}
    if "stg" in graphs:
        out["stg"] = build_stg(graphs["stg"], top, ix, cd)
    if "cfg" in graphs:
        out["cfg"] = build_cfg(graphs["cfg"], top, ix)
    if "ddg" in graphs:
        out["ddg"] = build_ddg(graphs["ddg"], top, ix, scoap, graphs.get("ddgm"), named)
    return {k: v for k, v in out.items() if v.ids}


def place_in(
    layout: Mapping[str, tuple[float, float]], bounds: Sequence[float]
) -> dict[str, list[float]]:
    """Map the unit layout into the box [xmin, ymin, xmax, ymax] of an anchor (10% margin)."""
    w, h = bounds[2] - bounds[0], bounds[3] - bounds[1]
    return {
        n: [round(bounds[0] + w * (0.05 + 0.9 * x), 4), round(bounds[1] + h * (0.05 + 0.9 * y), 4)]
        for n, (x, y) in layout.items()
    }
