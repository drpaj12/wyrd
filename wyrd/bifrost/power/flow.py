"""The power flow of one design: synthesis, activity, FPGA and ASIC power, report."""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from wyrd.bifrost.power import actfile, blifnet, crosscheck, sim, sta
from wyrd.bifrost.power.sim import PowerError
from wyrd.bifrost.power.tools import PowerTools
from wyrd.bifrost.power.vcdact import NetAct, read_activity_file


@dataclass
class Job:
    design: str
    sources: list[Path]
    top: str
    tb: list[Path]
    tb_top: str
    work: Path
    tb_clock: str = "clk"
    dut_inst: str = "dut"
    dut_clock: str = "sys_clk"
    defines: list[str] = field(default_factory=list)
    incdirs: list[Path] = field(default_factory=list)
    silicon: Path | None = None  # a silicon flow output directory (or/final.odb, or/final.v)
    asic_period_ns: float = 10.0
    pass_text: str = "PASS"

    def prefix(self) -> str:
        return f"{self.tb_top}.{self.dut_inst}."


def _odin(tools: PowerTools, job: Job, script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    cmd = [str(tools.odin3), "--diag-paths", "resolved", "--top", job.top, "-p", script]
    res = sim.run(cmd, cwd)
    if res.returncode != 0:
        raise PowerError(f"odin3 failed: {(res.stdout + res.stderr)[-400:]}")
    return res


def _read(job: Job) -> str:
    files = " ".join(f'"{s}"' for s in job.sources)
    return f"read_verilog --nolatches --vtr-compat --prov-ast refs {files}"


def synthesize(tools: PowerTools, job: Job) -> tuple[Path, Path]:
    """LUT BLIF with hash names and the names file; adders stay soft (spec section 1)."""
    out = job.work / "synth"
    out.mkdir(parents=True, exist_ok=True)
    blif = out / f"{job.top}.blif"
    script = (
        f"{_read(job)}; proc; fsm; opt; flatten; tristate; opt -full; wreduce; lower; "
        f'abc --lut 6; write_blif --vtr --lut-k 6 --name-style hash --prov-map "{blif}"'
    )
    _odin(tools, job, script, out)
    return blif, Path(str(blif) + ".names")


def gate_activity_fpga(job: Job, blif: blifnet.Blif, work: Path) -> sim.SimResult:
    """The design's own testbench against the BLIF as Verilog: activity of every BLIF net."""
    work.mkdir(parents=True, exist_ok=True)
    nl = work / "netlist.v"
    inner = f"{job.top}_nl"
    nl.write_text(blifnet.verilog_netlist(blif, inner) + blifnet.wrapper(blif, inner, job.top))
    return sim.activity_run(
        [nl, *job.tb],
        job.tb_top,
        job.tb_clock,
        job.prefix() + "u_nl.",
        work,
        defines=job.defines,
        incdirs=job.incdirs,
        pass_text=job.pass_text,
    )


def rtl_activity(job: Job, work: Path) -> sim.SimResult:
    """iverilog on the RTL: activity of every net under the DUT instance (the cross-check side)."""
    return sim.activity_run(
        [*job.sources, *job.tb],
        job.tb_top,
        job.tb_clock,
        job.prefix(),
        work,
        defines=job.defines,
        incdirs=job.incdirs,
        pass_text=job.pass_text,
    )


_PORT = re.compile(r"^# (clock|input|output) (\S+) (\d+)")


def odin_replay_activity(tools: PowerTools, job: Job, work: Path) -> tuple[dict[str, NetAct], int]:
    """Odin III replay: the DUT port waveform of ``sim_tb --vcd``, sampled per clock edge and
    replayed with ``sim --vectors-in --vcd``. Top scope removed from names. One clock only."""
    work.mkdir(parents=True, exist_ok=True)
    tbs = " ".join(f'"{t}"' for t in job.tb)
    base = f"{_read(job)}; proc; opt; lower"
    tbv, hdr = work / "tb.vcd", work / "hdr.vec"
    _odin(
        tools,
        job,
        f"{base}; sim_tb --top {job.tb_top} --out {work / 'run.txt'} --vcd {tbv} {tbs}",
        work,
    )
    _odin(tools, job, f"{base}; sim 1 1 {hdr}", work)
    ports = [
        (m.group(2), int(m.group(3)))
        for ln in hdr.read_text().splitlines()
        if (m := _PORT.match(ln)) and m.group(1) == "input"
    ]
    clock = [
        m.group(2)
        for ln in hdr.read_text().splitlines()
        if (m := _PORT.match(ln)) and m.group(1) == "clock"
    ]
    if len(clock) != 1:
        raise PowerError(f"odin replay needs exactly one clock port, found {clock}")
    rows = sim.vectors_from_tb_vcd(tbv, job.tb_top, job.dut_inst, clock[0], ports)
    vec = work / "replay.vec"
    head = [ln for ln in hdr.read_text().splitlines() if _PORT.match(ln)]
    body = [
        f"{i} " + "".join(f"{r[job.prefix() + n]:0{w}b}" for n, w in ports)
        for i, r in enumerate(rows)
    ]
    vec.write_text("\n".join(head + body) + "\n")
    rv = work / "replay.vcd"
    _odin(tools, job, f"{base}; sim --vectors-in {vec} --vcd {rv}", work)
    acts = read_activity_file(rv, f"{job.top}.{clock[0]}")
    return {k[len(job.top) + 1 :]: v for k, v in acts.items()}, len(rows)


def _heavy(tools: PowerTools, argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, ODIN3_HEAVY_OK="1")
    cmd = ([str(tools.heavy_run)] if tools.heavy_run else []) + argv
    return sim.run(cmd, cwd, env)


def vpr_power(tools: PowerTools, blif: Path, act: Path | None, out: Path) -> actfile.FpgaPower:
    """VPR with ``--power`` on ``blif`` (``act`` is its activity file) at a fixed channel width."""
    out.mkdir(parents=True, exist_ok=True)
    local = out / "circuit.blif"
    local.write_bytes(blif.read_bytes())
    argv = [
        str(tools.vpr()),
        str(tools.arch()),
        "circuit.blif",
        "--route_chan_width",
        "100",
        "--power",
        "--tech_properties",
        str(tools.tech()),
    ]
    if act is not None:
        argv += ["--activity_file", str(act)]
    res = _heavy(tools, argv, out)
    (out / "vpr.log").write_text(res.stdout + res.stderr)
    power = sorted(out.glob("*.power"))
    if res.returncode != 0 or not power:
        raise PowerError(f"vpr failed (see {out / 'vpr.log'})")
    return actfile.parse_power(power[0].read_text())


def vectorless_power(tools: PowerTools, blif: Path, clock: str, out: Path) -> actfile.FpgaPower:
    """ACE2 vectorless activity, then VPR power on the ACE netlist (the VTR power flow)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "in.blif").write_bytes(blif.read_bytes())
    ace = _heavy(
        tools,
        [
            str(tools.ace()),
            "-b",
            "in.blif",
            "-c",
            clock,
            "-n",
            "raw.ace.blif",
            "-o",
            "ace.act",
            "-s",
            "1",
        ],
        out,
    )
    if ace.returncode != 0:
        raise PowerError(f"ace failed: {(ace.stdout + ace.stderr)[-300:]}")
    fix = sim.run([str(tools.restore_latch()), "in.blif", "raw.ace.blif", "circuit.blif"], out)
    if fix.returncode != 0:
        raise PowerError(f"restore_multiclock_latch failed: {fix.stderr[-300:]}")
    return vpr_power(tools, out / "circuit.blif", out / "ace.act", out / "vpr")


def fanouts(blif: blifnet.Blif) -> dict[str, int]:
    count: dict[str, int] = defaultdict(int)
    for n in blif.names:
        for i in n.inputs:
            count[i] += 1
    for lt in blif.latches:
        count[lt.d] += 1
    return dict(count)


def fpga_by_line(
    blif: blifnet.Blif,
    act: dict[str, tuple[float, float]],
    prov: dict[str, blifnet.Provenance],
    dynamic_w: float,
    clock_w: float,
) -> list[dict[str, Any]]:
    """Dynamic power split over nets by activity x (fanout + 1), summed per HDL line (a model)."""
    fo = fanouts(blif)
    weight = {n: a * (fo.get(n, 0) + 1) for n, (_, a) in act.items()}
    total = sum(weight.values()) or 1.0
    share = max(dynamic_w - clock_w, 0.0)
    lines: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for n, w in weight.items():
        p = prov.get(n)
        key = (Path(p.file).name, p.line) if p else ("<port-or-unmapped>", 0)
        lines[key][0] += share * w / total
        lines[key][1] += 1
    return [
        {"file": k[0], "line": k[1], "fpga_dyn_w": v[0], "nets": int(v[1])}
        for k, v in sorted(lines.items(), key=lambda kv: -kv[1][0])
    ]


def read_prov_csv(path: Path) -> dict[str, tuple[str, int]]:
    """Silicon flow prov.csv: instance to the first (file, line) of its source chain."""
    out: dict[str, tuple[str, int]] = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            first = (row.get("src_chain") or "").split("|")[0]
            m = re.match(r"(.+?):(\d+)", first)
            if m:
                out[row["inst"]] = (Path(m.group(1)).name, int(m.group(2)))
    return out


def asic_by_line(
    instances: dict[str, tuple[float, float]], prov: dict[str, tuple[str, int]]
) -> list[dict[str, Any]]:
    lines: dict[tuple[str, int], list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
    for inst, (dyn, stat) in instances.items():
        key = prov.get(inst, ("<physical>", 0))
        lines[key][0] += dyn
        lines[key][1] += stat
        lines[key][2] += 1
    return [
        {"file": k[0], "line": k[1], "asic_dyn_w": v[0], "asic_static_w": v[1], "cells": int(v[2])}
        for k, v in sorted(lines.items(), key=lambda kv: -kv[1][0])
    ]


def asic_gate_activity(tools: PowerTools, job: Job, work: Path) -> sim.SimResult:
    """The testbench against the silicon flow's final.v and the sky130 models. The flip-flop start
    state is x, then 0, then 1 (first pass wins), as the silicon flow's gate_sim does."""
    assert job.silicon is not None
    models = tools.verilog_models()
    if models is None:
        raise PowerError("sky130 verilog models not found")
    prim = (models / "primitives.v").read_text()
    last = sim.SimResult(False, "")
    for mode in ("x", "0", "1"):
        w = work / f"asic_{mode}"
        w.mkdir(parents=True, exist_ok=True)
        pv = models / "primitives.v"
        if mode != "x":
            pv = w / "primitives.v"
            pv.write_text(sim.patch_primitives(prim, mode))
        srcs = [job.silicon / "or/final.v", pv, models / "sky130_fd_sc_hd.v", *job.tb]
        last = sim.activity_run(
            srcs,
            job.tb_top,
            job.tb_clock,
            job.prefix(),
            w,
            defines=job.defines,
            incdirs=job.incdirs,
            pass_text=job.pass_text,
            extra=["-DFUNCTIONAL", "-DUNIT_DELAY=#0"],
        )
        last.start_state = mode
        if last.passed:
            return last
    return last


def asic_power(
    tools: PowerTools, job: Job, acts: dict[str, NetAct], clock_port: str, work: Path
) -> sta.AsicPower:
    assert job.silicon is not None and tools.openroad and tools.liberty()
    work.mkdir(parents=True, exist_ok=True)
    table = work / "acts.txt"
    sta.write_activity_table(table, acts, {clock_port})
    lib = tools.liberty()
    assert lib is not None
    script = work / "power.tcl"
    script.write_text(
        sta.sta_script(lib, job.silicon / "or/final.odb", clock_port, job.asic_period_ns, table)
    )
    res = _heavy(tools, [str(tools.openroad), "-no_splash", "-exit", str(script)], work)
    (work / "openroad.log").write_text(res.stdout + res.stderr)
    if res.returncode != 0 or "INST_BEGIN" not in res.stdout:
        raise PowerError(f"openroad power failed (see {work / 'openroad.log'})")
    return sta.parse_sta_power(res.stdout)


def write_activity_csv(
    path: Path,
    act: dict[str, tuple[float, float]],
    prov: dict[str, blifnet.Provenance],
    source: str,
) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["net", "name", "file", "line", "p1", "activity", "source"])
        for n, (p, a) in act.items():
            pr = prov.get(n)
            w.writerow(
                [
                    n,
                    pr.name if pr else n,
                    Path(pr.file).name if pr else "",
                    pr.line if pr else "",
                    f"{p:.6f}",
                    f"{a:.6f}",
                    source,
                ]
            )


