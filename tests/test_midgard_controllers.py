import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.fakes_midgard import FakeLightBackend
from tests.test_midgard_level import make_level, run_until_done
from wyrd.bifrost import BifrostSession, SimUnavailable
from wyrd.midgard.model.controllers import (
    ControllerError,
    MidgardController,
    ScriptedController,
    build_controllers,
    check_ports,
    safe_controller,
)

GOOD = "module light1;"


class ControllerBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.backend = FakeLightBackend()

    def write(self, name: str, text: str = GOOD) -> Path:
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def controller(self, text: str = GOOD, name: str = "light0") -> MidgardController:
        f = self.write("a.v", text)
        session = BifrostSession.from_verilog([f], backend=self.backend)
        self.addCleanup(session.close)
        return MidgardController(session, name)


class ControllerTest(ControllerBase):
    def test_start_sequence(self) -> None:
        ctl = self.controller()
        ctl.start()
        h = self.backend.handles[0]
        self.assertEqual(h.log, [(0, 0, 0)])
        self.assertEqual(ctl.step(0b01000000, 5), (4, 0, 0, 0))
        self.assertEqual(h.log[-1], (1, 64, 5))
        self.assertEqual(ctl.step(0, 0), (4, 4, 4, 4))

    def test_sets_only_changes(self) -> None:
        ctl = self.controller()
        ctl.start()
        ctl.step(64, 5)
        ctl.step(64, 5)
        calls = self.backend.handles[0].set_calls
        self.assertEqual([c for c in calls if c[0] == "rst"], [("rst", 1)])
        self.assertEqual(calls.count(("sensor_light", 64)), 1)
        self.assertEqual(calls.count(("general_sensors", 5)), 1)
        n = len(calls)
        ctl.step(64, 5)
        self.assertEqual(len(calls), n)

    def test_last_values_and_recording(self) -> None:
        ctl = self.controller()
        ctl.start()
        self.assertIsNone(ctl.last_inputs)
        self.assertIsNone(ctl.last_outputs)
        ctl.step(64, 5)
        self.assertEqual(ctl.last_inputs, (64, 5))
        self.assertEqual(ctl.last_outputs, (4, 0, 0, 0))
        self.assertIsNone(ctl.recording())
        with self.assertRaises(ControllerError):
            ctl.export_vcd(self.tmp / "none.vcd")
        ctl.start_recording()
        for _ in range(5):
            ctl.step(64, 5)
        rec = ctl.recording()
        assert rec is not None
        self.assertEqual(len(rec.samples), 6)
        out = self.tmp / "a.vcd"
        ctl.export_vcd(out)
        self.assertIn("sensor_light", out.read_text(encoding="utf-8"))
        self.assertEqual(ctl.read_debug(), 0)

    def test_runtime_error(self) -> None:
        ctl = self.controller("RUNTIME_ERROR", "light7")
        ctl.start()
        with self.assertRaises(ControllerError) as cm:
            ctl.step(0, 0)
        self.assertTrue(str(cm.exception).startswith("runtime error in light7"))

    def test_output_codes_above_four(self) -> None:
        ctl = self.controller("CODE5", "L")
        ctl.start()
        self.assertEqual(ctl.step(0, 0)[0], 5)
        ctl.step(0, 0)
        self.assertEqual(ctl.warnings, ["L: output code 5 treated as STOP"])


class PortsTest(ControllerBase):
    def ports(self, text: str) -> list[str]:
        f = self.write("p.v", text)
        session = BifrostSession.from_verilog([f], backend=self.backend)
        self.addCleanup(session.close)
        return check_ports(session)

    def test_check_ports(self) -> None:
        self.assertEqual(self.ports("MISSING_OUTW"), ["port 'outW' is missing"])
        self.assertEqual(
            self.ports("BAD_WIDTH"),
            ["port 'sensor_light' must be an input of width 8, found input of width 4"],
        )
        self.assertEqual(self.ports(GOOD), [])


class BuildTest(ControllerBase):
    def test_build_controllers(self) -> None:
        good = self.write("g.v")
        bad1 = self.write("b1.v", "SYNTAX_ERROR")
        bad2 = self.write("b2.v", "MISSING_OUTW")
        gone = self.tmp / "gone.v"
        result = build_controllers([good, bad1, bad2, gone], self.backend)
        self.assertFalse(result.ok)
        self.assertIsInstance(result.controllers[0], MidgardController)
        self.assertEqual(result.controllers[1:], [None, None, None])
        got = [(e.index, e.line, e.col, e.message) for e in result.errors]
        self.assertEqual(
            got,
            [
                (1, 2, 5, "syntax: unexpected X"),
                (2, None, None, "port 'outW' is missing"),
                (3, None, None, "cannot read file"),
            ],
        )
        self.assertEqual(str(result.errors[0]), f"{bad1.name}:2:5: syntax: unexpected X")
        self.assertEqual(str(result.errors[1]), f"{bad2.name}: port 'outW' is missing")
        self.assertEqual(self.backend.open_handles, 1)

    def test_all_good(self) -> None:
        files = [self.write(f"g{k}.v") for k in range(3)]
        result = build_controllers(files, self.backend)
        self.assertTrue(result.ok)
        self.assertEqual(result.errors, [])
        for c in result.controllers:
            assert c is not None
            c.close()
        self.assertEqual(self.backend.open_handles, 0)

    def test_unavailable(self) -> None:
        f = self.write("g.v")
        with patch(
            "wyrd.midgard.model.controllers.default_backend",
            side_effect=SimUnavailable("no odin3"),
        ), self.assertRaises(SimUnavailable):
            build_controllers([f])

    def test_level_through_bifrost_equals_scripted(self) -> None:
        files = [self.write(f"g{k}.v") for k in range(2)]
        result = build_controllers(files, self.backend)
        real = make_level(1)
        real.start([c for c in result.controllers if c is not None])
        ref = make_level(1)
        ref.start([ScriptedController(safe_controller) for _ in ref.town.controls])
        self.assertGreater(run_until_done(real), 0)
        self.assertGreater(run_until_done(ref), 0)
        self.assertEqual(real.result(), ref.result())
        self.assertEqual(real.ticks, ref.ticks)


if __name__ == "__main__":
    unittest.main()
