"""`wyrd mux-cost`: what the muxes of a design cost, tied to the HDL lines that made them."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wyrd import settings
from wyrd.muxcost import flow, render, report
from wyrd.project import ConfigError, load_project
from wyrd.store import Store

NET_TIMING = "report_net_timing.csv"
WORDS = "words"


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser(
        "mux-cost", help="mux cost report: bits, LUTs and select lateness per HDL line"
    )
    p.add_argument("files", nargs="*", help="Verilog files of the design")
    p.add_argument("--top", help="top module (default: the one uninstantiated module)")
    p.add_argument("--project", metavar="DIR", help="a Wyrd project; use with --run")
    p.add_argument("--run", metavar="KEY", help="run key (or a prefix of 6 or more characters)")
    p.add_argument("--from", dest="from_dir", metavar="DIR", help="re-read the output dir of a run")
    p.add_argument("--out", metavar="DIR", help="output directory (default: mux-cost-out)")
    p.add_argument("--json", action="store_true", help="print the report as JSON (schema 1)")
    p.add_argument("--sort", choices=report.SORTS, default="bits", help="row order (default bits)")
    p.add_argument("--limit", type=int, metavar="N", help="show the first N rows of each table")
    p.add_argument("--net-timing", metavar="FILE", help="VPR report_net_timing.csv of a routed run")
    p.add_argument("--odin3", metavar="PATH", help="odin3 binary (default: machine settings)")
    p.add_argument(
        "--odin3-flow", metavar="PATH", help="odin3-flow script (default: machine settings)"
    )
    p.add_argument("--timeout", type=int, default=flow.DEFAULT_TIMEOUT_S, metavar="S")


def _err(msg: str) -> int:
    print(f"wyrd mux-cost: {msg}", file=sys.stderr)
    return 2


def _fail(msg: str) -> int:
    print(f"wyrd mux-cost: {msg}", file=sys.stderr)
    return 1


def _words_inputs(out: Path) -> report.Inputs | None:
    """The files of an earlier run in ``out``."""
    words = out / WORDS
    blifs = sorted(words.glob("*.blif"))
    snap = words / flow.SNAPSHOT
    if len(blifs) != 1 or not snap.is_file():
        return None
    return report.Inputs(
        snap,
        snap.with_name(snap.name + ".names"),
        blifs[0],
        blifs[0].with_name(blifs[0].name + ".names"),
    )


def _from_project(args: argparse.Namespace) -> tuple[tuple[Path, ...], str | None, Path] | str:
    """(files, top, run dir) of the run, or an error text."""
    db = Path(args.project) / "wyrd.db"
    if not db.is_file():
        return f"{db} not found (nothing has run in {args.project})"
    if len(args.run) < 6:
        return "key prefix needs at least 6 characters"
    try:
        rows = [r for r in Store.open_readonly(db).rows() if str(r["key"]).startswith(args.run)]
        project = load_project(Path(args.project) / "wyrd.toml")
    except (OSError, ConfigError, ValueError) as e:
        return str(e)
    if len(rows) != 1:
        return f"{len(rows)} runs start with {args.run!r}"
    design = project.designs.get(str(rows[0]["design"]))
    if design is None:
        return f"design {rows[0]['design']!r} is not in the project file"
    return design.files, design.top, Path(str(rows[0]["run_dir"]))


def _tools(args: argparse.Namespace) -> tuple[str, str]:
    s = settings.load(None, {})
    return (args.odin3 or s.tools["odin3"], args.odin3_flow or s.tools["odin3_flow"])


def _inputs(args: argparse.Namespace) -> tuple[report.Inputs, Path | None] | int:
    """The analysis inputs (running Odin III when needed) and the run dir to look for timing in."""
    if args.from_dir:
        found = _words_inputs(Path(args.from_dir))
        return (found, None) if found else _err(f"no earlier mux-cost output in {args.from_dir}")
    run_dir: Path | None = None
    files, top, out = tuple(Path(f) for f in args.files), args.top, Path(args.out or "mux-cost-out")
    if args.project:
        got = _from_project(args)
        if isinstance(got, str):
            return _err(got)
        files, top, run_dir = got
        out = Path(args.out) if args.out else run_dir / "mux-cost"
    if not files:
        return _err("give Verilog files, --project DIR --run KEY, or --from DIR")
    odin3, odin3_flow = _tools(args)
    return flow.run(flow.FlowSpec(files, top, out, odin3_flow, odin3, args.timeout)), run_dir


def _with_timing(
    inp: report.Inputs, args: argparse.Namespace, run_dir: Path | None
) -> report.Inputs:
    given = Path(args.net_timing) if args.net_timing else None
    if given is not None:
        return report.Inputs(*_core(inp), net_timing=given, lut_k=inp.lut_k)
    if run_dir is None:
        return inp
    found = sorted(run_dir.glob(f"**/{NET_TIMING}"))
    if not found:
        return inp
    return report.Inputs(*_core(inp), net_timing=found[0], lut_k=inp.lut_k, timing_optional=True)


def _core(inp: report.Inputs) -> tuple[Path, Path, Path, Path]:
    return (inp.snapshot, inp.snapshot_map, inp.blif, inp.blif_map)


def main(args: argparse.Namespace) -> int:
    if args.limit is not None and args.limit < 1:
        return _err("--limit must be at least 1")
    if bool(args.project) != bool(args.run):
        return _err("--project and --run go together")
    if sum(bool(x) for x in (args.files, args.project, args.from_dir)) != 1:
        return _err("give exactly one of: Verilog files, --project DIR --run KEY, --from DIR")
    try:
        made = _inputs(args)
        if isinstance(made, int):
            return made
        inp = _with_timing(made[0], args, made[1])
        doc = report.build(inp, args.sort, args.limit)
    except (flow.FlowError, report.ReportError, ValueError, OSError) as e:
        return _fail(str(e))
    print(json.dumps(doc, indent=1) if args.json else render.render(doc))
    return 0
