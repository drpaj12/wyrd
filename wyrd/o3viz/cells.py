"""The pre-mapping cell plane, signals (declared regs and wires) and bus names (stdlib only).

Inputs are the parsed dumps of `nets.py`. Nothing here runs a tool.
"""

from __future__ import annotations

import bisect
import re
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from wyrd.o3viz import blif, nets

FF_TYPE = re.compile(r"^\$(a|s|ald)?dff|^\$dlatch|^\$_(DFF|DLATCH)")
LABEL = re.compile(
    r"^\s*(?:(\d+)\s*'\s*([bBoOdDhH])\s*([0-9a-fA-F_]+)|(\d+))\s*(?:,\s*[^:]*)?:(?!:)"
)
DECL = r"\b(reg|wire|input|output|inout)\b[^;]*\b{}\b"
Bus = tuple[str, int | None, str]  # bus name, bit, "own" or "cone"
BITBASE = {"b": 2, "o": 8, "d": 10, "h": 16}


@dataclass
class Signal:
    name: str
    kind: str  # reg, wire, input, output
    width: int
    bits: list[int]
    decl: list[str] | None  # [file, span] of the declaration line


@dataclass
class CellData:
    ids: list[str] = field(default_factory=list)
    types: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    src: list[list[list[str]]] = field(default_factory=list)
    ff: set[str] = field(default_factory=set)
    bus: dict[str, Bus] = field(default_factory=dict)
    links: list[tuple[str, str, str, str]] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    sig_links: list[tuple[str, str, str, str]] = field(default_factory=list)
    selects: int = 0


def parse_src(attr: str) -> list[list[str]]:
    out: list[list[str]] = []
    for part in attr.split("|"):
        f, sep, span = part.rpartition(":")
        if sep and re.fullmatch(r"\d+\.\d+-\d+\.\d+", span):
            out.append([f.rsplit("/", 1)[-1], span])
    return out


def bit_names(mod: Mapping[str, Any], top: str) -> dict[int, tuple[str, int]]:
    """Bit id -> (bus, index): ports first, then the other wires, first name wins."""
    nn = mod.get("netnames", {})
    out: dict[int, tuple[str, int]] = {}
    for key in sorted(nn, key=lambda k: ("@" in k, k)):
        name = nets.bare_name(key, top)
        for idx, b in enumerate(nn[key].get("bits", [])):
            if isinstance(b, int) and b not in out:
                out[b] = (name, idx)
    return out


def out_bits(cell: Mapping[str, Any]) -> list[int]:
    dirs = cell.get("port_directions", {})
    conn = cell.get("connections", {})
    return [
        b for p, bits in conn.items() if dirs.get(p) == "output" for b in bits if isinstance(b, int)
    ]


def in_bits(cell: Mapping[str, Any]) -> list[int]:
    dirs = cell.get("port_directions", {})
    conn = cell.get("connections", {})
    return [
        b for p, bits in conn.items() if dirs.get(p) == "input" for b in bits if isinstance(b, int)
    ]


def own_bus(bits: Sequence[int], names: Mapping[int, tuple[str, int]]) -> Bus | None:
    hit = [names[b] for b in bits if b in names]
    if not hit:
        return None
    buses = {h[0] for h in hit}
    if len(buses) != 1:
        return None
    one = len(hit) == 1
    return hit[0][0], hit[0][1] if one else None, "own"


def infer(
    own: Mapping[str, Bus],
    succ: Mapping[str, Sequence[str]],
    nodes: Sequence[str],
    limit: int = 400,
) -> dict[str, Bus]:
    """Nodes without a name take the one bus of the nearest named nodes below them, if unique."""
    out: dict[str, Bus] = dict(own)
    for n in nodes:
        if n in own:
            continue
        seen = {n}
        stack = list(succ.get(n, ()))
        found: set[str] = set()
        while stack and len(seen) < limit and len(found) < 2:
            m = stack.pop()
            if m in seen:
                continue
            seen.add(m)
            if m in own:
                found.add(own[m][0])
            else:
                stack.extend(succ.get(m, ()))
        if len(found) == 1:
            out[n] = (next(iter(found)), None, "cone")
    return out


def cell_value(bits: Sequence[Any]) -> int | None:
    if not bits or any(b not in ("0", "1") for b in bits):
        return None
    return sum(1 << i for i, b in enumerate(bits) if b == "1")


