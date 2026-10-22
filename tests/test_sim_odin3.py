"""Bifrost against a real Odin III with the S1 simulation API (skipped when it is absent)."""

import tempfile
import time
import unittest
from pathlib import Path

from tests.fakes_sim import TRACE_IN, TRACE_OUT
from wyrd.bifrost import (
    BifrostSession,
    CompileError,
    odin3_available,
    vcd_text,
)

TRAFFIC = Path(__file__).parent / "data" / "sim" / "traffic.v"
OUT_NAMES = ["light_ns", "light_ew", "state", "timer"]


@unittest.skipUnless(odin3_available(), "odin3 with the simulation API is not installed")
class RealOdin3Test(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return path

    def traffic(self) -> BifrostSession:
        session = BifrostSession.from_verilog([TRAFFIC])
        self.addCleanup(session.close)
        return session

    def test_reference_trace(self) -> None:
        s = self.traffic()
        for ins, outs in zip(TRACE_IN, TRACE_OUT, strict=True):
            s.set_many(dict(zip(["rst", "car_ns", "car_ew"], ins, strict=True)))
            s.step()
            self.assertEqual(tuple(s.get_many(OUT_NAMES).values()), outs)

    def test_signal_kinds(self) -> None:
        s = self.traffic()
        self.assertEqual(s.signal("clk").kind, "clock")
        self.assertEqual(s.signal("rst").kind, "input")
        self.assertEqual((s.signal("light_ns").kind, s.signal("light_ns").width), ("output", 2))
        self.assertTrue(s.has_signal("state") and s.has_signal("timer"))

    def test_compile_error_location(self) -> None:
        path = self.write("m.v", "module m(input a, output y);\n assign y = a +;\nendmodule\n")
        with self.assertRaises(CompileError) as cm:
            BifrostSession.from_verilog([path])
        d = cm.exception.diagnostics[0]
        self.assertEqual(d.line, 2)
        self.assertIsNotNone(d.col)
        self.assertTrue((d.file or "").endswith(".v"))

    def test_warning_kept(self) -> None:
        path = self.write("w.v", "module m(input a, output y);\n assign y = b;\nendmodule\n")
        with BifrostSession.from_verilog([path]) as s:
            self.assertTrue(
                any(d.severity == "warning" and "'b'" in d.message for d in s.diagnostics)
            )

    def test_two_files_error_in_second(self) -> None:
        good = self.write("a.v", "module sub(input a, output y);\n assign y = a;\nendmodule\n")
        bad = self.write("b b.v", "module top(input a, output y);\n assign y = a +;\nendmodule\n")
        with self.assertRaises(CompileError) as cm:
            BifrostSession.from_verilog([good, bad])
        self.assertTrue((cm.exception.diagnostics[0].file or "").endswith("b b.v"))

    def test_combinational_design(self) -> None:
        src = "module c(input [3:0] a, output [3:0] y);\n assign y = ~a;\nendmodule\n"
        path = self.write("c.v", src)
        with BifrostSession.from_verilog([path]) as s:
            s.set("a", 5)
            s.step()
            self.assertEqual(s.get("y"), 10)
            self.assertEqual(s.clocks, ())

    def test_missing_port_message(self) -> None:
        src = (
            "module m(input a, output y);\n output [29:0] debug_port;\n"
            " assign y = a;\nendmodule\n"
        )
        path = self.write("p.v", src)
        with self.assertRaises(CompileError) as cm:
            BifrostSession.from_verilog([path])
        self.assertIn(
            "'debug_port' is declared as a port but is not in the port list", str(cm.exception)
        )

    def test_speed(self) -> None:
        s = self.traffic()
        start = time.perf_counter()
        for _ in range(600):
            s.set("car_ns", 1)
            s.set("car_ew", 1)
            s.step()
            s.get("light_ns")
            s.get("light_ew")
        self.assertLess(time.perf_counter() - start, 10.0)

    def test_sessions_independent(self) -> None:
        a, b = self.traffic(), self.traffic()
        a.step(3)
        self.assertEqual((a.cycle, b.cycle), (3, 0))

    def test_recording_and_vcd_text(self) -> None:
        s = self.traffic()
        s.start_recording()
        for ins in TRACE_IN[:3]:
            s.set_many(dict(zip(["rst", "car_ns", "car_ew"], ins, strict=True)))
            s.step()
        rec = s.stop_recording()
        assert rec is not None
        text = vcd_text(rec)
        self.assertIn("$var wire 2", text)
        self.assertIn("light_ns", text)


if __name__ == "__main__":
    unittest.main()
