"""`wyrd viz export|serve`: the o3viz 3D provenance viewer (spec 2026-11-03)."""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from wyrd.o3viz import export, serve


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    viz = sub.add_parser("viz", help="3D provenance viewer for one benchmark (o3viz)")
    vsub = viz.add_subparsers(dest="viz_command", required=True)
    ex = vsub.add_parser("export", help="write a bundle from an odin3-flow --prov run directory")
    ex.add_argument("flow", metavar="FLOW_DIR", help="odin3-flow output (prov/, odin3/, vpr/run/)")
    ex.add_argument("--out", required=True, metavar="BUNDLE_DIR")
    ex.add_argument("--benchmark", metavar="SUITE:DESIGN", help="name shown in the viewer")
    ex.add_argument(
        "--src", action="append", default=[], metavar="DIR", help="where the HDL files are"
    )
    sv = vsub.add_parser("serve", help="serve the viewer and one bundle on 127.0.0.1")
    sv.add_argument("bundle", metavar="BUNDLE_DIR")
    sv.add_argument("--port", type=int, default=8765)


def main(args: argparse.Namespace) -> int:
    if args.viz_command == "export":
        return _export(args)
    return _serve(args)


def _export(args: argparse.Namespace) -> int:
    flow = Path(args.flow)
    try:
        man = export.export_bundle(
            flow, Path(args.out), args.benchmark or flow.name, [Path(s) for s in args.src]
        )
    except export.ExportError as e:
        print(f"wyrd viz export: {e}", file=sys.stderr)
        return 2
    counts = ", ".join(f"{p} {n}" for p, n in man["counts"].items())
    print(
        f"wrote {args.out}: planes {counts}; {man['links']} links; {man['unanchored']} unanchored"
    )
    return 0


def _serve(args: argparse.Namespace) -> int:
    bundle = Path(args.bundle)
    if not (bundle / "manifest.json").is_file():
        print(f"wyrd viz serve: no manifest.json in {bundle}", file=sys.stderr)
        return 2
    srv = serve.make_server(bundle, args.port)
    print(f"serving {bundle.name} at http://127.0.0.1:{srv.server_address[1]}/  (Ctrl-C to stop)")
    with contextlib.suppress(KeyboardInterrupt):
        srv.serve_forever()
    return 0
