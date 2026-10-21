"""Command line: `wyrd init | run | status | table | compare | script | config` (spec section 3)."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections import Counter
from pathlib import Path

from wyrd import report, settings
from wyrd.preflight import ProjectLocked, acquire_lock, preflight
from wyrd.project import ConfigError, Project, load_project
from wyrd.sched import run_all
from wyrd.store import Store


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


def _run(args: argparse.Namespace) -> int:
    root = Path(args.project)
    try:
        project = load_project(root / "wyrd.toml")
        cli = {"jobs": args.jobs, "mem_budget": args.mem_budget}
        s = settings.load(project.run, cli)
    except (ConfigError, ValueError, OSError) as e:
        return _err(str(e))
    try:
        fd = acquire_lock(project.root)
    except ProjectLocked as e:
        return _err(str(e))
    except OSError as e:
        return _err(f"cannot lock {project.root}: {e}")
    try:
        return _run_locked(project, s, args.force)
    finally:
        os.close(fd)


def _run_locked(project: Project, s: settings.Settings, force: bool) -> int:
    problems = preflight(project, s)
    if problems:
        for problem in problems:
            print(f"wyrd: {problem}", file=sys.stderr)
        return 2
    store = Store(project.root / "wyrd.db")
    results = run_all(project, s, store, force)
    by_key = {str(r["key"]): r for r in store.rows()}
    for key, status in results.items():
        row = by_key.get(key, {})
        print(f"{status} {row.get('design', '?')} {row.get('arch', '?')} {key[:12]}")
    return 0 if all(v == "ok" for v in results.values()) else 1


def _rows(project: str) -> list[dict[str, object]] | None:
    db = Path(project) / "wyrd.db"
    if not db.is_file():
        _err(f"{db} not found (nothing has run in {project})")
        return None
    return Store(db).rows()


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
    cmds = sorted(directory.glob("*/cmd.sh"), key=lambda p: int(p.parent.name.split("-", 1)[0]))
    if not cmds:
        return _err(f"no cmd.sh files under {directory}")
    lines = ["#!/bin/sh", "set -e"] + [f"sh {shlex.quote(str(c))}" for c in cmds]
    out = directory / "replay.sh"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out.chmod(0o755)
    print(out)
    return 0


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
    _with_project(sub.add_parser("status", help="count runs per status"))
    table = _with_project(sub.add_parser("table", help="one row per design and arch"))
    _with_format(table)
    compare = sub.add_parser("compare", help="compare two project directories")
    compare.add_argument("a")
    compare.add_argument("b")
    _with_format(compare)
    script = _with_project(sub.add_parser("script", help="write replay.sh for a run"))
    script.add_argument("key", help="run key or a prefix of at least 6 characters")
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
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
