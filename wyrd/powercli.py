"""`wyrd power run`: FPGA and ASIC power from a design's testbench activity (spec 2026-11-06)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("power", help="power estimate from testbench switching activity")
    psub = p.add_subparsers(dest="power_command", required=True)
    run = psub.add_parser("run", help="run one design; writes power.json and activity.csv")
    run.add_argument("--design", required=True)
    run.add_argument("--src", nargs="+", required=True, metavar="FILE", help="DUT Verilog files")
    run.add_argument("--top", required=True, help="DUT top module")
    run.add_argument("--tb", nargs="+", required=True, metavar="FILE")
    run.add_argument("--tb-top", required=True)
    run.add_argument("--tb-clock", default="clk", help="testbench clock net (default clk)")
    run.add_argument("--dut-inst", default="dut", help="DUT instance name in the testbench")
    run.add_argument("--dut-clock", default="sys_clk", help="DUT clock port name")
    run.add_argument(
        "--tb-data", nargs="*", default=[], metavar="FILE", help="files $readmemh reads"
    )
    run.add_argument(
        "--silicon", metavar="DIR", help="silicon flow output (or/final.odb, or/final.v)"
    )
    run.add_argument("--period-ns", type=float, default=10.0)
    run.add_argument("--out", required=True, metavar="DIR")


def main(args: argparse.Namespace) -> int:
    from wyrd.bifrost.power.flow import Job, run_power
    from wyrd.bifrost.power.sim import PowerError
    from wyrd.bifrost.power.tools import discover

    job = Job(
        design=args.design,
        sources=[Path(f).resolve() for f in args.src],
        top=args.top,
        tb=[Path(f).resolve() for f in args.tb],
        tb_top=args.tb_top,
        work=Path(args.out).resolve(),
        tb_clock=args.tb_clock,
        dut_inst=args.dut_inst,
        dut_clock=args.dut_clock,
        tb_data=[Path(f).resolve() for f in args.tb_data],
        silicon=Path(args.silicon).resolve() if args.silicon else None,
        asic_period_ns=args.period_ns,
    )
    try:
        result = run_power(discover(), job)
    except PowerError as e:
        print(f"wyrd power: {e}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if not k.startswith("by_line")}, indent=1))
    return 0
