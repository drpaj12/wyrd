"""The proc dump and the final dump number the same Odin III record differently (r<n> counts the
records of one file); the `uid=` store ID, written with ODIN3_PROV_UID=1, is the same in both."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wyrd.o3viz import nets

PROC = (
    "R\tr1\tS\texpr\torigin\tt1.1\t\tf1:14.30-14.39\tc5\thier=lin,uid=114\n"
    "O\tlin\tnode\th6macx45vva\tlin/$c19@x.v:14\tlin\tx.v\t14\tr1\texpr\n"
)
FINAL = (
    "R\tr1\tS\tblock\torigin\tt1.1\t\tf1:15.3-21.12\tc2\thier=lin,uid=7\n"
    "R\tr2\tS\texpr\torigin\tt1.1\t\tf1:14.30-14.39\tc5\thier=lin,uid=114\n"
    "R\tr3\tD\tgate\tcoarsen:gate\tt2.1\tr1,r2\t\t\tuid=300\n"
    "O\tlin\tnet\thlut\tlin/$n20@x.v:14\tlin\tx.v\t14\tr3\tlut\n"
)


class Uid(unittest.TestCase):
    def test_records_join_by_store_id(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "p.names").write_text(PROC)
            (tmp / "f.names").write_text(FINAL)
            proc = nets.read_proc_names(tmp / "p.names")
            recs, lut_rec, _ = nets.read_map(tmp / "f.names")
        # r1 in the proc file, r2 in the final one: the store ID is the same
        self.assertEqual(("h6macx45vva", "u114"), proc["lin/$c19@x.v:14"])
        self.assertEqual("u300", lut_rec["hlut"])
        self.assertEqual(["u7", "u114"], recs["u300"])

    def test_a_map_without_uid_keeps_its_record_ids(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "f.names"
            path.write_text("R\tr1\tS\texpr\torigin\tt1.1\t\tf1:1.1-1.2\tc1\thier=m\n")
            recs, _, _ = nets.read_map(path)
        self.assertEqual({"r1": []}, recs)


if __name__ == "__main__":
    unittest.main()
