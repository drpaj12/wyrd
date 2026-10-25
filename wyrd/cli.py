"""Command line: `wyrd init | run | status | table | compare | script | timing | config | sim`."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from wyrd import report, settings
from wyrd.guimodel import timing
from wyrd.preflight import ProjectLocked, acquire_lock, preflight
from wyrd.project import ConfigError, Project, load_project
from wyrd.sched import run_all
from wyrd.store import Store

if TYPE_CHECKING:
    from wyrd.bifrost import (
        Backend,
        BifrostSession,
        Diagnostic,
        Recording,
        VectorFile,
    )


def _config_init() -> int:
    path = settings.machine_path()
    if path.exists():
        print(f"wyrd: {path} already exists", file=sys.stderr)
        return 2
    try:
        settings.write_machine_file(path)
    except OSError as e:
        print(f"wyrd: cannot write {path}: {e}", file=sys.stderr)
        return 2
    print(f"wrote {path}")
    return 0


def _config_show() -> int:
    try:
        s = settings.load(None, {})
    except (ValueError, OSError) as e:
        print(f"wyrd: {e}", file=sys.stderr)
        return 2
    for name in settings.field_names():
        value = getattr(s, name)
        shown = value if not isinstance(value, Path) else str(value)
        print(f"{name} = {shown}  ({s.sources.get(name, 'default')})")
    return 0


_TEMPLATE = """\
# wyrd project file. Tool locations are machine settings (`wyrd config init`), not set here.
[project]
name = "myproject"

# One [[design]] per design. Replace the placeholder path with your Verilog files.
[[design]]
name = "mydesign"
files = ["CHANGE_ME.v"]
# top = "top"

# A recipe is an ordered list of steps: odin3-flow, odin3, vpr, abc or shell.
[recipe.vtr]
steps = [{ use = "odin3-flow", target = "vtr", vpr = true }]

# The sweep: every recipe x design x arch (plus any extra parameter lists) becomes one run.
[sweep]
recipe = ["vtr"]
design = ["mydesign"]
arch = ["k6_frac_N10_frac_chain_mem32K_40nm"]

# Experiment settings only (step_timeout); machine settings do not go here.
[run]
# step_timeout = 3600
"""


def _err(msg: str) -> int:
    print(f"wyrd: {msg}", file=sys.stderr)
    return 2


def _fail(msg: str) -> int:
    """A run or file that exists but is not usable: exit 1 (2 stays for usage and config errors)."""
    print(f"wyrd: {msg}", file=sys.stderr)
    return 1


def _init(directory: str) -> int:
    target = Path(directory) / "wyrd.toml"
    if target.exists():
        return _err(f"{target} already exists")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_TEMPLATE, encoding="utf-8")
    except OSError as e:
        return _err(f"cannot write {target}: {e}")
    print(f"wrote {target}")
    return 0


def _quiet(line: str) -> None:
    """The CLI prints its own per-run lines; the scheduler's progress log is dropped."""


def _stdout_line(line: str) -> None:
    print(line, flush=True)


def _run(args: argparse.Namespace) -> int:
    root = Path(args.project)
    try:
        project = load_project(root / "wyrd.toml")
        cli = {"jobs": args.jobs, "mem_budget": args.mem_budget}
        s = settings.load(project.run, cli)
    except (ConfigError, ValueError, OSError) as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")
    try:
        fd = acquire_lock(project.root)
    except ProjectLocked as e:
        return _err(str(e))
    except OSError as e:
        return _err(f"cannot lock {project.root}: {e}")
    try:
        return _run_locked(project, s, args.force, args.progress)
    finally:
        os.close(fd)


def _run_locked(
    project: Project, s: settings.Settings, force: bool, progress: bool = False
) -> int:
    problems = preflight(project, s)
    if problems:
        for problem in problems:
            print(f"wyrd: {problem}", file=sys.stderr)
        return 2
    if not project.runs:
        return _err("no runs in the sweep")
    try:
        store = Store(project.root / "wyrd.db")
        results = run_all(project, s, store, force, log=_stdout_line if progress else _quiet)
        by_key = {str(r["key"]): r for r in store.rows()}
    except (OSError, sqlite3.Error) as e:
        return _err(f"run failed: {e}")
    for key, status in results.items():
        row = by_key.get(key, {})
        print(f"{status} {row.get('design', '?')} {row.get('arch', '?')} {key[:12]}")
    complete = len(results) >= len(project.runs)
    return 0 if complete and all(v == "ok" for v in results.values()) else 1


