"""`wyrd tb run|convert`: Verilog testbenches through Odin III (Bifrost III, spec 2026-10-31)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wyrd.bifrost import TbReport, TbResult, TbSpec

ON_CHOICES = ("rtl", "netlist", "both")


def add_parser(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    tb = sub.add_parser("tb", help="run Verilog testbenches, convert vectors (needs wyrd[sim])")
    tsub = tb.add_subparsers(dest="tb_command", required=True)
    run = tsub.add_parser("run", help="run a project's testbenches or one testbench file")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--project", metavar="FILE.o3proj")
    source.add_argument("--tb", metavar="FILE")
    run.add_argument("--only", metavar="NAME", help="with --project: one testbench")
    run.add_argument("--dut", nargs="+", metavar="FILE", help="with --tb: the DUT Verilog files")
    run.add_argument("--dut-top", metavar="MODULE")
    run.add_argument("--tb-top", metavar="MODULE")
    run.add_argument("--dut-inst", metavar="NAME", help="check the testbench instantiates this")
    run.add_argument("--max-time", type=int, metavar="T")
    run.add_argument("--expect", metavar="FILE", help="golden $display text")
    run.add_argument("--on", choices=ON_CHOICES, default="rtl")
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--json", metavar="OUT", help="write the results as JSON")
    run.add_argument("--out", metavar="TEXT", help="with --tb: write the $display text")
    run.add_argument("--vcd", metavar="OUT", help="with --tb: write a VCD (Wyrd-format output)")
    conv = tsub.add_parser("convert", help="vector file <-> testbench")
    conv.add_argument("--to", choices=["tb", "vectors"], required=True)
    conv.add_argument("--dut", nargs="+", required=True, metavar="FILE")
    conv.add_argument("--dut-top", metavar="MODULE")
    conv.add_argument("--vectors", metavar="FILE", help="--to tb: the vector file to read")
    conv.add_argument("--tb", metavar="FILE", help="--to vectors: the testbench to run")
    conv.add_argument("--out", required=True, metavar="FILE")


def _err(msg: str) -> int:
    print(f"wyrd: {msg}", file=sys.stderr)
    return 2


def _line(r: TbResult) -> list[str]:
    lines = [f"{r.name} {r.status} {r.on} {r.wall_ms} ms"]
    if r.mismatch is not None:
        m = r.mismatch
        when = "" if m.time is None else f" time {m.time}"
        head = f"  mismatch: {m.compared} line {m.line}{when} field {m.field}"
        lines.append(f'{head}: want "{m.want}" got "{m.got}"')
    elif r.error is not None:
        lines.append(f"  {r.status}: {r.error}")
    return lines


def _print_report(rep: TbReport) -> None:
    for r in rep.results:
        print("\n".join(_line(r)))
    print(
        f"tb run: {rep.count('pass')} passed, {rep.count('fail')} failed, "
        f"{rep.count('error')} errors, {rep.count('timeout')} timeouts"
    )


def _spec(args: argparse.Namespace) -> TbSpec:
    from wyrd.bifrost import TbSpec

    if not args.dut:
        raise ValueError("--tb needs --dut FILE...")
    return TbSpec(
        Path(args.tb),
        [Path(f) for f in args.dut],
        dut_top=args.dut_top,
        tb_top=args.tb_top,
        dut_inst=args.dut_inst,
        max_time=args.max_time,
        expect=None if args.expect is None else Path(args.expect),
        on=args.on,
        name=Path(args.tb).stem,
    )


def _write_extras(args: argparse.Namespace, spec: TbSpec, r: TbResult) -> None:
    if args.out and r.output is not None:
        Path(args.out).write_text(r.output, encoding="utf-8")
    if args.vcd:
        from wyrd.bifrost import testbench_file_to_vcd

        if r.output is None:
            raise ValueError("no testbench output to build a VCD from")
        testbench_file_to_vcd(spec.dut, r.output, Path(args.vcd), top=spec.dut_top)


def _run(args: argparse.Namespace) -> int:
    from wyrd.bifrost import TbReport, run_project_testbenches, run_testbench_file

    if args.project:
        rep = run_project_testbenches(args.project, only=args.only, seed=args.seed)
    else:
        spec = _spec(args)
        result = run_testbench_file(spec, seed=args.seed)
        rep = TbReport((result,))
        _write_extras(args, spec, result)
    _print_report(rep)
    if args.json:
        Path(args.json).write_text(rep.to_json(), encoding="utf-8")
    return 0 if rep.ok else 1


def _convert(args: argparse.Namespace) -> int:
    from wyrd.bifrost import testbench_file_to_vectors, vectors_file_to_testbench

    dut = [Path(f) for f in args.dut]
    if args.to == "tb":
        if not args.vectors:
            raise ValueError("--to tb needs --vectors FILE")
        n = vectors_file_to_testbench(dut, Path(args.vectors), Path(args.out), top=args.dut_top)
    else:
        if not args.tb:
            raise ValueError("--to vectors needs --tb FILE")
        n = testbench_file_to_vectors(dut, Path(args.tb), Path(args.out), top=args.dut_top)
    print(f"wrote {args.out}: {n} cycles")
    return 0


def main(args: argparse.Namespace) -> int:
    from wyrd.bifrost import CompileError, SimError

    try:
        return _run(args) if args.tb_command == "run" else _convert(args)
    except CompileError as e:
        for d in e.diagnostics or ():
            print(f"{d.severity}: {d.message}", file=sys.stderr)
        return _err(str(e))
    except (SimError, ValueError, OSError) as e:
        return _err(str(e))
