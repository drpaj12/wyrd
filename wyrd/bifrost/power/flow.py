"""The power flow of one design: synthesis, activity, FPGA and ASIC power, report."""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from wyrd.bifrost.power import actfile, blifnet, crosscheck, sim, sta
from wyrd.bifrost.power.sim import PowerError
from wyrd.bifrost.power.tools import PowerTools
from wyrd.bifrost.power.vcdact import NetAct, read_activity_file

# Memory cap for the heavy tools (VPR, ACE2, OpenROAD), e.g. "4G". When set, they run under
# ``systemd-run --user --scope`` with that cap and no swap, instead of ``tools/heavy-run``.
MEM_CAP: str | None = None

# The pass list of ``odin3-flow --prov`` (the flow the Heimdall pages are built from).
FLOW_PASSES = "proc; fsm; opt; flatten; tristate; opt -full; wreduce; hardmap; lower; abc --lut 6"
ACE_DEFAULTS = {"pi_static_prob": 0.5, "pi_switch_prob": 0.2, "seed": 1}  # ace2/ace.h, -s 1


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

    tb_data: list[Path] = field(default_factory=list)  # files the testbench reads ($readmemh)
    blif: Path | None = None  # run on this Odin III flow BLIF (its .names file beside it)
    activity: str | None = (
        None  # "odin3", "iverilog" or "ace2"; None: iverilog with a tb, else ace2
    )
    mem_cap: str | None = None  # MemoryMax of the heavy tools, e.g. "4G"
    odin_passes: str = FLOW_PASSES  # passes that rebuild the BLIF's netlist for sim_tb --vcd-all

    def prefix(self) -> str:
        return f"{self.tb_top}.{self.dut_inst}."

    def tbrun(self, sources: list[Path], strip: str, extra: list[str] | None = None) -> sim.TbRun:
        return sim.TbRun(
            sources,
            self.tb_top,
            self.dut_inst,
            self.tb_clock,
            strip,
            self.tb_data,
            self.defines,
            self.incdirs,
            self.pass_text,
            extra or [],
        )


def _capped(argv: list[str]) -> list[str]:
    if not MEM_CAP:
        return argv
    return ["systemd-run", "--user", "--scope", "-q", "-p", f"MemoryMax={MEM_CAP}",
            "-p", "MemorySwapMax=0", *argv]  # fmt: skip


