"""Point the screenshot scripts at an Odin III build (make_shots.py, make_gui_shots.py).

    ODIN3_BUILD   directory with `odin3` and libodin3.so (default: $ODIN3_ROOT/build/release)
    ODIN3_ROOT    an Odin III checkout; its tools/flow and plugins/python are used

Whatever PATH, PYTHONPATH and ODIN3_LIB already hold wins; this only fills in the rest.
Needs Odin III 1.6.0 (C ABI 7) or later; `check_version` stops with a message otherwise.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

MIN_VERSION = (1, 6, 0)


def setup() -> None:
    root = os.environ.get("ODIN3_ROOT")
    build = os.environ.get("ODIN3_BUILD") or (str(Path(root) / "build" / "release") if root else "")
    paths = [p for p in (build, str(Path(root) / "tools" / "flow") if root else "") if p]
    if paths:
        os.environ["PATH"] = os.pathsep.join([*paths, os.environ.get("PATH", "")])
    if root and "ODIN3_LIB" not in os.environ and build:
        os.environ["ODIN3_LIB"] = str(Path(build) / "libodin3.so")
    if root:
        py = str(Path(root) / "plugins" / "python")
        old = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = py if not old else py + os.pathsep + old
        if py not in sys.path:  # this process too, not only the children
            sys.path.append(py)
    check_version()


def check_version() -> None:
    try:
        out = subprocess.run(["odin3", "--version"], capture_output=True, text=True,
                             check=False).stdout
    except OSError:
        sys.exit("odin3 not found: set ODIN3_BUILD (or ODIN3_ROOT) or put odin3 on PATH")
    m = re.match(r"odin3 (\d+)\.(\d+)\.(\d+)", out)
    if not m or tuple(int(x) for x in m.groups()) < MIN_VERSION:
        need = ".".join(map(str, MIN_VERSION))
        sys.exit(f"Odin III {need} or later needed, got: {out.strip()!r}")
