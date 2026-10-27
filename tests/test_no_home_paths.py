"""Hygiene gate: no tracked file may contain a user home path (the repo is public).

Use `~/odin3-ws/...` or `$HOME` in docs and commands. Files that mention a home-style path on
purpose are allowlisted below, each with its reason. The test skips outside a git checkout.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Built from parts so this file does not contain the pattern it searches for.
NEEDLE = "/home" + "/"

ALLOWED = {
    "tests/test_no_home_paths.py": "this test",
    "docs/specs/2026-10-21-w1-runner-design.md": "placeholder user in an example wyrd.toml",
}


def tracked_files() -> list[str] | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-files", "-z"], check=True, capture_output=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.decode("utf-8").split("\0")


class NoHomePathsTest(unittest.TestCase):
    def test_tracked_files_have_no_home_path(self) -> None:
        listing = tracked_files()
        if listing is None:
            self.skipTest("not a git checkout")
        bad = []
        for name in listing:
            if not name or name in ALLOWED:
                continue
            path = REPO_ROOT / name
            if not path.is_file() or path.is_symlink():
                continue
            if NEEDLE.encode() in path.read_bytes():
                bad.append(name)
        self.assertEqual(bad, [], f"tracked files contain {NEEDLE!r}; use ~/ or $HOME")


if __name__ == "__main__":
    unittest.main()
