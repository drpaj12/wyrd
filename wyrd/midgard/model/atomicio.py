"""Atomic file replacement: write a temporary file in the target's directory, then `os.replace`.

A failed or interrupted write leaves the old file as it was. The new file keeps the old file's
permission bits, or gets the umask default when there was none (not the 0600 of `mkstemp`).
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path


def _mode_for(path: Path) -> int:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        umask = os.umask(0)
        os.umask(umask)
        return 0o666 & ~umask


def replace_file(path: Path, write: Callable[[Path], None]) -> None:
    """Call `write` on a temporary path beside `path`, then move it over `path`.

    `write` raises OSError on failure; the temporary file is removed on any error. The temporary
    name ends in the target's suffix (`.tmp.png`), for writers that pick a format from it.
    """
    fd, name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=f".tmp{path.suffix}"
    )
    os.close(fd)
    tmp = Path(name)
    try:
        write(tmp)
        os.chmod(tmp, _mode_for(path))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_text_atomic(path: Path, text: str, newline: str | None = None) -> None:
    """Replace `path` with `text` (UTF-8) atomically."""

    def write(tmp: Path) -> None:
        with tmp.open("w", encoding="utf-8", newline=newline) as handle:
            handle.write(text)

    replace_file(path, write)