def label_value(line: str) -> int | None:
    m = LABEL.match(line)
    if not m:
        return None
    try:
        if m.group(4) is not None:
            return int(m.group(4))
        return int(m.group(3).replace("_", ""), BITBASE[m.group(2).lower()])
    except ValueError:
        return None


def chains(hdl: Mapping[str, Any], parent: Mapping[str, str]) -> dict[str, list[str]]:
    """Chain node (a case or an if/else chain) -> its items (children of level branch)."""
    kids: dict[str, list[str]] = defaultdict(list)
    for oid, p in parent.items():
        if hdl[oid]["attrs"].get("level") == "branch":
            kids[p].append(oid)
    return {p: k for p, k in kids.items() if len(k) >= 2}


def item_labels(
    items: Sequence[str], hdl: Mapping[str, Any], texts: Mapping[str, list[str]]
) -> dict[int, str]:
    out: dict[int, str] = {}
    for it in items:
        src = hdl[it].get("src") or []
        if not src or src[0]["file"] not in texts:
            continue
        line = int(src[0]["span"].split(".", 1)[0])
        lines = texts[src[0]["file"]]
        v = label_value(lines[line - 1]) if 0 < line <= len(lines) else None
        if v is not None and v not in out:
            out[v] = it
    return out


def select_items(
    cells: Mapping[str, Any],
    hdl: Mapping[str, Any],
    parent: Mapping[str, str],
    texts: Mapping[str, list[str]],
) -> dict[str, str]:
    """Cell key -> item: an `$eq` against a constant that labels exactly one item."""
    labels = {c: item_labels(its, hdl, texts) for c, its in chains(hdl, parent).items()}
    out: dict[str, str] = {}
    for key, cell in cells.items():
        if cell["type"] != "$eq":
            continue
        a, b = cell["connections"].get("A", []), cell["connections"].get("B", [])
        va, vb = cell_value(a), cell_value(b)
        if (va is None) == (vb is None):
            continue
        val = va if va is not None else vb
        cand = {lab[val] for lab in labels.values() if val in lab}
        if len(cand) == 1:
            out[key] = next(iter(cand))
    return out


def ancestors(oid: str, parent: Mapping[str, str]) -> list[str]:
    out = []
    while oid in parent:
        oid = parent[oid]
        out.append(oid)
    return out


def item_of(oid: str, items: set[str], parent: Mapping[str, str]) -> str | None:
    for x in [oid, *ancestors(oid, parent)]:
        if x in items:
            return x
    return None


def hdl_links_of(
    spans: Sequence[Sequence[str]],
    sel: str | None,
    by_span: Mapping[str, list[str]],
    parent: Mapping[str, str],
    chain_of: Mapping[str, list[str]],
) -> list[tuple[str, str]]:
    """HDL constructs a cell links to: those with its exact spans and their ancestors. A select cell
    keeps only its own item of the chain (and the chain), not the sibling items."""
    hit: set[str] = set()
    for _f, sp in spans:
        for h in by_span.get(sp, ()):
            hit.add(h)
            hit.update(ancestors(h, parent))
    if sel:
        sibs = set(chain_of.get(parent.get(sel, ""), []))
        hit = {h for h in hit if (item_of(h, sibs, parent) or sel) == sel}
        hit.add(sel)
        hit.update(ancestors(sel, parent))
    return [(h, "structural_match" if h == sel else "location_match") for h in sorted(hit)]


def cell_ancestry(d: nets.Dumps, wanted: set[str]) -> dict[str, frozenset[str]]:
    """Record -> the `wanted` (cell) records it derives from, over the final name map."""
    memo: dict[str, frozenset[str]] = {}
    for root in d.records:
        stack = [root]
        while stack:
            r = stack[-1]
            if r in memo:
                stack.pop()
                continue
            pend = [q for q in d.records[r] if q in d.records and q not in memo and q != r]
            if pend:
                stack.extend(pend)
                continue
            acc: set[str] = {r} if r in wanted else set()
            for q in d.records[r]:
                acc |= memo.get(q, frozenset())
            memo[r] = frozenset(acc)
            stack.pop()
    return memo


