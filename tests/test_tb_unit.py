"""Testbench mode without Odin III: a fake script runner, the converters and the CLI."""

import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

from wyrd import cli
from wyrd.bifrost import (
    ConvertError,
    ScriptOutcome,
    TbError,
    TbSpec,
    detect_top,
    run_project_testbenches,
    run_testbench_file,
    testbench_to_vectors,
    vectors_to_testbench,
)
from wyrd.bifrost.testbench import parse_report
from wyrd.bifrost.types import Signal
from wyrd.bifrost.vectors import VectorFile

PORTS = (Signal("clk", 1, "clock"), Signal("rst", 1, "input"), Signal("d", 4, "input"))
OUTS = (Signal("q", 4, "output", 3, 0), Signal("v", 1, "output"))
HEADER = "# wyrd seed 3 cycles 3"
ROWS = ((1, 5), (0, 10), (0, 0))

RESULT: dict[str, Any] = {
    "testbenches": [
        {
            "name": "a",
            "status": "pass",
            "on": "rtl",
            "wall_ms": 2,
            "end_time": 9,
            "lines": 3,
            "mismatch": None,
            "timeout": False,
            "error": None,
        },
        {
            "name": "b",
            "status": "fail",
            "on": "both",
            "wall_ms": 1,
            "end_time": 9,
            "lines": 3,
            "mismatch": {
                "compared": "expect",
                "line": 2,
                "time": 1,
                "field": 1,
                "want": "1 9",
                "got": "1 5",
            },
            "timeout": False,
            "error": None,
        },
        {
            "name": "c",
            "status": "fail",
            "on": "rtl",
            "wall_ms": 0,
            "end_time": 0,
            "lines": 0,
            "mismatch": None,
            "timeout": True,
            "error": "no $finish by time 100",
        },
        {
            "name": "d",
            "status": "error",
            "on": "rtl",
            "wall_ms": 0,
            "end_time": 0,
            "lines": 0,
            "mismatch": None,
            "timeout": False,
            "error": "run (rtl): unsupported",
        },
    ],
    "passed": 1,
    "failed": 2,
    "errors": 1,
}


class FakeRunner:
    """Writes `result` to the `--json` path of a run_testbenches script; records the scripts."""

    def __init__(self, result: object = RESULT, output: str = "0 1 2\n") -> None:
        self.result = result
        self.output = output
        self.scripts: list[str] = []

    def run(self, script: str) -> ScriptOutcome:
        self.scripts.append(script)
        m = re.search(r"--json (\S+)", script)
        if m:
            Path(m.group(1)).write_text(json.dumps(self.result), encoding="utf-8")
        o = re.search(r"--out (\S+)", script)
        if o:
            Path(o.group(1)).write_text(self.output, encoding="utf-8")
        return ScriptOutcome("sim_tb" in script, "run_testbenches failed", ())


def vector_file() -> VectorFile:
    return VectorFile(tuple(ROWS))


class ReportTest(unittest.TestCase):
    def test_statuses(self) -> None:
        rep = parse_report(json.dumps(RESULT))
        self.assertEqual([r.status for r in rep.results], ["pass", "fail", "timeout", "error"])
        self.assertFalse(rep.ok)
        self.assertEqual(rep.count("timeout"), 1)
        mm = rep.results[1].mismatch
        assert mm is not None
        self.assertEqual((mm.line, mm.time, mm.field, mm.want), (2, 1, 1, "1 9"))

    def test_json_round_trip(self) -> None:
        rep = parse_report(json.dumps(RESULT))
        again = parse_report(rep.to_json())
        self.assertEqual(rep.results, again.results)

    def test_bad_json(self) -> None:
        with self.assertRaises(TbError):
            parse_report("{}")
        with self.assertRaises(TbError):
            parse_report(json.dumps({"testbenches": [{"name": "x", "status": "weird"}]}))


class RunnerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_project_script(self) -> None:
        proj = self.dir / "p.o3proj"
        proj.write_text("file verilog a.v\ntestbench t file t.v\n", encoding="utf-8")
        fake = FakeRunner()
        rep = run_project_testbenches(proj, only="t", seed=4, runner=fake)
        self.assertEqual(len(rep.results), 4)
        script = fake.scripts[0]
        self.assertIn(
            f"read_project {proj}; read_verilog; proc; opt; lower; run_testbenches", script
        )
        self.assertNotIn("abc", script)
        self.assertTrue(script.endswith("--seed 4 --only t"))

    def test_netlist_adds_abc(self) -> None:
        proj = self.dir / "p.o3proj"
        proj.write_text("testbench t file t.v on both\ntestbench u file u.v\n", encoding="utf-8")
        fake = FakeRunner()
        run_project_testbenches(proj, runner=fake)
        run_project_testbenches(proj, only="u", runner=fake)
        self.assertIn("abc --lut 6", fake.scripts[0])
        self.assertNotIn("abc", fake.scripts[1])

    def test_no_result_is_an_error(self) -> None:
        proj = self.dir / "p.o3proj"
        proj.write_text("", encoding="utf-8")

        class Silent:
            def run(self, script: str) -> ScriptOutcome:
                return ScriptOutcome(False, "no project was read", ())

        with self.assertRaisesRegex(TbError, "no project was read"):
            run_project_testbenches(proj, runner=Silent())
        with self.assertRaises(TbError):
            run_project_testbenches(self.dir / "missing.o3proj", runner=Silent())

    def test_file_run_writes_project_and_captures_output(self) -> None:
        one = {"testbenches": [RESULT["testbenches"][0]], "passed": 1, "failed": 0, "errors": 0}
        fake = FakeRunner(one, output="0 1 2\n")
        spec = TbSpec(self.dir / "t.v", [self.dir / "d.v"], dut_top="d", max_time=7, on="netlist")
        r = run_testbench_file(spec, runner=fake)
        self.assertTrue(r.ok)
        self.assertEqual(r.output, "0 1 2\n")
        self.assertIn("sim_tb --out", fake.scripts[1])
        self.assertIn("abc --lut 6", fake.scripts[1])

    def test_file_needs_dut(self) -> None:
        with self.assertRaises(TbError):
            run_testbench_file(TbSpec(self.dir / "t.v", []), runner=FakeRunner())

    def test_bad_path(self) -> None:
        with self.assertRaises(TbError):
            run_project_testbenches(self.dir / "a b.o3proj", runner=FakeRunner())


