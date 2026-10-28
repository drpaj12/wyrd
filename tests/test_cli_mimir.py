"""`wyrd mimir` on a synthetic v4 store."""

import csv
import io
import tempfile
import unittest
from pathlib import Path

from tests import mimir_fixture
from tests.test_cli import wyrd


class MimirCliTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = str(mimir_fixture.build(Path(tmp.name) / "s.db"))
        self.dir = Path(tmp.name)

    def test_summary(self) -> None:
        code, out, _ = wyrd("mimir", "summary", self.db)
        self.assertEqual(code, 0)
        self.assertIn("schema version 4", out)
        self.assertIn("records=18", out)
        self.assertIn("exp-a-1", out)

    def test_designs(self) -> None:
        code, out, _ = wyrd("mimir", "designs", self.db, "--source", "exp-a-1", "--filter", "d2")
        self.assertEqual(code, 0)
        self.assertIn("d2", out)
        self.assertNotIn("d1", out)
        _, out, _ = wyrd("mimir", "designs", self.db, "--csv", "--limit", "2")
        rows = list(csv.reader(io.StringIO(out)))
        self.assertEqual(rows[0][:2], ["source", "name"])
        self.assertEqual(len(rows), 4)  # header, 2 rows, the truncation comment
        self.assertTrue(rows[-1][0].startswith("# truncated"))
        _, out, _ = wyrd("mimir", "designs", self.db, "--limit", "2")
        self.assertIn("more rows", out)

    def test_csv_truncated(self) -> None:
        code, out, err = wyrd("mimir", "designs", self.db, "--csv", "--limit", "2")
        self.assertEqual(code, 0)
        self.assertTrue(out.endswith("# truncated at 2 rows\n"))
        self.assertIn("truncated at 2 rows", err)
        _, out, err = wyrd("mimir", "designs", self.db, "--csv", "--limit", "0")
        self.assertNotIn("truncated", out + err)

    def test_design_level(self) -> None:
        _, out, _ = wyrd("mimir", "design", self.db, "d1", "--csv", "--level", "clb")
        self.assertEqual(len(out.splitlines()), 3)

    def test_design(self) -> None:
        code, out, _ = wyrd("mimir", "design", self.db, "d1")
        self.assertEqual(code, 0)
        for text in ("vpr.cpd", "[runs]", "Ann", "SIS", "adder"):
            self.assertIn(text, out)
        _, out, _ = wyrd("mimir", "design", self.db, "d1", "--csv", "--source", "exp-a-2")
        self.assertEqual(len(out.splitlines()), 4)

    def test_run(self) -> None:
        code, out, _ = wyrd("mimir", "run", self.db, "r1")
        self.assertEqual(code, 0)
        for text in ("config.name: exp-a-1/base", "inner_num", "abc123"):
            self.assertIn(text, out)
        _, out, _ = wyrd("mimir", "run", self.db, "r1", "--csv")
        self.assertTrue(out.startswith("step,key,value,conf,source"))

    def test_compare(self) -> None:
        args = ("--prefix", "exp-a-", "--base", "exp-a-1/base", "--metric", "vpr.cpd")
        code, out, _ = wyrd("mimir", "compare", self.db, *args)
        self.assertEqual(code, 0)
        self.assertIn("exp-a-2/alt", out)
        _, out, _ = wyrd("mimir", "compare", self.db, *args, "--csv", "--level", "routed")
        self.assertIn("exp-a-1/base,routed,3,1.0000,0,0,1,1,", out)
        self.assertIn("dropped (<=0 or non-numeric)", out)
        _, out, _ = wyrd("mimir", "compare", self.db, *args)
        self.assertIn("routed", out)

    def test_errors(self) -> None:
        for argv in (
            ("mimir", "summary", str(self.dir / "none.db")),
            ("mimir", "design", self.db, "nope"),
            ("mimir", "run", self.db, "zz"),
            ("mimir", "compare", self.db, "--prefix", "x", "--base", "y", "--metric", "m"),
        ):
            code, _, err = wyrd(*argv)
            self.assertEqual(code, 2)
            self.assertIn("wyrd:", err)
        self.assertEqual(wyrd("mimir")[0], 2)


if __name__ == "__main__":
    unittest.main()