def build_cells(
    d: nets.Dumps,
    hdl: Mapping[str, Any],
    parent: Mapping[str, str],
    texts: Mapping[str, list[str]],
    lut_ids: Sequence[str],
) -> CellData:
    cells: dict[str, Any] = d.proc["cells"]
    names = bit_names(d.proc, d.top)
    by_span: dict[str, list[str]] = defaultdict(list)
    for oid, o in hdl.items():
        if o.get("src"):
            by_span[o["src"][0]["span"]].append(oid)
    chain_of = chains(hdl, parent)
    sel = select_items(cells, hdl, parent, texts)
    cd = CellData(selects=len(sel))
    own: dict[str, Bus] = {}
    succ: dict[str, list[str]] = defaultdict(list)
    readers: dict[int, list[str]] = defaultdict(list)
    rec_cells: dict[str, list[str]] = defaultdict(list)
    for key, c in cells.items():
        oid = "cell:" + nets.bare_name(key, d.top)
        cd.ids.append(oid)
        cd.types.append(c["type"])
        cd.names.append(oid[5:])
        spans = parse_src(c.get("attributes", {}).get("src", ""))
        cd.src.append(spans)
        if FF_TYPE.match(c["type"]):
            cd.ff.add(oid)
        b = own_bus(out_bits(c), names)
        if b:
            own[oid] = b
        for x in in_bits(c):
            readers[x].append(oid)
        for h, kind in hdl_links_of(spans, sel.get(key), by_span, parent, chain_of):
            cd.links.append((h, oid, kind, "medium" if kind == "structural_match" else "high"))
        rec = d.proc_names.get(key)
        if rec and oid not in cd.ff:
            rec_cells[rec[1]].append(oid)
    for key, c in cells.items():
        oid = "cell:" + nets.bare_name(key, d.top)
        for x in out_bits(c):
            succ[oid].extend(readers.get(x, ()))
    cd.bus = infer(own, succ, cd.ids)
    link_luts(cd, d, rec_cells, lut_ids)
    cd.signals = signals_of(d, texts)
    link_signals(cd, d, cells)
    return cd


def link_luts(
    cd: CellData, d: nets.Dumps, rec_cells: Mapping[str, list[str]], lut_ids: Sequence[str]
) -> None:
    memo = cell_ancestry(d, set(rec_cells))
    for lid in lut_ids:
        h = lid.split("/", 1)[-1]
        rec = d.lut_rec.get(h)
        if rec is None:
            continue
        for r in sorted(memo.get(rec, ())):
            for c in rec_cells[r]:
                cd.links.append((c, lid, "cone", "high"))


def decl_of(name: str, texts: Mapping[str, list[str]], src: str) -> list[str] | None:
    rx = re.compile(DECL.format(re.escape(name)))
    for part in parse_src(src):
        lines = texts.get(part[0])
        ln = int(part[1].split(".", 1)[0])
        if lines and 0 < ln <= len(lines) and rx.search(lines[ln - 1]):
            return [part[0], f"{ln}.1-{ln}.{len(lines[ln - 1]) + 1}"]
    for f in sorted(texts):
        for i, line in enumerate(texts[f]):
            if rx.search(line):
                return [f, f"{i + 1}.1-{i + 1}.{len(line) + 1}"]
    return None


def signals_of(d: nets.Dumps, texts: Mapping[str, list[str]]) -> list[Signal]:
    ports = d.proc.get("ports", {})
    ffq = {b for c in d.proc["cells"].values() if FF_TYPE.match(c["type"]) for b in out_bits(c)}
    out: list[Signal] = []
    for key in sorted(d.proc.get("netnames", {})):
        name = nets.bare_name(key, d.top)
        nn = d.proc["netnames"][key]
        bits = [b for b in nn.get("bits", []) if isinstance(b, int)]
        if "." in name or not bits or name.startswith("$"):
            continue
        kind = ports[name]["direction"] if name in ports else "wire"
        if kind == "wire" and any(b in ffq for b in bits):
            kind = "reg"
        decl = decl_of(name, texts, nn.get("attributes", {}).get("src", ""))
        out.append(Signal(name, kind, len(nn.get("bits", [])), bits, decl))
    return out


def link_signals(cd: CellData, d: nets.Dumps, cells: Mapping[str, Any]) -> None:
    owner: dict[int, str] = {}
    for s in cd.signals:
        for b in s.bits:
            owner.setdefault(b, s.name)
    for key, c in cells.items():
        oid = "cell:" + nets.bare_name(key, d.top)
        for nm in sorted({owner[b] for b in out_bits(c) if b in owner}):
            cd.sig_links.append((f"hdl:sig.{nm}", oid, "name", "exact"))


