"""CI test jobs have no PySide6: every tests/test_gui_*.py must import and skip, not error."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK = (
    "import sys, unittest\n"
    "sys.modules['PySide6'] = None\n"  # None makes import raise ImportError, find_spec return None
    "sys.modules['shiboken6'] = None\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "names = sys.argv[2:]\n"
    "suite = unittest.defaultTestLoader.loadTestsFromNames(names)\n"
    "res = unittest.TextTestRunner(verbosity=0).run(suite)\n"
    "sys.exit(0 if res.wasSuccessful() and not res.errors else 1)\n"
)


class NoPySideTest(unittest.TestCase):
    def test_gui_test_modules_import_and_skip_without_pyside6(self) -> None:
        names = sorted(
            f"tests.{p.stem}"
            for p in (ROOT / "tests").glob("test_gui_*.py")
            if p.stem != Path(__file__).stem
        )
        self.assertTrue(names)
        done = subprocess.run(
            [sys.executable, "-c", BLOCK, str(ROOT), *names],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )  # fmt: skip
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        self.assertIn("skipped", done.stderr)


if __name__ == "__main__":
    unittest.main()
