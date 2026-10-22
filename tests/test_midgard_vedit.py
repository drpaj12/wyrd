import tempfile
import unittest
from pathlib import Path

from tests.fakes_midgard import FakeLightBackend
from wyrd.midgard.model.vedit import (
    BAD_VECTOR,
    NOT_COMPILED,
    SAVE_OK,
    EditorSession,
    animation_image_names,
    load_template,
)

GOOD = "module light1;"
ZERO30 = "0" * 30


class VeditBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.backend = FakeLightBackend()

    def session(self, text: str | None = GOOD) -> tuple[EditorSession, Path]:
        path = self.tmp / "a.v"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        s = EditorSession(path, self.backend)
        self.addCleanup(s.close)
        return s, path


class VeditTest(VeditBase):
    def test_templates(self) -> None:
        combo = load_template("combinational")
        self.assertIn("always @(*)", combo)
        self.assertIn("general_sensors, debug_port);", combo)
        self.assertIn("posedge clk", load_template("sequential"))
        with self.assertRaises(ValueError):
            load_template("x")

    def test_save_and_dirty(self) -> None:
        s, path = self.session(None)
        self.assertEqual(s.text, load_template("combinational"))
        self.assertFalse(s.dirty)
        s.set_text("abc")
        self.assertTrue(s.dirty)
        self.assertTrue(s.should_prompt_on_exit())
        self.assertEqual(s.save(), SAVE_OK)
        self.assertEqual(SAVE_OK, "Saving complete.")
        self.assertEqual(path.read_text(encoding="utf-8"), "abc\n")
        self.assertFalse(s.dirty)
        self.assertFalse(s.should_prompt_on_exit())

    def test_save_error_returns_text(self) -> None:
        path = self.tmp / "nodir" / "a.v"
        s = EditorSession(path, self.backend)
        self.addCleanup(s.close)
        self.assertIn("nodir", s.save())
        self.assertTrue(s.text)

    def test_verify_ok_and_error(self) -> None:
        s, path = self.session()
        res = s.verify()
        self.assertTrue(res.ok)
        self.assertEqual(list(res.messages), [f"Compiling {path}", "Compile successful"])
        s.set_text("SYNTAX_ERROR")
        bad = s.verify()
        self.assertFalse(bad.ok)
        self.assertEqual(bad.messages[1], "Error at line 2:5: syntax: unexpected X")
        self.assertEqual(s.simulate("00000000", ZERO30), (None, NOT_COMPILED))

    def test_verify_port_error_has_no_position(self) -> None:
        s, _ = self.session("BAD_WIDTH")
        res = s.verify()
        self.assertFalse(res.ok)
        self.assertTrue(res.messages[1].startswith("Error: port 'sensor_light'"))

    def test_simulate_rules(self) -> None:
        s, _ = self.session()
        self.assertEqual(s.simulate("00000000", ZERO30), (None, NOT_COMPILED))
        s.verify()
        handle = self.backend.live()[-1]
        self.assertEqual(s.simulate("0100", ZERO30), (None, BAD_VECTOR))
        self.assertEqual(s.simulate("01000000", "0" * 29), (None, BAD_VECTOR))
        self.assertEqual(s.simulate("0100000x", ZERO30), (None, BAD_VECTOR))
        before = len(handle.log)
        res, msg = s.simulate("01000000", ZERO30)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.out, (4, 0, 0, 0))
        self.assertEqual(res.clock_cycle, 1)
        self.assertTrue(res.text.startswith("Simulation Cycle\nClock Cycle:1 "))
        self.assertIn("OutN Val = 4", res.text)
        self.assertTrue(res.text.endswith("DebugVector = " + ZERO30))
        self.assertEqual(msg, res.text)
        self.assertEqual(len(handle.log) - before, 1)
        res2, _ = s.simulate("01000000", ZERO30)
        assert res2 is not None
        self.assertIn("Clock Cycle:2 ", res2.text)
        self.assertEqual(len(handle.log) - before, 2)
        res3, _ = s.simulate("00000000", ZERO30)
        assert res3 is not None
        self.assertEqual(res3.out, (4, 4, 4, 4))

    def test_reset_restarts_cycle(self) -> None:
        s, _ = self.session()
        s.verify()
        first, _ = s.simulate("00000000", ZERO30)
        s.simulate("00000000", ZERO30)
        s.simulate("00000000", ZERO30)
        self.assertIn("Compile successful", s.reset())
        again, _ = s.simulate("00000000", ZERO30)
        assert first is not None and again is not None
        self.assertEqual(first.clock_cycle, again.clock_cycle)

    def test_reverify_closes_old_controller(self) -> None:
        s, _ = self.session()
        s.verify()
        s.verify()
        self.assertEqual(len(self.backend.live()), 1)
        s.close()
        self.assertEqual(self.backend.live(), [])

    def test_animation_names(self) -> None:
        self.assertEqual(
            animation_image_names((4, 0, 2, 3)), ("go_n", "stop_s", "left_e", "right_w")
        )
        self.assertEqual(
            animation_image_names((1, 5, 0, 0)), ("forward_n", "stop_s", "stop_e", "stop_w")
        )


if __name__ == "__main__":
    unittest.main()
