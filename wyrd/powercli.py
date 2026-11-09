"""`wyrd power run`: FPGA and ASIC power from a design's testbench activity (spec 2026-11-06)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    p = sub.add_parser("power", help="power estimate from testbench switching activity")
    psub = p.add_subparsers(dest="power_command", required=True)
    run = psub.add_parser(
        "run", help="run one design; writes power.json, activity.csv, asic_nets.csv, asic_inst.csv"
    )
    run.add_argument("--design", required=True)
    run.add_argument(
        "--src",
        nargs="*",
        default=[],
        metavar="FILE",
        help="DUT Verilog files (needed to synthesise, and for --activity odin3)",
    )
    run.add_argument("--top", required=True, help="DUT top module")
    run.add_argument(
        "--tb", nargs="*", default=[], metavar="FILE", help="testbench (none: ACE2 vectorless)"
    )
    run.add_argument("--tb-top", default="", help="testbench top module (with --tb)")
    run.add_argument(
        "--blif",
        metavar="FILE",
        help="run on this Odin III flow BLIF (hash names; FILE.names beside it) instead of "
        "synthesising, so the net names join the BLIF a Heimdall page was built from",
    )
    run.add_argument(
        "--activity",
        choices=["odin3", "iverilog", "ace2"],
        help="activity source: odin3 = sim_tb --vcd-all (Odin III 1.5+), iverilog = testbench "
        "on the BLIF as Verilog, ace2 = vectorless (primary inputs p=0.5, activity 0.2); "
        "default iverilog with --tb, else ace2",
    )
    run.add_argument(
        "--odin-passes",
        metavar="PASSES",
        help="passes that rebuild the BLIF netlist for --activity odin3 (default: odin3-flow's)",
    )
    run.add_argument(
        "--mem-cap",
        metavar="SIZE",
        help="run VPR, ACE2, OpenROAD and Odin III under systemd-run MemoryMax=SIZE, no swap "
        "(instead of heavy-run)",
    )
    run.add_argument("--tb-clock", default="clk", help="testbench clock net (default clk)")
    run.add_argument("--dut-inst", default="dut", help="DUT instance name in the testbench")
    run.add_argument("--dut-clock", default="sys_clk", help="DUT clock port name")
    run.add_argument(
        "--tb-data", nargs="*", default=[], metavar="FILE", help="files $readmemh reads"
    )
    run.add_argument(
        "--silicon", metavar="DIR", help="silicon flow output (or/final.odb, or/final.v)"
    )
    run.add_argument("--incdir", nargs="*", default=[], metavar="DIR", help="`include directories")
    run.add_argument("--define", nargs="*", default=[], metavar="NAME[=V]")
    run.add_argument("--period-ns", type=float, default=10.0)
    run.add_argument("--out", required=True, metavar="DIR")


def main(args: argparse.Namespace) -> int:
    from wyrd.bifrost.power.flow import FLOW_PASSES, Job, run_power
    from wyrd.bifrost.power.sim import PowerError
    from wyrd.bifrost.power.tools import discover

    job = Job(
        design=args.design,
        sources=[Path(f).resolve() for f in args.src],
        top=args.top,
        tb=[Path(f).resolve() for f in args.tb],
        tb_top=args.tb_top,
        blif=Path(args.blif).resolve() if args.blif else None,
        activity=args.activity,
        mem_cap=args.mem_cap,
        odin_passes=args.odin_passes or FLOW_PASSES,
        work=Path(args.out).resolve(),
        tb_clock=args.tb_clock,
        dut_inst=args.dut_inst,
        dut_clock=args.dut_clock,
        tb_data=[Path(f).resolve() for f in args.tb_data],
        silicon=Path(args.silicon).resolve() if args.silicon else None,
        asic_period_ns=args.period_ns,
        incdirs=[Path(d).resolve() for d in args.incdir],
        defines=list(args.define),
    )
    if not args.blif and not args.src:
        print("wyrd power: give --blif or --src", file=sys.stderr)
        return 2
    if args.tb and not args.tb_top:
        print("wyrd power: --tb needs --tb-top", file=sys.stderr)
        return 2
    try:
        result = run_power(discover(), job)
    except PowerError as e:
        print(f"wyrd power: {e}", file=sys.stderr)
        return 2
    print(json.dumps({k: v for k, v in result.items() if not k.startswith("by_line")}, indent=1))
    return 0