def json_ffs(mod: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [c for c in mod["cells"].values() if str(c["type"]).startswith("$_DFF")]


def net_id(full: str) -> int | None:
    m = re.search(r"\$n(\d+)@", full)
    return int(m.group(1)) if m else None


def port_bits(mod: Mapping[str, Any]) -> set[int]:
    return {
        b
        for k, v in mod.get("netnames", {}).items()
        if "@" not in k
        for b in v.get("bits", [])
        if isinstance(b, int)
    }


def offset_fn(d: nets.Dumps, nl: blif.Netlist) -> Callable[[int], int] | None:
    """BLIF net `$nN` is JSON bit N - off(N). The offset is constant between the points where
    nets exist in one numbering and not in the other (adders, black boxes), so it is read off the
    flip-flops sorted by number (the ones with a hash name) and held until the next one."""
    pb = port_bits(d.gates)
    lat = sorted(
        nid
        for n, k in nl.drivers.items()
        if k == "latch" and n in d.net_full and (nid := net_id(d.net_full[n])) is not None
    )
    ffq = sorted(
        c["connections"]["Q"][0]
        for c in json_ffs(d.gates)
        if isinstance(c["connections"]["Q"][0], int) and c["connections"]["Q"][0] not in pb
    )
    if not lat or len(lat) != len(ffq):
        return None
    offs = [a - q for a, q in zip(lat, ffq, strict=True)]

    def off(nid: int) -> int:
        return offs[max(0, bisect.bisect_right(lat, nid) - 1)]

    return off


def verified_nets(
    d: nets.Dumps, nl: blif.Netlist, off: Callable[[int], int]
) -> tuple[set[str], int, int]:
    """BLIF nets whose JSON cell matches: a flip-flop output, or a LUT with as many inputs."""
    pb = port_bits(d.gates)
    by_nid = {nid: h for h, f in d.net_full.items() if (nid := net_id(f)) is not None}
    hash_of_bit: dict[int, str] = {}
    for nid, h in by_nid.items():
        hash_of_bit[nid - off(nid)] = h
    good: set[str] = set()
    total = 0
    for c in d.gates["cells"].values():
        t = c["type"]
        conn = c["connections"]
        if t.startswith("$_DFF"):
            qh = hash_of_bit.get(conn["Q"][0]) if isinstance(conn["Q"][0], int) else None
            if qh and nl.drivers.get(qh) == "latch":
                good.add(qh)
        elif t == "$lut" and any(isinstance(b, int) for b in conn["A"]):
            total += 1
            y = conn["Y"][0]
            lh = hash_of_bit.get(y) if isinstance(y, int) else None
            ins = {b for b in conn["A"] if isinstance(b, int) and b not in pb}
            hin = [x for x in nl.inputs.get(lh or "", []) if x in d.net_full]
            if lh and nl.drivers.get(lh) == "names" and len(ins) == len(set(hin)):
                good.add(lh)
    luts = sum(1 for h in good if nl.drivers.get(h) == "names")
    return good, luts, total


def port_bus(name: str) -> Bus | None:
    m = re.fullmatch(r"(.+)\[(\d+)\]", name)
    if m:
        return m.group(1), int(m.group(2)), "own"
    if name in ("gnd", "vcc", "unconn") or name.startswith("$"):
        return None
    return (name, None, "own") if not name.startswith("h") or len(name) != 11 else None


def net_bus(
    net: str,
    d: nets.Dumps,
    good: set[str],
    off: Callable[[int], int],
    bn: Mapping[int, tuple[str, int]],
) -> Bus | None:
    nid = net_id(d.net_full.get(net, ""))
    if nid is None:
        return port_bus(net)
    return own_bus([nid - off(nid)], bn) if net in good else None


def lut_buses(d: nets.Dumps, nl: blif.Netlist) -> tuple[dict[str, Bus], str]:
    """Bus per BLIF net: its own wire name, else the one bus it feeds. Second value: a note."""
    off = offset_fn(d, nl)
    if off is None:
        return {}, "flip-flops of the BLIF and of the netlist dump do not pair up; no bus names"
    good, luts, total = verified_nets(d, nl, off)
    if total == 0 or luts * 100 < total * 95:
        return {}, f"only {luts} of {total} LUT cells match the BLIF; bus names dropped"
    bn = bit_names(d.gates, d.top)
    own: dict[str, Bus] = {}
    for net in nl.drivers:
        b = net_bus(net, d, good, off, bn)
        if b:
            own[net] = b
    succ: dict[str, list[str]] = defaultdict(list)
    for net, srcs in nl.inputs.items():
        for s in set(srcs):
            succ[s].append(net)
    note = f"net numbers paired on the flip-flops; {luts} of {total} LUT cells verified"
    return infer(own, succ, list(nl.drivers)), note