def run_power(tools: PowerTools, job: Job, asic: bool = True) -> dict[str, Any]:
    """All steps for one design; writes ``power.json`` and ``activity.csv`` in ``job.work``."""
    missing = tools.missing()
    if missing:
        raise PowerError("missing tools: " + ", ".join(missing))
    job.work.mkdir(parents=True, exist_ok=True)
    blif_path, names_path = synthesize(tools, job)
    blif, prov = blifnet.read_blif(blif_path), blifnet.parse_names(names_path.read_text())
    gl = gate_activity_fpga(job, blif, job.work / "gl")
    if not gl.passed:
        raise PowerError("gate-level testbench did not pass: " + gl.log[-300:])
    clock_net = blif.latches[0].clock if blif.latches else job.dut_clock
    act, summary = actfile.build_act(blif.nets(), gl.acts, skip=[clock_net])
    act[clock_net] = (0.5, 2.0)  # VPR wants the clock in the file: probability 0.5, 2 per cycle
    (job.work / "fpga").mkdir(exist_ok=True)
    act_path = job.work / "fpga/tb.act"
    actfile.write_act(act_path, act)
    fpga = vpr_power(tools, blif_path, act_path, job.work / "fpga/tb")
    vless = vectorless_power(tools, blif_path, clock_net, job.work / "fpga/vectorless")
    result: dict[str, Any] = {
        "version": 1,
        "design": job.design,
        "testbench": job.tb[0].name,
        "tb_pass": True,
        "clock": job.tb_clock,
        "cycles": gl.cycles,
        "start_state": gl.start_state,
        "activity": {
            "source": "iverilog-gate",
            "nets": summary.nets,
            "matched": summary.matched,
            "matched_fraction": summary.matched_fraction,
            "default_activity": summary.default_activity,
        },
        "targets": {
            "fpga": {
                **asdict(fpga),
                "arch": tools.arch().name,
                "tech": "PTM_45nm",
                "method": "vpr --power",
                "vectorless_total_w": vless.total_w,
                "vectorless_dynamic_w": vless.dynamic_w,
            }
        },
        "crosscheck": _crosscheck(tools, job, blif, gl, act_path, names_path, fpga),
    }
    result["by_line"] = fpga_by_line(blif, act, prov, fpga.dynamic_w, fpga.clock_w)
    write_activity_csv(job.work / "activity.csv", act, prov, "iverilog-gate")
    if asic and job.silicon is not None:
        _add_asic(tools, job, result)
    (job.work / "power.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def _crosscheck(
    tools: PowerTools,
    job: Job,
    blif: blifnet.Blif,
    gl: sim.SimResult,
    act_path: Path,
    names_path: Path,
    fpga: actfile.FpgaPower,
) -> dict[str, Any]:
    rtl = rtl_activity(job, job.work / "rtl")
    odin, _ = odin_replay_activity(tools, job, job.work / "replay")
    cc = crosscheck.compare(odin, rtl.acts)
    names = set(blif.nets())
    mapped = {n: a for n, a in odin.items() if n in names}
    return {
        "odin_vs_iverilog_rtl": asdict(cc) | {"identical_fraction": cc.identical_fraction},
        "rtl_passed": rtl.passed,
        "odin_replay_nets_in_blif": len(mapped),
        "odin_replay_matched_fraction": len(mapped) / max(len(names), 1),
    }


def _add_asic(tools: PowerTools, job: Job, result: dict[str, Any]) -> None:
    assert job.silicon is not None
    g = asic_gate_activity(tools, job, job.work / "asic")
    if not g.passed:
        result["targets"]["asic"] = {
            "error": "gate-level testbench did not pass",
            "log": g.log[-300:],
        }
        return
    p = asic_power(tools, job, g.acts, job.dut_clock, job.work / "asic/sta")
    result["targets"]["asic"] = {
        "pdk": "sky130_fd_sc_hd tt_025C_1v80",
        "parasitics": "placement",
        "start_state": g.start_state,
        "total_w": p.total_w,
        "dynamic_w": p.dynamic_w,
        "static_w": p.leakage_w,
        "clock_w": p.clock_w,
        "switching_w": p.switching_w,
        "internal_w": p.internal_w,
        "activity_set": p.activity_set,
        "nets": p.nets,
        "matched_fraction": p.matched_fraction,
    }
    prov_csv = job.silicon / "prov.csv"
    if prov_csv.exists():
        result["by_line_asic"] = asic_by_line(p.instances, read_prov_csv(prov_csv))
