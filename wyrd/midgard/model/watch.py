"""File watch and the external editor command (spec 8)."""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

Stamp = tuple[int, int] | None


def _stamp(path: Path) -> Stamp:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


class FileWatcher:
    def __init__(self, paths: Sequence[Path]) -> None:
        self._state: dict[Path, Stamp] = {}
        self.set_paths(paths)

    def set_paths(self, paths: Sequence[Path]) -> None:
        self._state = {p: _stamp(p) for p in paths}

    def poll(self) -> list[Path]:
        changed: list[Path] = []
        for p, old in self._state.items():
            new = _stamp(p)
            if new != old:
                self._state[p] = new
                changed.append(p)
        return changed


def editor_command(
    path: Path, env: Mapping[str, str], which: Callable[[str], str | None]
) -> list[str] | None:
    custom = env.get("MIDGARD_EDITOR", "").strip()
    if custom:
        return [*shlex.split(custom), str(path)]
    for name in ("code", "xdg-open", "wslview"):
        if which(name) is not None:
            return [name, str(path)]
    return None


def editor_launch_argv(path: Path, level: int, name: str, python: str | None = None) -> list[str]:
    """The command line that starts the Verilog editor window for one player file."""
    return [
        python or sys.executable,
        "-m",
        "wyrd.midgard.editors.verilog_editor",
        "--file",
        str(path),
        "--level",
        str(level),
        "--name",
        name,
    ]
