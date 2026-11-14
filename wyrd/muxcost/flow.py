"""Run Odin III for the mux cost report.

``odin3-flow --prov --prov-cut --no-vpr`` runs first: it is the one definition of the Odin III
script. Its first log line is the exact ``odin3`` command; the same command runs again with one
more pass, ``write_json --odin3 --name-style hash --prov-map`` before ``lower``, so the word-level
muxes and the mapped BLIF come from one run with one set of record ids (``ODIN3_PROV_UID=1``).
Odin III is used as a program only.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wyrd.muxcost.report import Inputs

DEFAULT_TIMEOUT_S = 3600
SNAPSHOT = "snapshot.json"
_LOWER = "; lower;"
_WRITE = re.compile(r'write_blif (.*?)"[^"]*/([^"/]+\.blif)"\s*$')
_LUT_K = re.compile(r"abc --lut (\d+)")


class FlowError(Exception):
    """Odin III did not run to the end; the message says why, in one line."""


@dataclass(frozen=True)
class FlowSpec:
    files: tuple[Path, ...]
    top: str | None
    out: Path
    odin3_flow: str
    odin3: str
    timeout_s: int = DEFAULT_TIMEOUT_S


def _tail(path: Path) -> str:
    try:
        lines = [x for x in path.read_text(encoding="utf-8", errors="replace").splitlines() if x]
    except OSError:
        return ""
    return lines[-1][:300] if lines else ""


def _run(argv: Sequence[str], cwd: Path | None, env: dict[str, str], timeout_s: int) -> int:
    try:
        return subprocess.run(
            list(argv), cwd=cwd, env=env, timeout=timeout_s, check=False, capture_output=True
        ).returncode
    except subprocess.TimeoutExpired as e:
        raise FlowError(f"{Path(argv[0]).name} ran over {timeout_s} s") from e
    except OSError as e:
        raise FlowError(f"cannot run {argv[0]}: {e.strerror or e}") from e


def flow_argv(spec: FlowSpec, flow_out: Path) -> list[str]:
    argv = [spec.odin3_flow, *map(str, spec.files)]
    if spec.top:
        argv += ["--top", spec.top]
    argv += ["--target", "vtr", "--no-vpr", "--prov", "--prov-cut", "--out", str(flow_out)]
    found = shutil.which(spec.odin3)
    if found:
        argv += ["--odin3", found]
    return argv


def replay_script(script: str, snapshot: Path, blif_dir: Path) -> str:
    """The flow script with a snapshot before ``lower`` and its BLIF moved to ``blif_dir``."""
    if script.count(_LOWER) != 1:
        raise FlowError("the odin3 script has no single lower pass to write a snapshot before")
    write = f'; write_json --odin3 --name-style hash --prov-map "{snapshot}"{_LOWER}'
    script = script.replace(_LOWER, write, 1)
    done = _WRITE.sub(lambda m: f'write_blif {m.group(1)}"{blif_dir}/{m.group(2)}"', script)
    if done == script:
        raise FlowError("the odin3 script has no write_blif to redirect")
    return done


def split_command(first_line: str) -> tuple[list[str], str]:
    """(argv before ``-p``, the script) of the ``$ ...`` line the flow logs first."""
    if not first_line.startswith("$ ") or " -p " not in first_line:
        raise FlowError("the odin3 log does not start with the command line")
    pre, script = first_line[2:].split(" -p ", 1)
    return shlex.split(pre), script


def work_dir(files: Sequence[Path]) -> Path:
    """The directory odin3 runs in: the common parent of the design files (as the flow does)."""
    return Path(os.path.commonpath([str(f.resolve().parent) for f in files]))


def run(spec: FlowSpec) -> Inputs:
    """Run the flow, then the replay; return the files of the analysis. Raise ``FlowError``."""
    out = spec.out.resolve()
    flow_out, dest = out / "flow", out / "words"
    dest.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "ODIN3_PROV_UID": "1"}
    if _run(flow_argv(spec, flow_out), None, env, spec.timeout_s) != 0:
        raise FlowError(f"odin3-flow failed: {_tail(flow_out / 'odin3' / 'odin3.log')}")
    log = flow_out / "odin3" / "odin3.log"
    try:
        first = log.read_text(encoding="utf-8").split("\n", 1)[0]
    except OSError as e:
        raise FlowError(f"cannot read {log.name}: {e.strerror or e}") from e
    argv, script = split_command(first)
    snap = dest / SNAPSHOT
    argv += ["-p", replay_script(script, snap, dest)]
    if _run(argv, work_dir(spec.files), env, spec.timeout_s) != 0:
        raise FlowError("the odin3 replay failed (see its command in flow/odin3/odin3.log)")
    blifs = sorted(dest.glob("*.blif"))
    if len(blifs) != 1 or not snap.is_file():
        raise FlowError("the odin3 replay wrote no BLIF or no snapshot")
    k = _LUT_K.search(script)
    return Inputs(
        snap,
        snap.with_name(snap.name + ".names"),
        blifs[0],
        blifs[0].with_name(blifs[0].name + ".names"),
        None,
        int(k.group(1)) if k else 6,
    )