def _odin(tools: PowerTools, job: Job, script: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    cmd = [str(tools.odin3), "--diag-paths", "resolved", "--top", job.top, "-p", script]
    res = sim.run(_capped(cmd), cwd)
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
    """The design's own testbench against the BLIF as Verilog: activity of every BLIF net.

    The latches start at x, then 0, then 1 (first pass wins): a netlist has lost the RTL
    ``initial`` values, so x can stay unresolved (X pessimism, as in the silicon gate_sim)."""
    inner = f"{job.top}_nl"
    last = sim.SimResult(False, "")
    for mode in ("x", "0", "1"):
        w = work / f"state_{mode}"
        w.mkdir(parents=True, exist_ok=True)
        nl = w / "netlist.v"
        text = blifnet.verilog_netlist(blif, inner, None if mode == "x" else mode)
        nl.write_text(text + blifnet.wrapper(blif, inner, job.top))
        last = sim.activity_run(job.tbrun([nl, *job.tb], job.prefix() + "u_nl."), w)
        last.start_state = mode
        if last.passed:
            return last
    return last


def rtl_activity(job: Job, work: Path) -> sim.SimResult:
    """iverilog on the RTL: activity of every net under the DUT instance (the cross-check side)."""
    return sim.activity_run(job.tbrun([*job.sources, *job.tb], job.prefix()), work)


_PORT = re.compile(r"^# (clock|input|output) (\S+) (\d+)")


def odin_replay_activity(tools: PowerTools, job: Job, work: Path) -> tuple[dict[str, NetAct], int]:
    """Odin III replay: the DUT port waveform of ``sim_tb --vcd``, sampled per clock edge and
    replayed with ``sim --vectors-in --vcd``. Top scope removed from names. One clock only."""
    work.mkdir(parents=True, exist_ok=True)
    for d in job.tb_data:
        shutil.copy(d, work / d.name)
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


def odin_sim_activity(tools: PowerTools, job: Job, work: Path) -> sim.SimResult:
    """Odin III ``sim_tb --vcd-all --vcd-names hash`` on the netlist the flow BLIF was written
    from: every BLIF net is in the waveform under its BLIF name (Odin III 1.5 and later), so
    the names join the flow BLIF exactly. ``job.odin_passes`` must be the flow's passes."""
    work.mkdir(parents=True, exist_ok=True)
    for d in job.tb_data:
        shutil.copy(d, work / d.name)
    techlib = tools.odin3.resolve().parents[2] / "lib/vtr.o3lib"
    tbs = " ".join(f'"{t}"' for t in job.tb)
    vcd, out = work / "all.vcd", work / "run.txt"
    script = (
        f"read_techlib {techlib}; {_read(job)}; {job.odin_passes}; sim_tb --top {job.tb_top} "
        f"--out {out} --vcd {vcd} --vcd-all --vcd-names hash {tbs}"
    )
    _odin(tools, job, script, work)
    text = out.read_text(errors="replace") if out.exists() else ""
    ok = job.pass_text in text and sim.PASS_BAD.search(text) is None
    res = sim.SimResult(ok, text)
    clk = f"{job.tb_top}.{job.tb_clock}"
    try:
        acts = read_activity_file(vcd, clk)
    finally:
        vcd.unlink(missing_ok=True)
    nested = f"{job.prefix()}{job.top}."
    strip = nested if any(k.startswith(nested) for k in acts) else job.prefix()
    if ok and clk in acts:
        res.cycles = acts[clk].toggles // 2
        res.acts = {k[len(strip) :]: v for k, v in acts.items() if k.startswith(strip)}
    return res


def _heavy(tools: PowerTools, argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    if MEM_CAP:
        return sim.run(_capped(argv), cwd)
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
    return vectorless_run(tools, blif, clock, out)[0]


def vectorless_run(
    tools: PowerTools, blif: Path, clock: str, out: Path
) -> tuple[actfile.FpgaPower, dict[str, tuple[float, float]]]:
    """ACE2 vectorless activity (primary inputs at ``ACE_DEFAULTS``), then VPR power on the ACE
    netlist (the VTR power flow). Also returns ACE2's (p1, activity) of every net."""
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
    power = vpr_power(tools, out / "circuit.blif", out / "ace.act", out / "vpr")
    return power, actfile.read_act(out / "ace.act")


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
            job.tbrun(srcs, job.prefix(), ["-DFUNCTIONAL", "-DUNIT_DELAY=#0"]), w
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


_OUT_PINS = ("Q", "X", "Y", "SUM", "HI", "LO", "Q_N", "COUT", "GCLK")
_CELL = re.compile(r"^\s*(sky130_fd_sc_hd__\w+)\s+(\\?\S+)\s*\((.*?)\);", re.S | re.M)


def instance_out_nets(final_v: str) -> dict[str, str]:
    """Instance name to the net on its first output pin, from the silicon flow's final.v."""
    out: dict[str, str] = {}
    for m in _CELL.finditer(final_v):
        pins = dict(re.findall(r"\.(\w+)\(\s*([^)]*?)\s*\)", m.group(3)))
        for o in _OUT_PINS:
            if pins.get(o):
                out[m.group(2).lstrip("\\")] = pins[o].lstrip("\\")
                break
    return out


def write_asic_csvs(
    work: Path,
    acts: dict[str, NetAct],
    instances: dict[str, tuple[float, float]],
    final_v: Path,
    prov_csv: Path,
) -> None:
    """``asic_nets.csv`` (net,p1,activity) and ``asic_inst.csv``
    (inst,dyn_w,static_w,out_net,file,line): the Heimdall III activity-overlay input."""
    with (work / "asic_nets.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["net", "p1", "activity"])
        for n, a in acts.items():
            w.writerow([n, f"{a.p1:.6f}", f"{a.activity:.6f}"])
    out_net = instance_out_nets(final_v.read_text()) if final_v.exists() else {}
    prov = read_prov_csv(prov_csv) if prov_csv.exists() else {}
    with (work / "asic_inst.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["inst", "dyn_w", "static_w", "out_net", "file", "line"])
        for inst, (dyn, stat) in instances.items():
            fl = prov.get(inst, ("", ""))
            w.writerow([inst, repr(dyn), repr(stat), out_net.get(inst, ""), fl[0], fl[1]])


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


def ace_activity(
    nets: list[str], found: dict[str, tuple[float, float]], clock: str
) -> dict[str, tuple[float, float]]:
    """ACE2's (p1, activity) of the netlist nets. ACE2 renames some rewritten nodes to
    ``new_<name>``; its internal gates (``n<k>``) have no counterpart in the Odin III netlist."""
    out: dict[str, tuple[float, float]] = {}
    for n in nets:
        hit = found.get(n) or found.get("new_" + n)
        if hit is not None and n != clock:
            out[n] = hit
    return out


SOURCE_LABEL = {"odin3": "odin3-sim", "iverilog": "iverilog-gate", "ace2": "ace2"}


def _testbench_activity(
    tools: PowerTools, job: Job, source: str, blif: blifnet.Blif
) -> sim.SimResult:
    if source == "odin3":
        return odin_sim_activity(tools, job, job.work / "odin")
    return gate_activity_fpga(job, blif, job.work / "gl")


def run_power(tools: PowerTools, job: Job, asic: bool = True) -> dict[str, Any]:
    """All steps for one design; writes ``power.json``, ``activity.csv`` and (with a silicon run)
    ``asic_nets.csv`` and ``asic_inst.csv`` in ``job.work``.

    The activity source is ``job.activity``: ``odin3`` (``sim_tb --vcd-all``), ``iverilog``
    (testbench on the BLIF as Verilog) or ``ace2`` (vectorless); the default is ``iverilog``
    with a testbench and ``ace2`` without."""
    global MEM_CAP
    MEM_CAP = job.mem_cap
    missing = tools.missing()
    if missing:
        raise PowerError("missing tools: " + ", ".join(missing))
    source = job.activity or ("iverilog" if job.tb else "ace2")
    if source not in SOURCE_LABEL:
        raise PowerError(f"unknown activity source {source!r}")
    if source != "ace2" and not job.tb:
        raise PowerError(f"activity source {source!r} needs a testbench")
    job.work.mkdir(parents=True, exist_ok=True)
    if job.blif is not None:
        blif_path = job.blif.resolve()
        names_path = Path(str(blif_path) + ".names")
    else:
        blif_path, names_path = synthesize(tools, job)
    blif = blifnet.read_blif(blif_path)
    prov = blifnet.parse_names(names_path.read_text()) if names_path.exists() else {}
    clock_net = blif.latches[0].clock if blif.latches else job.dut_clock
    (job.work / "fpga").mkdir(exist_ok=True)
    label = SOURCE_LABEL[source]
    vless_dir = job.work / "fpga/vectorless"
    result: dict[str, Any] = {
        "version": 1,
        "design": job.design,
        "blif": blif_path.name,
        "clock": job.tb_clock if source != "ace2" else clock_net,
        "activity": {"source": label},
        "targets": {},
    }
    if source == "ace2":
        vless, vless_act = vectorless_run(tools, blif_path, clock_net, vless_dir)
        act = ace_activity(blif.nets(), vless_act, clock_net)
        fpga = vless
        summ = len(act), len(act)
        result["tb_pass"] = None
        result["cycles"] = 0
        result["activity"] |= {
            "nets": len(blif.nets()) - 1,
            "matched": summ[1],
            "matched_fraction": summ[1] / max(len(blif.nets()) - 1, 1),
            "ace_defaults": ACE_DEFAULTS,
        }
    else:
        tb = _testbench_activity(tools, job, source, blif)
        if not tb.passed:
            raise PowerError(f"{source} testbench did not pass: " + tb.log[-300:])
        act, summary = actfile.build_act(blif.nets(), tb.acts, skip=[clock_net])
        act[clock_net] = (0.5, 2.0)  # VPR wants the clock: probability 0.5, 2 per cycle
        act_path = job.work / "fpga/tb.act"
        actfile.write_act(act_path, act)
        fpga = vpr_power(tools, blif_path, act_path, job.work / "fpga/tb")
        vless = vectorless_run(tools, blif_path, clock_net, vless_dir)[0]
        result["testbench"] = job.tb[0].name
        result["tb_pass"] = True
        result["cycles"] = tb.cycles
        result["start_state"] = tb.start_state
        result["activity"] |= {
            "nets": summary.nets,
            "matched": summary.matched,
            "matched_fraction": summary.matched_fraction,
            "default_activity": summary.default_activity,
        }
        if job.blif is None and source == "iverilog":
            result["crosscheck"] = _crosscheck(tools, job, blif, tb, blif_path)
    result["targets"]["fpga"] = {
        **asdict(fpga),
        "arch": tools.arch().name,
        "tech": "PTM_45nm",
        "method": "vpr --power",
        "freq_mhz": 1e-6 / fpga.critical_path_s if fpga.critical_path_s else 0.0,
        "energy_per_cycle_pj": fpga.total_w * fpga.critical_path_s * 1e12,
        "vectorless_total_w": vless.total_w,
        "vectorless_dynamic_w": vless.dynamic_w,
    }
    result["by_line"] = fpga_by_line(blif, act, prov, fpga.dynamic_w, fpga.clock_w)
    write_activity_csv(job.work / "activity.csv", act, prov, label)
    if asic and job.silicon is not None and job.tb:
        _add_asic(tools, job, result)
    (job.work / "power.json").write_text(json.dumps(result, indent=1) + "\n")
    return result


def _crosscheck(
    tools: PowerTools,
    job: Job,
    blif: blifnet.Blif,
    gl: sim.SimResult,
    blif_path: Path,
) -> dict[str, Any]:
    rtl = rtl_activity(job, job.work / "rtl")
    out: dict[str, Any] = {"rtl_passed": rtl.passed}
    try:
        odin, _ = odin_replay_activity(tools, job, job.work / "replay")
    except PowerError as e:
        out["odin_replay_error"] = str(e)[-300:]
        return out
    cc = crosscheck.compare(odin, rtl.acts)
    out["odin_vs_iverilog_rtl"] = asdict(cc) | {"identical_fraction": cc.identical_fraction}
    clock_net = blif.latches[0].clock if blif.latches else job.dut_clock
    act, summ = actfile.build_act(blif.nets(), odin, skip=[clock_net])
    act[clock_net] = (0.5, 2.0)
    path = job.work / "fpga/odin_replay.act"
    actfile.write_act(path, act)
    p = vpr_power(tools, blif_path, path, job.work / "fpga/odin_replay")
    out["fpga_odin_replay"] = {
        "matched": summ.matched,
        "nets": summ.nets,
        "matched_fraction": summ.matched_fraction,
        "total_w": p.total_w,
        "dynamic_w": p.dynamic_w,
        "clock_w": p.clock_w,
    }
    return out


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
        "freq_mhz": 1e3 / job.asic_period_ns,
        "energy_per_cycle_pj": p.total_w * job.asic_period_ns * 1e3,
        "switching_w": p.switching_w,
        "internal_w": p.internal_w,
        "activity_set": p.activity_set,
        "nets": p.nets,
        "matched_fraction": p.matched_fraction,
    }
    prov_csv = job.silicon / "prov.csv"
    if prov_csv.exists():
        result["by_line_asic"] = asic_by_line(p.instances, read_prov_csv(prov_csv))
    write_asic_csvs(job.work, g.acts, p.instances, job.silicon / "or/final.v", prov_csv)
