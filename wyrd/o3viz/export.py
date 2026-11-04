"""Export an `odin3-flow --prov` run (plus VPR's kept files) as an o3viz bundle (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wyrd.o3viz import anchors, blif, vprfiles

BUNDLE_VERSION = 1
CONF_RANK = {"exact": 4, "high": 3, "medium": 2, "low": 1, "ambiguous": 0}
PLANE_STAGES = {"hdl": "hdl", "luts": "lut", "placed": "placed"}
PLANE_ORDER = ["hdl", "lut", "clb", "placed"]

METRICS: list[dict[str, Any]] = [
    {
        "name": "depth",
        "unit": "levels",
        "planes": ["hdl"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the HDL construct tree",
        "source": "prov step read",
    },
    {
        "name": "children",
        "unit": "count",
        "planes": ["hdl"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the HDL construct tree",
        "source": "prov step read",
    },
    {
        "name": "span_lines",
        "unit": "lines",
        "planes": ["hdl"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the source span",
        "source": "prov step read",
    },
    {
        "name": "luts_below",
        "unit": "count",
        "planes": ["hdl"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export, LUT objects whose chain reaches this construct",
        "source": "prov step map links",
    },
    {
        "name": "fanin",
        "unit": "nets",
        "planes": ["lut", "placed"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the mapped BLIF",
        "source": "odin3 BLIF",
    },
    {
        "name": "fanout",
        "unit": "nets",
        "planes": ["lut", "placed"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the mapped BLIF",
        "source": "odin3 BLIF",
    },
    {
        "name": "logic_level",
        "unit": "levels",
        "planes": ["lut", "placed"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export, .names depth from inputs and register/block outputs",
        "source": "odin3 BLIF",
    },
    {
        "name": "hdl_links",
        "unit": "count",
        "planes": ["lut"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export, links to HDL constructs",
        "source": "prov step map",
    },
    {
        "name": "weakest_confidence",
        "unit": "rank 0-4 (4 exact)",
        "planes": ["lut"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export, weakest link confidence",
        "source": "prov step map",
    },
    {
        "name": "slack_worst",
        "unit": "ns",
        "planes": ["lut", "clb", "placed"],
        "scale": "div",
        "measurer": "VPR setup timing report, worst slack of the reported paths through the object",
        "source": "vpr report_timing.setup.rpt",
    },
    {
        "name": "paths_through",
        "unit": "count",
        "planes": ["lut", "clb", "placed"],
        "scale": "seq",
        "measurer": "VPR setup timing report, reported paths through the object",
        "source": "vpr report_timing.setup.rpt",
    },
    {
        "name": "atoms",
        "unit": "count",
        "planes": ["clb"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the VPR .net",
        "source": "vpr .net",
    },
    {
        "name": "luts_inside",
        "unit": "count",
        "planes": ["clb"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the VPR .net and BLIF",
        "source": "vpr .net",
    },
    {
        "name": "ffs_inside",
        "unit": "count",
        "planes": ["clb"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export from the VPR .net and BLIF",
        "source": "vpr .net",
    },
    {
        "name": "x",
        "unit": "grid",
        "planes": ["clb", "placed"],
        "scale": "seq",
        "measurer": "VPR placement",
        "source": "vpr .place",
    },
    {
        "name": "y",
        "unit": "grid",
        "planes": ["clb", "placed"],
        "scale": "seq",
        "measurer": "VPR placement",
        "source": "vpr .place",
    },
]


class ExportError(Exception):
    pass


@dataclass
class Plane:
    stage: str
    ids: list[str] = field(default_factory=list)
    kind: list[str] = field(default_factory=list)
    type: list[str] = field(default_factory=list)
    origin: list[str] = field(default_factory=list)
    name: list[str] = field(default_factory=list)
    src: list[list[list[str]]] = field(default_factory=list)
    metrics: dict[str, list[float | None]] = field(default_factory=dict)

    def add(
        self,
        oid: str,
        kind: str,
        typ: str,
        origin: str,
        name: str,
        src: list[list[str]] | None = None,
    ) -> None:
        self.ids.append(oid)
        self.kind.append(kind)
        self.type.append(typ)
        self.origin.append(origin)
        self.name.append(name)
        self.src.append(src or [])

    def set_metric(self, key: str, values: dict[str, float]) -> None:
        self.metrics[key] = [values.get(i) for i in self.ids]


@dataclass(frozen=True)
class FlowFiles:
    prov: Path
    blif: Path
    net: Path
    place: Path
    timing: Path | None
    record: Path | None


def find_files(flow: Path) -> FlowFiles:
    prov = flow / "prov"
    if not (prov / "index.json").is_file():
        raise ExportError(
            f"no prov/index.json in {flow.name}: run odin3-flow --prov, then odin3-prov-post "
            "and odin3-prov-steps"
        )
    blifs = sorted(p for p in (flow / "odin3").glob("*.blif"))
    nets = sorted(p for p in (flow / "vpr" / "run").glob("*.net"))
    places = sorted(p for p in (flow / "vpr" / "run").glob("*.place"))
    if not (blifs and nets and places):
        raise ExportError(
            "need odin3/*.blif and vpr/run/*.net and *.place (run odin3-flow with --keep-results)"
        )
    timing = flow / "vpr" / "run" / "report_timing.setup.rpt"
    record = flow / "mimir-run.json"
    return FlowFiles(
        prov,
        blifs[0],
        nets[0],
        places[0],
        timing if timing.is_file() else None,
        record if record.is_file() else None,
    )


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def read_steps(prov: Path) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    index = json.loads((prov / "index.json").read_text(encoding="utf-8"))
    objs: dict[str, list[dict[str, Any]]] = {}
    for step in index["steps"]:
        if step.get("objects"):
            objs[step["stage"]] = read_jsonl(prov / step["objects"])
    return index, objs


def span_lines(span: str) -> float | None:
    try:
        a, b = span.split("-", 1)
        return float(int(b.split(".", 1)[0]) - int(a.split(".", 1)[0]) + 1)
    except ValueError:
        return None


def src_of(o: dict[str, Any]) -> list[list[str]]:
    return [[s["file"], s["span"]] for s in o.get("src", [])]


def build_hdl(
    objs: list[dict[str, Any]], lut_links: dict[str, int]
) -> tuple[Plane, dict[str, str]]:
    plane = Plane("hdl")
    parent: dict[str, str] = {}
    for o in objs:
        plane.add(
            o["id"], o["kind"], o["attrs"].get("level", ""), o["origin"], o["name"], src_of(o)
        )
        if o["attrs"].get("parent"):
            parent[o["id"]] = o["attrs"]["parent"]
    depth: dict[str, float] = {}
    kids: dict[str, float] = {}
    for oid in plane.ids:
        d, cur = 0, oid
        while cur in parent and d < 10_000:
            cur = parent[cur]
            d += 1
        depth[oid] = float(d)
        if oid in parent:
            kids[parent[oid]] = kids.get(parent[oid], 0.0) + 1
    plane.set_metric("depth", depth)
    plane.set_metric("children", {i: kids.get(i, 0.0) for i in plane.ids})
    plane.set_metric(
        "span_lines",
        {
            i: v
            for i, s in zip(plane.ids, plane.src, strict=True)
            if s and (v := span_lines(s[0][1])) is not None
        },
    )
    plane.set_metric("luts_below", {i: float(lut_links.get(i, 0)) for i in plane.ids})
    return plane, parent


def lut_local(oid: str) -> str:
    return oid.split("/", 1)[1] if "/" in oid else oid.split(":", 1)[1]


def build_lut(
    objs: list[dict[str, Any]], nl: blif.Netlist, timing: vprfiles.AtomTiming | None
) -> Plane:
    plane = Plane("lut")
    levels, fanout = nl.levels(), nl.fanout()
    fanin: dict[str, float] = {}
    lvl: dict[str, float] = {}
    fo: dict[str, float] = {}
    hl: dict[str, float] = {}
    wc: dict[str, float] = {}
    for o in objs:
        net = lut_local(o["id"])
        drv = nl.drivers.get(net, "")
        plane.add(o["id"], o["kind"], drv or o["kind"], o["origin"], o["name"], src_of(o))
        hdl = [lk for lk in o.get("links", []) if lk["to"].startswith("hdl:")]
        hl[o["id"]] = float(len(hdl))
        if o.get("links"):
            wc[o["id"]] = float(min(CONF_RANK.get(lk["confidence"], 0) for lk in o["links"]))
        if net in nl.drivers:
            fanin[o["id"]] = float(len(set(nl.inputs[net])))
            lvl[o["id"]] = float(levels.get(net, 0))
        if net in fanout:
            fo[o["id"]] = float(fanout[net])
    plane.set_metric("fanin", fanin)
    plane.set_metric("fanout", fo)
    plane.set_metric("logic_level", lvl)
    plane.set_metric("hdl_links", hl)
    plane.set_metric("weakest_confidence", wc)
    if timing:
        plane.set_metric(
            "slack_worst",
            {
                i: timing.worst_slack[lut_local(i)]
                for i in plane.ids
                if lut_local(i) in timing.worst_slack
            },
        )
        plane.set_metric(
            "paths_through",
            {
                i: float(timing.npaths[lut_local(i)])
                for i in plane.ids
                if lut_local(i) in timing.npaths
            },
        )
    return plane


def build_clb_and_placed(
    clusters: list[vprfiles.Cluster],
    pl: vprfiles.Placement,
    placed_objs: list[dict[str, Any]],
    lut_ids: set[str],
    nl: blif.Netlist,
    timing: vprfiles.AtomTiming | None,
    top: str,
) -> tuple[
    Plane,
    Plane,
    list[tuple[str, str, str, str]],
    dict[str, anchors.Pos],
    dict[str, tuple[int, int, int]],
]:
    clb, placed = Plane("clb"), Plane("placed")
    owner: dict[str, str] = {}
    cxy: dict[str, tuple[int, int, int]] = {}
    links: list[tuple[str, str, str, str]] = []
    cl_metrics: dict[str, dict[str, float]] = {
        k: {}
        for k in ("atoms", "luts_inside", "ffs_inside", "x", "y", "slack_worst", "paths_through")
    }
    seen_ids: set[str] = set()
    for k, c in enumerate(clusters):
        cid = f"clb:{c.name}" if f"clb:{c.name}" not in seen_ids else f"clb:{c.name}#{k}"
        seen_ids.add(cid)
        clb.add(cid, c.kind, c.instance, "hdl", c.name)
        xyz = pl.xy.get(c.name)
        if xyz:
            cxy[cid] = xyz
            cl_metrics["x"][cid], cl_metrics["y"][cid] = float(xyz[0]), float(xyz[1])
        atoms = c.atoms
        luts = [a for a in atoms if f"luts:{top}/{a}" in lut_ids]
        cl_metrics["atoms"][cid] = float(len(atoms))
        cl_metrics["luts_inside"][cid] = float(
            sum(1 for a in atoms if nl.drivers.get(a) == "names")
        )
        cl_metrics["ffs_inside"][cid] = float(sum(1 for a in atoms if nl.drivers.get(a) == "latch"))
        if timing:
            sl = [timing.worst_slack[a] for a in atoms if a in timing.worst_slack]
            if sl:
                cl_metrics["slack_worst"][cid] = min(sl)
            cl_metrics["paths_through"][cid] = float(sum(timing.npaths.get(a, 0) for a in atoms))
        for a in atoms:
            owner.setdefault(a, cid)
        for a in luts:
            links.append((f"luts:{top}/{a}", cid, "pack", "exact"))
    for key, vals in cl_metrics.items():
        clb.set_metric(key, vals)

    pxy: dict[str, float] = {}
    py: dict[str, float] = {}
    members: dict[tuple[int, int], list[str]] = {}
    pm: dict[str, dict[str, float]] = {
        k: {} for k in ("fanin", "fanout", "logic_level", "slack_worst", "paths_through")
    }
    fo, lv = nl.fanout(), nl.levels()
    for o in placed_objs:
        pid, name = o["id"], o["name"]
        drv = nl.drivers.get(name)
        placed.add(pid, o["kind"], drv or "pad", o["origin"], name, src_of(o))
        if name in nl.drivers:
            pm["fanin"][pid] = float(len(set(nl.inputs[name])))
            pm["logic_level"][pid] = float(lv.get(name, 0))
        if name in fo:
            pm["fanout"][pid] = float(fo[name])
        if timing and name in timing.worst_slack:
            pm["slack_worst"][pid] = timing.worst_slack[name]
            pm["paths_through"][pid] = float(timing.npaths[name])
        oid = owner.get(name)
        if oid:
            links.append((oid, pid, "pack", "exact"))
            if oid in cxy:
                members.setdefault((cxy[oid][0], cxy[oid][1]), []).append(pid)
                pxy[pid], py[pid] = float(cxy[oid][0]), float(cxy[oid][1])
        for lk in o.get("links", []):
            links.append((lk["to"], pid, lk["kind"], lk["confidence"]))
    placed.set_metric("x", pxy)
    placed.set_metric("y", py)
    for key, vals in pm.items():
        placed.set_metric(key, vals)
    return clb, placed, links, anchors.tile_spread(members), cxy


def dumps(obj: Any) -> str:
    return (
        json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        + "\n"
    )


def plane_json(p: Plane) -> dict[str, Any]:
    cols = {
        k: [None if v is None else round(v, 6) for v in vals]
        for k, vals in sorted(p.metrics.items())
    }
    return {
        "stage": p.stage,
        "ids": p.ids,
        "kind": p.kind,
        "type": p.type,
        "origin": p.origin,
        "name": p.name,
        "src": p.src,
        "metrics": cols,
    }


def build_planes(
    ff: FlowFiles,
) -> tuple[
    dict[str, Any],
    dict[str, Plane],
    list[tuple[str, str, str, str]],
    list[tuple[str, str, str]],
    dict[str, str],
    dict[str, anchors.Pos],
    dict[str, anchors.Pos],
]:
    index, objs = read_steps(ff.prov)
    top = index["top"]
    nl = blif.read_blif(ff.blif)
    timing = vprfiles.read_setup_report(ff.timing) if ff.timing else None
    lut_objs = objs.get("luts", [])
    lut_ids = {o["id"] for o in lut_objs}
    hdl_ids = {o["id"] for o in objs.get("hdl", [])}
    links: list[tuple[str, str, str, str]] = []
    below: dict[str, int] = {}
    for o in lut_objs:
        for lk in o.get("links", []):
            if lk["to"] in hdl_ids:
                links.append((lk["to"], o["id"], lk["kind"], lk["confidence"]))
                below[lk["to"]] = below.get(lk["to"], 0) + 1
    hdl, parent = build_hdl(objs.get("hdl", []), below)
    lut = build_lut(lut_objs, nl, timing)
    clb, placed, plinks, bottom, cxy = build_clb_and_placed(
        vprfiles.read_net(ff.net),
        vprfiles.read_place(ff.place),
        objs.get("placed", []),
        lut_ids,
        nl,
        timing,
        top,
    )
    all_ids = set(hdl.ids) | set(lut.ids) | set(clb.ids) | set(placed.ids)
    dropped = 0
    for lk in plinks:
        if lk[0] in all_ids and lk[1] in all_ids:
            links.append(lk)
        else:
            dropped += 1
    planes = {"hdl": hdl, "lut": lut, "clb": clb, "placed": placed}
    edges = [
        (f"luts:{top}/{a}", f"luts:{top}/{b}", k)
        for a, b, k in nl.edges()
        if f"luts:{top}/{a}" in lut_ids and f"luts:{top}/{b}" in lut_ids
    ]
    meta = {
        "index": index,
        "top": top,
        "dropped_links": dropped,
        "grid": vprfiles.read_place(ff.place).grid,
    }
    fallback = {cid: (float(x), float(y)) for cid, (x, y, _) in cxy.items()}
    return meta, planes, sorted(set(links)), sorted(edges), parent, bottom, fallback


def find_sources(
    index: dict[str, Any], planes: dict[str, Plane], search: list[Path]
) -> dict[str, Path]:
    names = {s[0] for p in planes.values() for srcs in p.src for s in srcs}
    found: dict[str, Path] = {}
    for n in sorted(names):
        for d in search:
            cand = d / n
            if cand.is_file():
                found[n] = cand
                break
    return found


def tool_versions(record: Path | None) -> dict[str, str]:
    if record is None:
        return {}
    tools = json.loads(record.read_text(encoding="utf-8")).get("tools", {})
    out: dict[str, str] = {}
    for key, t in sorted(tools.items()):
        ver = str(t.get("binary_version", "")).splitlines()
        out[key] = (ver[0] if ver else "") + (f" commit {t['commit']}" if t.get("commit") else "")
    return out


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj), encoding="utf-8", newline="\n")


def export_bundle(flow: Path, out: Path, benchmark: str, src_dirs: list[Path]) -> dict[str, Any]:
    """Write the bundle directory `out` and return its manifest."""
    ff = find_files(flow)
    meta, planes, links, edges, parent, bottom, fallback = build_planes(ff)
    order = [p for p in PLANE_ORDER if planes[p].ids]
    ids = {p: planes[p].ids for p in order}
    grid = meta["grid"]
    centre = ((grid[0] + 1) / 2, (grid[1] + 1) / 2)
    ulinks = [(a, b) for a, b, _, _ in links]
    pos, unanchored = anchors.placement_anchor(
        order, ids, ulinks, bottom, centre, parent, [(a, b) for a, b, _ in edges], fallback
    )
    sources = find_sources(meta["index"], planes, [*src_dirs, flow.parent])
    for p in order:
        write_json(out / "planes" / f"{p}.json", plane_json(planes[p]))
    write_json(out / "links.json", [list(lk) for lk in links])
    write_json(out / "edges" / "lut.json", [list(e) for e in edges])
    write_json(
        out / "anchors" / "placement.json",
        {
            "bounds": [0, 0, grid[0] + 1, grid[1] + 1],
            "unanchored": unanchored,
            "pos": {p: {i: list(xy) for i, xy in pos[p].items()} for p in order},
        },
    )
    hashes: dict[str, str] = {}
    for name, path in sources.items():
        dest = out / "hdl" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    metrics = [
        m
        for m in METRICS
        if any(
            planes[p].metrics.get(m["name"])
            and any(v is not None for v in planes[p].metrics[m["name"]])
            for p in order
            if p in m["planes"]
        )
    ]
    manifest = {
        "bundle_version": BUNDLE_VERSION,
        "benchmark": benchmark,
        "flow": "vtr",
        "design": meta["index"]["design"],
        "top": meta["top"],
        "tools": tool_versions(ff.record),
        "inputs": hashes,
        "planes": order,
        "counts": {p: len(planes[p].ids) for p in order},
        "links": len(links),
        "dropped_links": meta["dropped_links"],
        "unanchored": len(unanchored),
        "anchors": ["placement"],
        "metrics": metrics,
        "missing_planes": [s for s in ("ir", "gates", "ble", "routed")],
        "grid": list(grid),
    }
    write_json(out / "manifest.json", manifest)
    return manifest
