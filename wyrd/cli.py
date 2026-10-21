"""Command line: `wyrd config init|show` (more commands come in later tasks)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wyrd import settings


def _config_init() -> int:
    path = settings.machine_path()
    if path.exists():
        print(f"wyrd: {path} already exists", file=sys.stderr)
        return 2
    settings.write_machine_file(path)
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


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wyrd")
    sub = p.add_subparsers(dest="command", required=True)
    cfg = sub.add_parser("config", help="machine settings")
    cfg.add_argument("action", choices=["init", "show"])
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    if args.command == "config":
        return _config_init() if args.action == "init" else _config_show()
    return 2


if __name__ == "__main__":
    sys.exit(main())