class ConvertTest(unittest.TestCase):
    def tb(self) -> str:
        return vectors_to_testbench("cnt", PORTS, OUTS, vector_file(), HEADER)

    def test_testbench_text(self) -> None:
        text = self.tb()
        self.assertIn("module wyrd_tb;", text)
        self.assertIn("cnt u_dut(.clk(clk), .rst(rst), .d(d), .q(q), .v(v));", text)
        self.assertIn(
            "rst = 1'b1; d = 4'b0101; #5 clk = 1; #1 $display(\"0 10101 %b%b\", q, v);", text
        )
        self.assertTrue(text.startswith("// wyrd-vectors-header: " + HEADER))
        self.assertEqual(text.count("$display"), 3)
        self.assertIn("$finish;", text)

    def test_combinational_has_no_clock(self) -> None:
        ports = (Signal("a", 2, "input"),)
        text = vectors_to_testbench("m", ports, OUTS[:1], VectorFile(((3,),)), HEADER)
        self.assertNotIn("clk", text)
        self.assertIn("a = 2'b11; #10 $display", text)

    def test_no_data_input(self) -> None:
        ports = (Signal("clk", 1, "clock"),)
        text = vectors_to_testbench("m", ports, OUTS, VectorFile(((), ())), HEADER)
        self.assertIn('$display("0 - %b%b"', text)

    def test_wide_port_refused(self) -> None:
        wide = (Signal("w", 65, "input"),)
        with self.assertRaises(ConvertError):
            vectors_to_testbench("m", wide, (), VectorFile(((0,),)), HEADER)

    def test_output_to_vectors(self) -> None:
        printed = "0 10101 00001\n1 00000 00000\n2 00000 00000\n"
        text = testbench_to_vectors(printed, PORTS, OUTS, HEADER)
        self.assertEqual(text.splitlines()[0], HEADER)
        self.assertIn("# clock clk 0", text)
        self.assertTrue(text.endswith("2 00000 00000\n"))

    def test_output_noise_is_skipped(self) -> None:
        printed = "hello\n0 10101 00001\n$finish called\n1 00000 00000\n"
        text = testbench_to_vectors(printed, PORTS, OUTS, HEADER)
        self.assertEqual(sum(1 for line in text.splitlines() if not line.startswith("#")), 2)

    def test_foreign_output(self) -> None:
        with self.assertRaisesRegex(ConvertError, "no vector lines"):
            testbench_to_vectors("0 1 0\n1 2 0\n", PORTS, OUTS, HEADER)

    def test_pure_round_trip(self) -> None:
        from wyrd.bifrost import parse_vectors

        printed = "".join(f"{c} {r[0]}{r[1]:04b} {c:05b}\n" for c, r in enumerate(ROWS))
        vec = testbench_to_vectors(printed, PORTS, OUTS, HEADER)
        vf = parse_vectors(vec, PORTS, OUTS)
        self.assertEqual(vf.rows, tuple(ROWS))
        self.assertEqual(self.tb(), vectors_to_testbench("cnt", PORTS, OUTS, vf, HEADER))

    def test_detect_top(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.v"
            f.write_text(
                "// module fake\nmodule leaf(input a); endmodule\n"
                "module top(input a);\n  leaf u(.a(a));\nendmodule\n",
                encoding="utf-8",
            )
            self.assertEqual(detect_top([f]), "top")
            f.write_text("module a(); endmodule\nmodule b(); endmodule\n", encoding="utf-8")
            with self.assertRaises(ConvertError):
                detect_top([f])


class CliTest(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_project_run_exit_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "p.o3proj"
            proj.write_text("", encoding="utf-8")
            res = Path(tmp) / "r.json"
            with mock.patch("wyrd.bifrost.testbench.default_runner", return_value=FakeRunner()):
                code, out, _ = self.run_cli("tb", "run", "--project", str(proj), "--json", str(res))
            self.assertEqual(code, 1)
            self.assertIn("b fail both 1 ms", out)
            self.assertIn('mismatch: expect line 2 time 1 field 1: want "1 9" got "1 5"', out)
            self.assertIn("c timeout rtl", out)
            self.assertIn("tb run: 1 passed, 1 failed, 1 errors, 1 timeouts", out)
            self.assertEqual(len(json.loads(res.read_text())["testbenches"]), 4)

    def test_usage_errors(self) -> None:
        self.assertEqual(self.run_cli("tb", "run")[0], 2)
        code, _, err = self.run_cli("tb", "run", "--tb", "x.v")
        self.assertEqual((code, "--dut" in err), (2, True))
        code, _, err = self.run_cli("tb", "convert", "--to", "tb", "--dut", "a.v")
        self.assertEqual((code, "--vectors" in err), (2, True))

    def test_missing_project(self) -> None:
        with mock.patch("wyrd.bifrost.testbench.default_runner", return_value=FakeRunner()):
            code, _, err = self.run_cli("tb", "run", "--project", "/nonexistent/p.o3proj")
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)


if __name__ == "__main__":
    unittest.main()
