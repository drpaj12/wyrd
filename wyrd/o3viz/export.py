"""Export an `odin3-flow --prov` run (plus VPR's kept files) as an o3viz bundle (stdlib only)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wyrd.o3viz import anchors, anchorset, blif, cells, nets, vprfiles

BUNDLE_VERSION = 1
CONF_RANK = {"exact": 4, "high": 3, "medium": 2, "low": 1, "ambiguous": 0}
PLANE_STAGES = {"hdl": "hdl", "luts": "lut", "placed": "placed"}
PLANE_ORDER = ["hdl", "cell", "lut", "clb", "placed"]

METRICS: list[dict[str, Any]] = [
    {
        "name": "is_ff",
        "unit": "1 = flip-flop",
        "planes": ["hdl", "cell", "lut", "placed"],
        "scale": "seq",
        "measurer": (
            "wyrd.o3viz.export: a $dff-type cell, a BLIF .latch, or a declared reg that a "
            "flip-flop drives"
        ),
        "source": "odin3 netlist dumps and BLIF",
    },
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
        "planes": ["hdl", "lut", "clb", "placed"],
        "scale": "seq",
        "measurer": (
            "wyrd.o3viz.export, .names depth from inputs and register/block outputs; "
            "lut and placed: the object itself; clb: max over the atoms inside; "
            "hdl: max over the LUTs linked below"
        ),
        "source": "odin3 BLIF",
    },
    {
        "name": "stage",
        "unit": "register stages",
        "planes": ["lut", "placed"],
        "scale": "seq",
        "measurer": "wyrd.o3viz.export, registers and block outputs add one to the deepest input",
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
    bus: list[str | None] = field(default_factory=list)
    bit: list[int | None] = field(default_factory=list)
    busk: list[str | None] = field(default_factory=list)
    parent: list[str | None] = field(default_factory=list)
    attach: list[str | None] = field(default_factory=list)  # a flip-flop: the object driving its D

    def set_bus(self, table: dict[str, cells.Bus]) -> None:
        """Bus columns from a table keyed by object id."""
        self.bus = [table[i][0] if i in table else None for i in self.ids]
        self.bit = [table[i][1] if i in table else None for i in self.ids]
        self.busk = [table[i][2] if i in table else None for i in self.ids]

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


def join_depth_up(hdl: Plane, lut: Plane, links: list[tuple[str, str, str, str]]) -> None:
    """Logic depth of an HDL construct: the max `logic_level` of the LUTs linked below it."""
    lvl = dict(zip(lut.ids, lut.metrics.get("logic_level", []), strict=True))
    deepest: dict[str, float] = {}
    for h, lu, _k, _c in links:
        v = lvl.get(lu)
        if v is not None and (h not in deepest or v > deepest[h]):
            deepest[h] = v
    hdl.set_metric("logic_level", deepest)


def path_rows(
    paths: list[vprfiles.SetupPath], top: str, lut_ids: set[str], placed_ids: set[str]
) -> list[dict[str, Any]]:
    """Reported setup paths as bundle rows, sorted by slack (worst first), atoms mapped to ids."""
    rows = []
    for p in sorted(paths, key=lambda q: (q.slack, q.n)):
        rows.append(
            {
                "n": p.n,
                "slack": p.slack,
                "start": p.start,
                "end": p.end,
                "lut": [i for a in p.atoms if (i := f"luts:{top}/{a}") in lut_ids],
                "placed": [i for a in p.atoms if (i := f"placed:{a}") in placed_ids],
            }
        )
    return rows


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
    stg = blif.stages_of(nl)
    plane.set_metric(
        "stage", {i: float(stg[lut_local(i)]) for i in plane.ids if lut_local(i) in stg}
    )
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
    levels = nl.levels()
    owner: dict[str, str] = {}
    cxy: dict[str, tuple[int, int, int]] = {}
    links: list[tuple[str, str, str, str]] = []
    cl_metrics: dict[str, dict[str, float]] = {
        k: {}
        for k in (
            "atoms",
            "luts_inside",
            "ffs_inside",
            "x",
            "y",
            "slack_worst",
            "paths_through",
            "logic_level",
        )
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
        lvls = [levels[a] for a in atoms if a in levels]
        if lvls:
            cl_metrics["logic_level"][cid] = float(max(lvls))
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
        k: {} for k in ("fanin", "fanout", "logic_level", "stage", "slack_worst", "paths_through")
    }
    fo, lv, stg = nl.fanout(), levels, blif.stages_of(nl)
    for o in placed_objs:
        pid, name = o["id"], o["name"]
        drv = nl.drivers.get(name)
        placed.add(pid, o["kind"], drv or "pad", o["origin"], name, src_of(o))
        if name in nl.drivers:
            pm["fanin"][pid] = float(len(set(nl.inputs[name])))
            pm["logic_level"][pid] = float(lv.get(name, 0))
            pm["stage"][pid] = float(stg.get(name, 0))
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
    out: dict[str, Any] = {
        "stage": p.stage,
        "ids": p.ids,
        "kind": p.kind,
        "type": p.type,
        "origin": p.origin,
        "name": p.name,
        "src": p.src,
        "metrics": cols,
    }
    if any(b is not None for b in p.bus):
        out.update({"bus": p.bus, "bit": p.bit, "busk": p.busk})
    if any(b is not None for b in p.parent):
        out["parent"] = p.parent
    if any(b is not None for b in p.attach):
        out["attach"] = p.attach
    return out


def read_texts(names: set[str], search: list[Path]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for n in sorted(names):
        for d in search:
            if (d / n).is_file():
                out[n] = (d / n).read_text(encoding="utf-8", errors="replace").split("\n")
                break
    return out


def try_dumps(flow: Path, top: str, search: list[Path]) -> tuple[nets.Dumps | None, str]:
    """The extra Odin III run; (None, reason) when it cannot be done (the bundle then has no cell
    plane and no bus names)."""
    with tempfile.TemporaryDirectory() as t:
        try:
            nets.run_dumps(flow, Path(t), search)
            return nets.load_dumps(Path(t), top), ""
        except (nets.NetsError, OSError, KeyError, ValueError, subprocess.SubprocessError) as e:
            msg = re.sub(r"/[^\s'\"]+", lambda m: m.group(0).rsplit("/", 1)[-1], str(e))
            return None, f"{type(e).__name__}: {msg}"


def pad_metrics(p: Plane) -> None:
    for vals in p.metrics.values():
        vals.extend([None] * (len(p.ids) - len(vals)))


def add_signals(hdl: Plane, sigs: list[cells.Signal], parent: dict[str, str]) -> None:
    for s in sigs:
        src = [s.decl] if s.decl else []
        hdl.add(f"hdl:sig.{s.name}", "signal", s.kind, "hdl", s.name, src)
    pad_metrics(hdl)
    hdl.set_metric("is_ff", {f"hdl:sig.{s.name}": 1.0 for s in sigs if s.kind == "reg"})
    hdl.parent = [parent.get(i) for i in hdl.ids]
    hdl.set_bus({f"hdl:sig.{s.name}": (s.name, None, "own") for s in sigs})


def cell_plane(cd: cells.CellData) -> Plane:
    plane = Plane("cell")
    for i, t, n, src in zip(cd.ids, cd.types, cd.names, cd.src, strict=True):
        plane.add(i, "cell", t, "hdl", n, src)
    plane.set_metric("is_ff", {i: 1.0 for i in cd.ids if i in cd.ff})
    plane.set_bus(cd.bus)
    return plane


def apply_lut_buses(
    lut: Plane, placed: Plane, table: dict[str, cells.Bus], top: str
) -> list[tuple[str, str, str, str]]:
    """Bus columns on the lut and placed planes; the signal links of the named nets."""
    lut.set_bus({i: table[lut_local(i)] for i in lut.ids if lut_local(i) in table})
    placed.set_bus(
        {i: table[n] for i, n in zip(placed.ids, placed.name, strict=True) if n in table}
    )
    ffs = {i: 1.0 for i, t in zip(lut.ids, lut.type, strict=True) if t == "latch"}
    lut.set_metric("is_ff", ffs)
    placed.set_metric(
        "is_ff", {i: 1.0 for i, t in zip(placed.ids, placed.type, strict=True) if t == "latch"}
    )
    out = []
    for i, b, k in zip(lut.ids, lut.bus, lut.busk, strict=True):
        if b is not None and k == "own":
            out.append((f"hdl:sig.{b}", i, "name", "exact"))
    return out


def ff_attach(lut: Plane, placed: Plane, nl: blif.Netlist, top: str) -> None:
    """Each flip-flop is drawn as a small piece of the object that drives its D input."""
    pid = dict(zip(placed.name, placed.ids, strict=True))
    lids = set(lut.ids)

    def drv(net: str) -> str | None:
        d = nl.inputs.get(net, [None])[0]
        return d if d is not None and nl.drivers.get(d) == "names" else None

    lut.attach = [
        f"luts:{top}/{d}"
        if t == "latch" and (d := drv(lut_local(i))) and f"luts:{top}/{d}" in lids
        else None
        for i, t in zip(lut.ids, lut.type, strict=True)
    ]
    placed.attach = [
        pid.get(d) if t == "latch" and (d := drv(n)) else None
        for n, t in zip(placed.name, placed.type, strict=True)
    ]


def ff_links(cell: Plane, lut: Plane) -> list[tuple[str, str, str, str]]:
    """A flip-flop cell links to the latches of the same bus (word cell to bit latches)."""
    latches: dict[str, list[str]] = {}
    for i, b, t in zip(lut.ids, lut.bus, lut.type, strict=True):
        if b is not None and t == "latch":
            latches.setdefault(b, []).append(i)
    isff = cell.metrics.get("is_ff", [])
    return [
        (c, lid, "name", "medium")
        for c, b, f in zip(cell.ids, cell.bus, isff, strict=True)
        if f == 1.0 and b is not None
        for lid in latches.get(b, [])
    ]


def build_planes(
    ff: FlowFiles,
    flow: Path,
    search: list[Path],
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
    join_depth_up(hdl, lut, links)
    texts = read_texts({s[0] for srcs in hdl.src for s in srcs}, search)
    dumps, note = try_dumps(flow, top, search)
    cd = (
        cells.build_cells(dumps, {o["id"]: o for o in objs.get("hdl", [])}, parent, texts, lut.ids)
        if dumps
        else None
    )
    if cd:
        add_signals(hdl, cd.signals, parent)
    clb, placed, plinks, bottom, cxy = build_clb_and_placed(
        vprfiles.read_net(ff.net),
        vprfiles.read_place(ff.place),
        objs.get("placed", []),
        lut_ids,
        nl,
        timing,
        top,
    )
    cplane = cell_plane(cd) if cd else None
    sigl: list[tuple[str, str, str, str]] = []
    bus_note = ""
    if dumps and cd and cplane:
        table, bus_note = cells.lut_buses(dumps, nl)
        sigl = apply_lut_buses(lut, placed, table, top) + cd.sig_links + ff_links(cplane, lut)
        links.extend(cd.links)
    else:
        lut.set_metric(
            "is_ff", {i: 1.0 for i, t in zip(lut.ids, lut.type, strict=True) if t == "latch"}
        )
        placed.set_metric(
            "is_ff", {i: 1.0 for i, t in zip(placed.ids, placed.type, strict=True) if t == "latch"}
        )
    ff_attach(lut, placed, nl, top)
    links.extend(sigl)
    all_ids = set(hdl.ids) | set(lut.ids) | set(clb.ids) | set(placed.ids)
    if cplane:
        all_ids |= set(cplane.ids)
    dropped = 0
    for lk in plinks:
        if lk[0] in all_ids and lk[1] in all_ids:
            links.append(lk)
        else:
            dropped += 1
    planes = {"hdl": hdl, "lut": lut, "clb": clb, "placed": placed}
    planes["cell"] = cplane or Plane("cell")
    edges = [
        (f"luts:{top}/{a}", f"luts:{top}/{b}", k)
        for a, b, k in nl.edges()
        if f"luts:{top}/{a}" in lut_ids and f"luts:{top}/{b}" in lut_ids
    ]
    meta = {
        "index": index,
        "top": top,
        "dropped_links": dropped,
        "notes": [n for n in (note and f"cell plane off: {note}", bus_note) if n],
        "signals": cd.signals if cd else [],
        "selects": cd.selects if cd else 0,
        "grid": vprfiles.read_place(ff.place).grid,
        "paths": path_rows(vprfiles.read_setup_paths(ff.timing), top, lut_ids, set(placed.ids))
        if ff.timing
        else [],
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


def compact_links(
    order: list[str], planes: dict[str, Plane], links: list[tuple[str, str, str, str]]
) -> dict[str, Any]:
    """Links as integer rows [from, to, kind, confidence].

    Object numbers count through the plane files in manifest order; kinds and confidences index the
    two tables.
    """
    num = {oid: n for n, oid in enumerate(i for p in order for i in planes[p].ids)}
    kinds = sorted({lk[2] for lk in links})
    confs = sorted({lk[3] for lk in links})
    rows = [[num[a], num[b], kinds.index(k), confs.index(c)] for a, b, k, c in links]
    return {"kinds": kinds, "confidences": confs, "rows": rows}


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(obj), encoding="utf-8", newline="\n")


def spread_cells(aset: dict[str, Any]) -> None:
    """Cells linked to the same LUTs get the same mean position: spread them on a small grid."""
    cp = aset["pos"].get("cell")
    if cp:
        moved = anchors.spread_same({i: (xy[0], xy[1]) for i, xy in cp.items()}, 1.4)
        aset["pos"]["cell"] = {i: list(xy) for i, xy in moved.items()}


def bus_table(planes: dict[str, Plane], sigs: list[cells.Signal]) -> list[dict[str, Any]]:
    """Every bus with its width, declaration line and object counts per plane."""
    info: dict[str, dict[str, Any]] = {}
    for s in sigs:
        info[s.name] = {
            "name": s.name,
            "kind": s.kind,
            "width": s.width,
            "decl": s.decl,
            "counts": {},
        }
    for pname, p in planes.items():
        for b, bit in zip(p.bus, p.bit, strict=True):
            if b is None:
                continue
            e = info.setdefault(
                b, {"name": b, "kind": "net", "width": 0, "decl": None, "counts": {}}
            )
            e["counts"][pname] = e["counts"].get(pname, 0) + 1
            e["width"] = max(e["width"], (bit or 0) + 1)
    return sorted(info.values(), key=lambda e: e["name"])


def export_bundle(flow: Path, out: Path, benchmark: str, src_dirs: list[Path]) -> dict[str, Any]:
    """Write the bundle directory `out` and return its manifest."""
    ff = find_files(flow)
    meta, planes, links, edges, parent, bottom, fallback = build_planes(
        ff, flow, [*src_dirs, flow.parent]
    )
    order = [p for p in PLANE_ORDER if planes[p].ids]
    grid = meta["grid"]
    anchor_sets = anchorset.compute_all(
        order, planes, links, edges, parent, bottom, fallback, tuple(grid)
    )
    for aset in anchor_sets.values():
        spread_cells(aset)
    sources = find_sources(meta["index"], planes, [*src_dirs, flow.parent])
    for p in order:
        write_json(out / "planes" / f"{p}.json", plane_json(planes[p]))
    write_json(out / "links.json", compact_links(order, planes, links))
    write_json(out / "edges" / "lut.json", [list(e) for e in edges])
    if meta["paths"]:
        write_json(
            out / "paths.json",
            {"source": "vpr report_timing.setup.rpt", "paths": meta["paths"]},
        )
    for name, aset in anchor_sets.items():
        write_json(out / "anchors" / f"{name}.json", aset)
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
        "paths": len(meta["paths"]),
        "dropped_links": meta["dropped_links"],
        "unanchored": len(anchor_sets["placement"]["unanchored"]),
        "anchors": sorted(anchor_sets),
        "metrics": metrics,
        "missing_planes": [
            s for s in ("ir", "gates", "ble", "routed") if s != "ir" or "cell" not in order
        ],
        "buses": bus_table(planes, meta["signals"]),
        "notes": meta["notes"],
        "select_cells": meta["selects"],
        "grid": list(grid),
    }
    write_json(out / "manifest.json", manifest)
    return manifest