def _rows(project: str) -> list[dict[str, object]] | None:
    db = Path(project) / "wyrd.db"
    if not db.is_file():
        _err(f"{db} not found (nothing has run in {project})")
        return None
    try:
        return Store.open_readonly(db).rows()
    except sqlite3.Error as e:
        _err(f"cannot read {db}: {e}")
        return None


def _status(args: argparse.Namespace) -> int:
    rows = _rows(args.project)
    if rows is None:
        return 2
    counts = Counter(str(r["status"]) for r in rows)
    for status in sorted(counts):
        print(f"{status} {counts[status]}")
    return 0


def _split(text: str | None) -> list[str] | None:
    return None if text is None else [m.strip() for m in text.split(",") if m.strip()]


def _table(args: argparse.Namespace) -> int:
    rows = _rows(args.project)
    if rows is None:
        return 2
    print(report.render(report.table(rows, _split(args.metrics)), args.format))
    return 0


def _compare(args: argparse.Namespace) -> int:
    a, b = _rows(args.a), _rows(args.b)
    if a is None or b is None:
        return 2
    for line in report.unmatched(a, b):
        print(line, file=sys.stderr)
    print(report.render(report.compare(a, b, _split(args.metrics)), args.format))
    return 0


def _find_run(rows: list[dict[str, object]], key: str) -> dict[str, object] | str:
    if len(key) < 6:
        return "key prefix needs at least 6 characters"
    found = [r for r in rows if str(r["key"]).startswith(key)]
    if not found:
        return f"no run with key starting {key!r}"
    if len(found) > 1:
        return f"key prefix {key!r} is ambiguous ({len(found)} runs)"
    return found[0]


def _script(args: argparse.Namespace) -> int:
    rows = _rows(args.project)
    if rows is None:
        return 2
    run = _find_run(rows, args.key)
    if isinstance(run, str):
        return _err(run)
    directory = Path(str(run["run_dir"]))
    numbered: list[tuple[int, Path]] = []
    for cmd in directory.glob("[0-9]*-*/cmd.sh"):
        m = re.fullmatch(r"(\d+)-.+", cmd.parent.name)
        if m:
            numbered.append((int(m.group(1)), cmd))
    cmds = [c for _, c in sorted(numbered)]
    if not cmds:
        return _err(f"no cmd.sh files under {directory}")
    header = [
        "#!/bin/sh",
        "# Replay re-runs the steps in place and overwrites their outputs in this run directory.",
        "set -e",
    ]
    lines = header + [f"sh {shlex.quote(str(c))}" for c in cmds]
    out = directory / "replay.sh"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.chmod(0o755)
    print(out)
    return 0


def _timing(args: argparse.Namespace) -> int:
    if args.top < 1:
        return _err("--top must be at least 1")
    rows = _rows(args.project)
    if rows is None:
        return 2
    run = _find_run(rows, args.key)
    if isinstance(run, str):
        return _err(run)
    if run["status"] != "ok":
        return _fail(f"run {str(run['key'])[:12]} has status {run['status']}, not ok")
    run_dir = Path(str(run["run_dir"]))
    path = timing.find_attribution(run_dir)
    if path is None:
        reason = timing.missing_reason(run_dir)
        return _err(
            "no timing attribution for this run: "
            + (reason or "use odin3-flow with timing_attr = true")
        )
    try:
        att = timing.load_attribution(path)
    except timing.TimingError as e:
        return _fail(str(e))
    print("\n".join(timing.summary_lines(att, args.top)))
    return 0


def _sim_backend() -> Backend:
    from wyrd.bifrost import default_backend

    return default_backend()


def _sim_where(d: Diagnostic) -> str:
    parts = [d.file, None if d.line is None else str(d.line), None if d.col is None else str(d.col)]
    where = ":".join(x for x in parts if x is not None)
    return f"{where}: " if where else ""


def _sim_diag(d: Diagnostic) -> None:
    print(f"{_sim_where(d)}{d.severity}: {d.message}", file=sys.stderr)


def _print_run(rec: Recording, csv: bool) -> None:
    ins = [n for n in rec.names if n in rec.inputs]
    outs = [n for n in rec.names if n not in rec.inputs]
    shown = ins + outs
    if csv:
        print(",".join(["cycle", *shown]))
    for cycle, sample in zip(rec.cycles[1:], rec.samples[1:], strict=True):
        by_name = dict(zip(rec.names, sample, strict=True))
        if csv:
            print(",".join([str(cycle), *(str(by_name[n]) for n in shown)]))
            continue
        left = " ".join(f"{n}={by_name[n]}" for n in ins)
        right = " ".join(f"{n}={by_name[n]}" for n in outs)
        print(f"{cycle}: {left} | {right}" if outs else f"{cycle}: {left}")


