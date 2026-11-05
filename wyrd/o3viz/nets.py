"""Re-run the Odin III script of a flow with extra dumps (pre-mapping netlist, wire names).

The flow's own run keeps no wire names for the nets ABC rebuilds (flip-flop outputs and LUT outputs
are `$nN`). A second run of the same script, with two `write_json` dumps added, gives (1) the
netlist right after `proc` (word cells with their HDL spans and, in a second dump, their
provenance records) and (2) the netlist right before the BLIF write (wire names of the surviving
nets, flip-flop cells named after their register). Wyrd uses Odin III only as a program here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class NetsError(Exception):
    pass


@dataclass
class Dumps:
    """Parsed outputs of the extra run (the top module only)."""

    top: str
    proc: dict[str, Any]  # write_json, provenance names, after proc
    proc_names: dict[str, tuple[str, str]]  # provenance cell key -> (hash, record id)
    gates: dict[str, Any]  # write_json, provenance names, before write_blif
    scoap: dict[int, tuple[int, int, int]] | None  # net id -> (cc0, cc1, co); None: no scoap pass
    records: dict[str, list[str]]  # final name map: record id -> parent records
    lut_rec: dict[str, str]  # final name map: hash net name -> record id
    net_full: dict[str, str]  # final name map: hash net name -> full net name
    scoap_nets: list[dict[str, Any]] = field(
        default_factory=list
    )  # raw scoap rows (--prov: driver, wire, prov, src)
    graphs: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )  # write_graph kind -> parsed file


def command_of(log: Path) -> tuple[list[str], str]:
    """The odin3 argv (before -p) and the script text from the `$ ` line of a flow log."""
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("$ ") and " -p " in line:
            head, script = line[2:].split(" -p ", 1)
            return head.split(), script
    raise NetsError(f"no odin3 command line in {log}")


GRAPH_KINDS = ("cfg", "stg", "ddg")
# what to ask of the Odin III build, richest first; a build without a pass fails, the next is tried
ATTEMPTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("cfg", "stg", "ddg"), "prov"),
    (("cfg", "stg", "ddg"), "plain"),
    (("cfg", "stg"), "plain"),
    (("cfg", "stg"), "none"),
    ((), "plain"),
    ((), "none"),
)


def extended_script(
    script: str, work: Path, graphs: tuple[str, ...] = (), scoap: str = "plain"
) -> str:
    """The script with the dumps added and the BLIF written under `work`.

    `graphs`: write_graph kinds (cfg runs just before proc, stg and ddg just after). `scoap`:
    "none", "plain" (net id, CC0, CC1, CO) or "prov" (also driver, wire, prov, src per net); the
    pass runs on the netlist the second dump shows (after mapping) and writes `work`/scoap.json.
    """
    if "; proc;" not in script and not script.startswith("proc;"):
        raise NetsError("the odin3 script has no proc step")
    dump1 = (
        f"write_json --odin3 --name-style provenance {work}/proc.json; "
        f"write_json --odin3 --name-style hash --prov-map {work}/proc_h.json; "
    )
    pre = f"write_graph cfg {work}/cfg.json; " if "cfg" in graphs else ""
    post = "".join(f"write_graph {k} {work}/{k}.json; " for k in ("stg", "ddg") if k in graphs)
    out = script.replace("proc; ", pre + "proc; " + dump1 + post, 1)
    m = list(re.finditer(r"write_blif ", out))
    if not m:
        raise NetsError("the odin3 script has no write_blif")
    at = m[-1].start()
    tail = re.sub(r'"[^"]*\.blif"', f'"{work}/rt.blif"', out[at:])
    flag = " --prov" if scoap == "prov" else ""
    sc = f"scoap{flag} --out {work}/scoap.json; " if scoap != "none" else ""
    if (
        sc and "ddg" in graphs
    ):  # the DDG of the mapped netlist: the one the scoap wire IDs belong to
        sc = f"write_graph ddg {work}/ddgm.json; " + sc
    return out[:at] + sc + f"write_json --odin3 --name-style provenance {work}/gates.json; " + tail


def source_cwd(script: str, candidates: list[Path]) -> Path:
    files = re.findall(r'"([^"]+\.s?vh?)"', script)
    for d in candidates:
        if all((d / f).is_file() or Path(f).is_absolute() for f in files):
            return d
    raise NetsError(f"cannot find the HDL files {files} in {[str(c) for c in candidates]}")


def run_dumps(flow: Path, work: Path, search: list[Path], odin3: Path | None = None) -> Path:
    """Run the extended script; return `work`. `odin3` replaces the program of the flow's own
    command line. If the run fails the next-poorer set of extras is tried (an Odin III build without
    `write_graph ddg` or `scoap --prov` still gives the other dumps)."""
    argv, script = command_of(flow / "odin3" / "odin3.log")
    if odin3 is not None:
        argv[0] = str(odin3)
    cwd = source_cwd(script, [*search, flow.parent])
    r: subprocess.CompletedProcess[str] | None = None
    for graphs, scoap in ATTEMPTS:
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        new = extended_script(script, work, graphs, scoap)
        r = subprocess.run(
            [*argv, "-p", new], cwd=cwd, capture_output=True, text=True, check=False, timeout=600
        )
        if r.returncode == 0:
            return work
        if not any(w in r.stderr for w in ("scoap", "write_graph", "usage", "unknown")):
            break
    assert r is not None
    raise NetsError(f"odin3 dump run failed ({r.returncode}): {r.stderr[-400:]}")


def read_scoap(path: Path, top: str) -> dict[int, tuple[int, int, int]] | None:
    """Net id -> (CC0, CC1, CO) of the top module from the scoap pass JSON (INF is 10^18)."""
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    for mod in doc.get("modules", []):
        if mod.get("name") == top:
            return {n["id"]: (n["cc0"], n["cc1"], n["co"]) for n in mod["nets"]}
    return None


def read_scoap_rows(path: Path, top: str) -> list[dict[str, Any]]:
    """The raw net rows of the top module (with `--prov`: driver, wire, prov, src)."""
    if not path.is_file():
        return []
    for mod in json.loads(path.read_text(encoding="utf-8")).get("modules", []):
        if mod.get("name") == top:
            return [dict(n) for n in mod["nets"]]
    return []


def read_graphs(work: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for kind in (*GRAPH_KINDS, "ddgm"):
        p = work / f"{kind}.json"
        if p.is_file():
            out[kind] = json.loads(p.read_text(encoding="utf-8"))
    return out


def read_map(path: Path) -> tuple[dict[str, list[str]], dict[str, str], dict[str, str]]:
    """Version 2 name map: record parents, hash -> record, hash -> full name (O lines)."""
    recs: dict[str, list[str]] = {}
    lut_rec: dict[str, str] = {}
    full: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if p[0] == "R" and len(p) > 6:
            recs[p[1]] = [q for q in p[6].split(",") if q]
        elif p[0] == "O" and len(p) > 8:
            lut_rec[p[3]] = p[8]
            full[p[3]] = p[4]
    return recs, lut_rec, full


def read_proc_names(path: Path) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split("\t")
        if p[0] == "O" and len(p) > 8 and p[2] == "node":
            out[p[4]] = (p[3], p[8])
    return out


def load_dumps(work: Path, top: str) -> Dumps:
    def module(name: str) -> dict[str, Any]:
        d = json.loads((work / name).read_text(encoding="utf-8"))
        mods = d["modules"]
        if top not in mods:
            raise NetsError(f"{name} has no module {top}")
        return dict(mods[top])

    recs, lut_rec, full = read_map(work / "rt.blif.names")
    return Dumps(
        top,
        module("proc.json"),
        read_proc_names(work / "proc_h.json.names"),
        module("gates.json"),
        read_scoap(work / "scoap.json", top),
        recs,
        lut_rec,
        full,
        read_scoap_rows(work / "scoap.json", top),
        read_graphs(work),
    )


def bare_name(key: str, top: str) -> str:
    """`memset/cur_state@../f.v:147` -> `cur_state`; a plain port name stays."""
    s = key.split("@", 1)[0]
    return s[len(top) + 1 :] if s.startswith(top + "/") else s
