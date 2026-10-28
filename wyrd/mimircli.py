"""`wyrd mimir ...`: plain-text views of a Mimir store (read only); see the Mimir browser spec."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wyrd import mimirview
from wyrd.mimirview import MimirError, MimirView, Table


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    mim = sub.add_parser("mimir", help="browse a Mimir store (read only)")
    msub = mim.add_subparsers(dest="mimir_command", required=True)
    summary = msub.add_parser("summary", help="counts, sources, levels")
    summary.add_argument("db")
    designs = msub.add_parser("designs", help="list designs")
    designs.add_argument("db")
    designs.add_argument("--source")
    designs.add_argument("--filter", dest="text", default="")
    design = msub.add_parser("design", help="metrics, runs and provenance of a design")
    design.add_argument("db")
    design.add_argument("name")
    design.add_argument("--source")
    design.add_argument("--level", help="only metric records of this level")
    run = msub.add_parser("run", help="a run: flow parameters and artifacts")
    run.add_argument("db")
    run.add_argument("run_id")
    comp = msub.add_parser("compare", help="geomean ratio of a metric per config vs a base config")
    comp.add_argument("db")
    comp.add_argument("--prefix", required=True, help="source prefix, e.g. norns-placers-e10-")
    comp.add_argument("--base", required=True, help="base config label: source/arm")
    comp.add_argument("--metric", required=True)
    comp.add_argument("--level")
    for p in (designs, design, run, comp):
        p.add_argument("--csv", action="store_true", help="write the main table as CSV")
    for p in (designs, design):
        p.add_argument(
            "--limit", type=int, default=mimirview.DEFAULT_LIMIT, help="rows; 0 for no cap"
        )


def _show(t: Table, as_csv: bool) -> None:
    if as_csv:
        print(mimirview.render_csv(t), end="")
        if t.more:
            print(
                f"wyrd: warning: output truncated at {len(t.rows)} rows; raise --limit",
                file=sys.stderr,
            )
    else:
        print(mimirview.render_text(t))


def _summary(v: MimirView, args: argparse.Namespace) -> int:
    s = v.summary()
    print(f"store {v.path.name}  schema version {s.version}  {s.size_bytes} bytes")
    print("rows: " + ", ".join(f"{k}={n}" for k, n in s.counts.items()))
    print(f"levels: {', '.join(s.levels)}  distinct metrics: {s.n_metrics}")
    if s.note:
        print(f"note: {s.note}")
    if v.wal_present:
        print("note: a -wal file exists beside this store; another process may have it open")
    print()
    print(mimirview.render_text(s.sources))
    return 0


def _designs(v: MimirView, args: argparse.Namespace) -> int:
    _show(v.designs(args.source, args.text, args.limit), args.csv)
    return 0


def _design(v: MimirView, args: argparse.Namespace) -> int:
    d = v.design(args.name, args.source, args.limit, args.level)
    if args.csv:
        _show(d.metrics, True)
        return 0
    print(f"design {d.name}  sources: {', '.join(d.sources)}")
    for t in (d.metrics, d.runs, d.meta, d.lineage, d.structures):
        if t.rows:
            print(f"\n[{t.title}]")
            print(mimirview.render_text(t))
    return 0


def _run(v: MimirView, args: argparse.Namespace) -> int:
    r = v.run(args.run_id)
    if args.csv:
        _show(r.params, True)
        return 0
    for k, val in {**r.header, **{f"config.{k}": x for k, x in r.config.items()}}.items():
        print(f"{k}: {val}")
    print("\n[flow_param]")
    print(mimirview.render_text(r.params))
    print("\n[artifacts]")
    print(mimirview.render_text(r.artifacts))
    return 0


def _compare(v: MimirView, args: argparse.Namespace) -> int:
    _show(v.compare(args.prefix, args.base, args.metric, args.level).as_table(), args.csv)
    return 0


def main(args: argparse.Namespace) -> int:
    handlers = {
        "summary": _summary,
        "designs": _designs,
        "design": _design,
        "run": _run,
        "compare": _compare,
    }
    try:
        return handlers[args.mimir_command](MimirView(Path(args.db)), args)
    except MimirError as e:
        print(f"wyrd: {e}", file=sys.stderr)
        return 2
