import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.fakes_sim import TRACE_IN, TRACE_OUT, FakeBackend, traffic_session
from wyrd.bifrost.errors import (
    CompileError,
    NoSuchSignal,
    SessionClosed,
    SignalKindError,
    ValueRangeError,
)
from wyrd.bifrost.session import BifrostSession

OUT_NAMES = ["light_ns", "light_ew", "state", "timer"]


class SessionTest(unittest.TestCase):
    def test_reference_trace(self) -> None:
        s = traffic_session()
        self.assertEqual((s.get("light_ns"), s.get("light_ew"), s.cycle), (2, 0, 0))
        for ins, outs in zip(TRACE_IN, TRACE_OUT, strict=True):
            s.set_many(dict(zip(["rst", "car_ns", "car_ew"], ins, strict=True)))
            s.step()
            self.assertEqual(tuple(s.get_many(OUT_NAMES).values()), outs)
        self.assertEqual(s.cycle, 10)

    def test_signal_lists(self) -> None:
        s = traffic_session()
        self.assertEqual(
            [(x.name, x.kind, x.width) for x in s.signals],
            [
                ("clk", "clock", 1),
                ("rst", "input", 1),
                ("car_ns", "input", 1),
                ("car_ew", "input", 1),
                ("light_ns", "output", 2),
                ("light_ew", "output", 2),
                ("state", "internal", 2),
                ("timer", "internal", 3),
            ],
        )
        self.assertEqual([x.name for x in s.inputs], ["rst", "car_ns", "car_ew"])
        self.assertEqual([x.name for x in s.outputs], ["light_ns", "light_ew"])
        self.assertEqual([x.name for x in s.clocks], ["clk"])
        self.assertTrue(s.has_signal("state"))
        self.assertFalse(s.has_signal("nope"))

    def test_set_errors(self) -> None:
        s = traffic_session()
        with self.assertRaises(SignalKindError) as cm:
            s.set("clk", 1)
        self.assertEqual(str(cm.exception), "clock 'clk' is stepped, not set")
        for name in ("light_ns", "state"):
            with self.assertRaises(SignalKindError):
                s.set(name, 1)
        for bad in (2, -1):
            with self.assertRaises(ValueRangeError):
                s.set("car_ns", bad)
        with self.assertRaises(NoSuchSignal):
            s.set("nope", 1)
        with self.assertRaises(NoSuchSignal):
            s.get("nope")
        self.assertEqual(s.get("car_ns"), 0)

    def test_set_many_is_atomic(self) -> None:
        s = traffic_session()
        with self.assertRaises(ValueRangeError):
            s.set_many({"car_ns": 1, "car_ew": 5})
        self.assertEqual(s.get("car_ns"), 0)

    def test_step_rules(self) -> None:
        s = traffic_session()
        s.step(0)
        self.assertEqual(s.cycle, 0)
        with self.assertRaises(ValueError):
            s.step(-1)
        s.step(3)
        self.assertEqual(s.cycle, 3)

    def test_reset_is_power_on(self) -> None:
        s = traffic_session()
        s.set("car_ew", 1)
        s.step(3)
        s.reset()
        self.assertEqual((s.cycle, s.get("light_ns"), s.get("car_ew")), (0, 2, 0))

    def test_close(self) -> None:
        backend = FakeBackend()
        s = traffic_session(backend)
        s.close()
        s.close()
        self.assertTrue(s.closed)
        calls = (lambda: s.get("rst"), lambda: s.set("rst", 1), s.step, lambda: s.signal("rst"))
        for call in calls:
            with self.assertRaises(SessionClosed):
                call()
        self.assertEqual(backend.open_handles, 0)
        backend2 = FakeBackend()
        with traffic_session(backend2) as s2:
            self.assertFalse(s2.closed)
        self.assertTrue(s2.closed)
        self.assertEqual(backend2.open_handles, 0)

    def test_from_verilog_errors(self) -> None:
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.v"
            good.write_text("module t", encoding="utf-8")
            bad = Path(tmp) / "bad.v"
            bad.write_text("SYNTAX_ERROR", encoding="utf-8")
            warn = Path(tmp) / "warn.v"
            warn.write_text("WARN_ME", encoding="utf-8")
            with self.assertRaises(ValueError):
                BifrostSession.from_verilog([], backend=backend)
            missing = Path(tmp) / "missing.v"
            with self.assertRaises(CompileError) as cm:
                BifrostSession.from_verilog([missing], backend=backend)
            (d,) = cm.exception.diagnostics
            self.assertEqual((d.file, d.line, d.message), (str(missing), None, "cannot read file"))
            self.assertEqual(backend.compile_calls, [])
            with self.assertRaises(CompileError) as cm:
                BifrostSession.from_verilog([good, bad], backend=backend)
            self.assertEqual(cm.exception.diagnostics[0].line, 2)
            self.assertEqual(backend.open_handles, 0)
            s = BifrostSession.from_verilog([warn], top="traffic", backend=backend)
            self.assertEqual(s.diagnostics[0].severity, "warning")
            self.assertEqual(backend.last_top, "traffic")
            s.close()

    def test_relative_paths_become_absolute(self) -> None:
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "t.v").write_text("module t", encoding="utf-8")
            rel = os.path.relpath(Path(tmp) / "t.v")
            BifrostSession.from_verilog([str(rel)], backend=backend).close()
        self.assertTrue(backend.compile_calls[0][0].is_absolute())

    def test_overhead(self) -> None:
        s = traffic_session()
        start = time.perf_counter()
        for _ in range(600):
            s.set("car_ns", 1)
            s.set("car_ew", 1)
            s.step()
            s.get("light_ns")
            s.get("light_ew")
        self.assertLess(time.perf_counter() - start, 2.0)

    def test_settle_and_closed_step(self) -> None:
        s = traffic_session()
        s.settle()
        self.assertEqual(s.get("state"), 0)
        s.close()
        with self.assertRaises(SessionClosed):
            s.step(1)


if __name__ == "__main__":
    unittest.main()
