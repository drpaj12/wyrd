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
import subprocess
from dataclasses import dataclass
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


def command_of(log: Path) -> tuple[list[str], str]:
    """The odin3 argv (before -p) and the script text from the `$ ` line of a flow log."""
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("$ ") and " -p " in line:
            head, script = line[2:].split(" -p ", 1)
            return head.split(), script
    raise NetsError(f"no odin3 command line in {log}")


def extended_script(script: str, work: Path, scoap: bool = True) -> str:
    """The script with the two dumps added and the BLIF written under `work`.

    With `scoap`, the scoap pass runs on the netlist the second dump shows (after mapping) and
    writes `work`/scoap.json (net id, CC0, CC1, CO).
    """
    if "; proc;" not in script and not script.startswith("proc;"):
        raise NetsError("the odin3 script has no proc step")
    dump1 = (
        f"write_json --odin3 --name-style provenance {work}/proc.json; "
        f"write_json --odin3 --name-style hash --prov-map {work}/proc_h.json; "
    )
    out = script.replace("proc; ", "proc; " + dump1, 1)
    m = list(re.finditer(r"write_blif ", out))
    if not m:
        raise NetsError("the odin3 script has no write_blif")
    at = m[-1].start()
    tail = re.sub(r'"[^"]*\.blif"', f'"{work}/rt.blif"', out[at:])
    sc = f"scoap --out {work}/scoap.json; " if scoap else ""
    return out[:at] + sc + f"write_json --odin3 --name-style provenance {work}/gates.json; " + tail


def source_cwd(script: str, candidates: list[Path]) -> Path:
    files = re.findall(r'"([^"]+\.s?vh?)"', script)
    for d in candidates:
        if all((d / f).is_file() or Path(f).is_absolute() for f in files):
            return d
    raise NetsError(f"cannot find the HDL files {files} in {[str(c) for c in candidates]}")


def run_dumps(flow: Path, work: Path, search: list[Path]) -> Path:
    """Run the extended script; return `work`. If the run fails and the script had the scoap pass,
    it runs again without it (an Odin III build without that pass still gives the other dumps)."""
    argv, script = command_of(flow / "odin3" / "odin3.log")
    work.mkdir(parents=True, exist_ok=True)
    cwd = source_cwd(script, [*search, flow.parent])
    for with_scoap in (True, False):
        new = extended_script(script, work, with_scoap)
        r = subprocess.run(
            [*argv, "-p", new], cwd=cwd, capture_output=True, text=True, check=False, timeout=600
        )
        if r.returncode == 0:
            return work
        if not with_scoap or "scoap" not in r.stderr:
            break
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
    )


def bare_name(key: str, top: str) -> str:
    """`memset/cur_state@../f.v:147` -> `cur_state`; a plain port name stays."""
    s = key.split("@", 1)[0]
    return s[len(top) + 1 :] if s.startswith(top + "/") else s