def _sim_vectors(args: argparse.Namespace, session: BifrostSession) -> VectorFile:
    from wyrd.bifrost import parse_vectors, random_vectors, session_ports

    ports, outs = session_ports(session)
    if args.vectors is not None:
        text = Path(args.vectors).read_text(encoding="utf-8")
        return parse_vectors(text, ports, outs, args.vectors)
    return random_vectors(ports, args.random, args.seed)


def _sim_write(args: argparse.Namespace, session: BifrostSession, vf: VectorFile) -> None:
    from wyrd.bifrost import format_vectors, session_ports, write_vcd

    rec = session.recording
    assert rec is not None
    if args.vcd:
        write_vcd(rec, Path(args.vcd))
    if args.save_vectors:
        ports, outs = session_ports(session)
        text = format_vectors(vf, ports, outs, recording=rec, seed=args.seed)
        Path(args.save_vectors).write_text(text, encoding="utf-8")


def _sim_session(args: argparse.Namespace, session: BifrostSession) -> int:
    for d in session.diagnostics:
        _sim_diag(d)
    vf = _sim_vectors(args, session)
    rec = session.run_vectors(vf)
    _print_run(rec, args.csv)
    _sim_write(args, session, vf)
    return 0


def _sim(args: argparse.Namespace) -> int:
    from wyrd.bifrost import BifrostSession, CompileError, SimError

    try:
        backend = _sim_backend()
        with BifrostSession.from_verilog(args.files, top=args.top, backend=backend) as session:
            return _sim_session(args, session)
    except CompileError as e:
        for d in e.diagnostics or ():
            _sim_diag(d)
        if not e.diagnostics:
            print(f"wyrd: {e}", file=sys.stderr)
        return 2
    except (SimError, ValueError, OSError) as e:
        return _err(str(e))


def _with_project(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
    p.add_argument("--project", default=".", metavar="DIR")
    return p


def _with_format(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", choices=["md", "csv"], default="md")
    p.add_argument("--metrics", help="comma-separated metric names (filters and orders columns)")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wyrd")
    sub = p.add_subparsers(dest="command", required=True)
    cfg = sub.add_parser("config", help="machine settings")
    cfg.add_argument("action", choices=["init", "show"])
    init = sub.add_parser("init", help="write a commented wyrd.toml")
    init.add_argument("dir", nargs="?", default=".")
    run = _with_project(sub.add_parser("run", help="run the project's sweep"))
    run.add_argument("--force", action="store_true", help="re-run runs that are already ok")
    run.add_argument("--jobs", type=int, help="parallel runs")
    run.add_argument("--mem-budget", help='memory budget, e.g. "24G" or "60%"')
    run.add_argument(
        "--progress", action="store_true", help="print one line per finished run to stdout"
    )
    _with_project(sub.add_parser("status", help="count runs per status"))
    table = _with_project(sub.add_parser("table", help="one row per design and arch"))
    _with_format(table)
    compare = sub.add_parser("compare", help="compare two project directories")
    compare.add_argument("a")
    compare.add_argument("b")
    _with_format(compare)
    script = _with_project(sub.add_parser("script", help="write replay.sh for a run"))
    script.add_argument("key", help="run key or a prefix of at least 6 characters")
    tim = _with_project(sub.add_parser("timing", help="critical-path attribution of a run"))
    tim.add_argument("key", help="run key or a prefix of at least 6 characters")
    tim.add_argument("--top", type=int, default=10, metavar="N", help="statements to list")
    sim = sub.add_parser("sim", help="simulate Verilog files cycle by cycle (needs wyrd[sim])")
    sim.add_argument("files", nargs="+")
    sim.add_argument("--top")
    source = sim.add_mutually_exclusive_group(required=True)
    source.add_argument("--vectors", metavar="FILE")
    source.add_argument("--random", type=int, metavar="N")
    sim.add_argument("--seed", type=int, default=0)
    sim.add_argument("--vcd", metavar="OUT")
    sim.add_argument("--save-vectors", metavar="FILE")
    sim.add_argument("--csv", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.command == "config":
        return _config_init() if args.action == "init" else _config_show()
    if args.command == "init":
        return _init(args.dir)
    handlers = {
        "run": _run,
        "status": _status,
        "table": _table,
        "compare": _compare,
        "script": _script,
        "timing": _timing,
        "sim": _sim,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
