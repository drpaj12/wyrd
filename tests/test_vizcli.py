"""`wyrd viz` forwards to Heimdall III when installed and says how to install it otherwise."""

from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import redirect_stderr
from unittest import mock

from wyrd import cli


class TestVizShim(unittest.TestCase):
    def test_missing_heimdall(self) -> None:
        err = io.StringIO()
        with (
            mock.patch.dict(sys.modules, {"heimdall": None, "heimdall.cli": None}),
            redirect_stderr(err),
        ):
            self.assertEqual(cli.main(["viz", "serve", "x"]), 2)
        self.assertIn("pip install", err.getvalue())
        self.assertIn("heimdallIII", err.getvalue())

    def test_forwards_arguments(self) -> None:
        seen: list[list[str]] = []

        def fake_main(argv: list[str]) -> int:
            seen.append(argv)
            return 0

        fake = types.SimpleNamespace(main=fake_main)
        with mock.patch.dict(
            sys.modules, {"heimdall": types.ModuleType("heimdall"), "heimdall.cli": fake}
        ):
            self.assertEqual(cli.main(["viz", "export", "RUN", "--out", "b"]), 0)
        self.assertEqual(seen, [["export", "RUN", "--out", "b"]])


if __name__ == "__main__":
    unittest.main()
