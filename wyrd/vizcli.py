"""`wyrd viz ...`: forwards to Heimdall III (heimdallIII on GitHub) when it is installed."""

from __future__ import annotations

import argparse
import importlib
import sys

INSTALL = (
    "Heimdall III is not installed. The 3D provenance viewer moved there from Wyrd.\n"
    "Install it with:  pip install 'wyrd[viz]'   or   "
    "pip install git+https://github.com/drpaj12/heimdallIII.git\n"
    "Then run `heimdall export|serve|site` directly, or `wyrd viz ...` as before."
)


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    viz = sub.add_parser("viz", help="3D provenance viewer (Heimdall III, optional extra `viz`)")
    viz.add_argument("rest", nargs=argparse.REMAINDER, help="arguments for `heimdall`")


def main(args: argparse.Namespace) -> int:
    try:
        heimdall_cli = importlib.import_module("heimdall.cli")
    except ImportError:
        print(INSTALL, file=sys.stderr)
        return 2
    code: int = heimdall_cli.main(list(args.rest))
    return code
