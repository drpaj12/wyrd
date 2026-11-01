"""Testbench mode against a real Odin III with run_testbenches (skipped when it is absent)."""

import io
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from wyrd import cli
from wyrd.bifrost import (
    BifrostSession,
    TbSpec,
    VectorFile,
    format_vectors,
    random_vectors,
    run_project_testbenches,
    run_testbench_file,
    session_ports,
    testbench_available,
    testbench_file_to_vcd,
    testbench_file_to_vectors,
    vcd_text,
    vectors_file_to_testbench,
)
from wyrd.bifrost.testbench import On

DATA = Path(__file__).parent / "data"
TB = DATA / "tb"
TRAFFIC = DATA / "sim" / "traffic.v"
IVERILOG = shutil.which("iverilog") and shutil.which("vvp")


@unittest.skipUnless(testbench_available(), "Odin III with run_testbenches is not installed")
class RealTestbenchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def traffic_vectors(self) -> Path:
        """A vector file saved the way `wyrd sim --save-vectors` does (reset first)."""
        with BifrostSession.from_verilog([TRAFFIC]) as s:
            ports, outs = session_ports(s)
            rows = [(1, 0, 0)] * 3 + list(random_vectors(ports, 40, 5).rows[3:])
            vf = VectorFile(tuple(rows))
            text = format_vectors(vf, ports, outs, recording=s.run_vectors(vf), seed=5)
        path = self.dir / "v.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def test_project(self) -> None:
        rep = run_project_testbenches(TB / "project.o3proj")
        by = {r.name: r for r in rep.results}
        self.assertEqual(
            {n: r.status for n, r in by.items()},
            {"good": "pass", "bad": "fail", "both": "pass", "hang": "timeout", "err": "error"},
        )
        mm = by["bad"].mismatch
        assert mm is not None
        self.assertEqual((mm.line, mm.time, mm.field, mm.want, mm.got), (5, 4, 1, "4 9 0", "4 5 0"))
        self.assertIn("unsupported", by["err"].error or "")
        self.assertTrue(by["hang"].timeout)
        self.assertFalse(rep.ok)

    def test_project_only(self) -> None:
        rep = run_project_testbenches(TB / "project.o3proj", only="both")
        self.assertEqual([(r.name, r.status) for r in rep.results], [("both", "pass")])

    def test_file_on_each_target(self) -> None:
        ons: tuple[On, ...] = ("rtl", "netlist", "both")
        for on in ons:
            spec = TbSpec(TB / "tb_good.v", [TB / "counter.v"], on=on, expect=TB / "good.expect")
            r = run_testbench_file(spec)
            self.assertEqual((on, r.status), (on, "pass"), r.error)
            assert r.output is not None
            self.assertEqual(r.output, (TB / "good.expect").read_text(encoding="utf-8"))

    def test_file_failures(self) -> None:
        bad = run_testbench_file(
            TbSpec(TB / "tb_good.v", [TB / "counter.v"], expect=TB / "bad.expect")
        )
        self.assertEqual(bad.status, "fail")
        hang = run_testbench_file(TbSpec(TB / "tb_hang.v", [TB / "counter.v"], max_time=50))
        self.assertEqual(hang.status, "timeout")
        err = run_testbench_file(TbSpec(TB / "tb_err.v", [TB / "counter.v"]))
        self.assertEqual(err.status, "error")
        self.assertIsNone(err.output)

    def test_round_trip_is_identical(self) -> None:
        vec = self.traffic_vectors()
        tb = self.dir / "tb.v"
        self.assertEqual(vectors_file_to_testbench([TRAFFIC], vec, tb), 40)
        back = self.dir / "back.txt"
        self.assertEqual(testbench_file_to_vectors([TRAFFIC], tb, back), 40)
        self.assertEqual(back.read_text(encoding="utf-8"), vec.read_text(encoding="utf-8"))

    @unittest.skipUnless(IVERILOG, "iverilog is not installed")
    def test_iverilog_agrees(self) -> None:
        vec = self.traffic_vectors()
        tb = self.dir / "tb.v"
        vectors_file_to_testbench([TRAFFIC], vec, tb)
        vvp = self.dir / "t.vvp"
        subprocess.run(["iverilog", "-g2005", "-o", str(vvp), str(tb), str(TRAFFIC)], check=True)
        done = subprocess.run(["vvp", str(vvp)], check=True, capture_output=True, text=True)
        shown = [x for x in done.stdout.splitlines() if x[:1].isdigit()]
        want = [x for x in vec.read_text(encoding="utf-8").splitlines() if x[:1].isdigit()]
        self.assertEqual(shown, want)
        self.assertEqual(run_testbench_file(TbSpec(tb, [TRAFFIC])).output, "\n".join(shown) + "\n")

    def test_derived_vcd_matches_the_direct_one(self) -> None:
        vec = self.traffic_vectors()
        tb = self.dir / "tb.v"
        vectors_file_to_testbench([TRAFFIC], vec, tb)
        r = run_testbench_file(TbSpec(tb, [TRAFFIC]))
        assert r.output is not None
        out = self.dir / "o.vcd"
        testbench_file_to_vcd([TRAFFIC], r.output, out)
        with BifrostSession.from_verilog([TRAFFIC]) as s:
            ports, outs = session_ports(s)
            from wyrd.bifrost import parse_vectors

            vf = parse_vectors(vec.read_text(encoding="utf-8"), ports, outs)
            direct = vcd_text(s.run_vectors(vf))
        self.assertEqual(out.read_text(encoding="utf-8"), direct)

    def test_cli(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(
                ["tb", "run", "--project", str(TB / "project.o3proj"), "--only", "good"]
            )
        self.assertEqual(
            (code, out.getvalue().splitlines()[0].split()[:3]), (0, ["good", "pass", "rtl"])
        )
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["tb", "run", "--project", str(TB / "project.o3proj"), "--only", "bad"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
