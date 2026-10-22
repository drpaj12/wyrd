import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fakes_sim import TRACE_IN, traffic_session
from wyrd.bifrost.errors import NoSuchSignal
from wyrd.bifrost.record import Recording
from wyrd.bifrost.session import BifrostSession
from wyrd.bifrost.vcd import vcd_text, write_vcd

EXPECTED_VCD = """\
$version wyrd sim $end
$timescale 1ns $end
$scope module top $end
$var wire 1 ! clk $end
$var wire 1 " a $end
$var wire 2 # y [1:0] $end
$upscope $end
$enddefinitions $end
#0
$dumpvars
0!
0"
b00 #
$end
#2
1"
#5
1!
b11 #
#10
0!
"""


def run_rows(s: BifrostSession, count: int) -> None:
    for rst, car_ns, car_ew in TRACE_IN[:count]:
        s.set_many({"rst": rst, "car_ns": car_ns, "car_ew": car_ew})
        s.step()


class RecordingTest(unittest.TestCase):
    def test_recording_defaults(self) -> None:
        s = traffic_session()
        rec = s.start_recording()
        self.assertEqual(rec.names, ("rst", "car_ns", "car_ew", "light_ns", "light_ew"))
        self.assertEqual(rec.widths, (1, 1, 1, 2, 2))
        self.assertEqual(rec.clocks, ("clk",))
        self.assertEqual(rec.inputs, ("rst", "car_ns", "car_ew"))
        self.assertEqual(rec.cycles, (0,))
        self.assertEqual(rec.samples, ((0, 0, 0, 2, 0),))
        run_rows(s, 3)
        live = s.recording
        assert live is not None
        self.assertEqual(live.cycles, (0, 1, 2, 3))
        self.assertEqual(live.samples[1:], ((1, 0, 0, 2, 0), (0, 0, 1, 1, 0), (0, 0, 0, 1, 0)))

    def test_internal_names(self) -> None:
        s = traffic_session()
        rec = s.start_recording(["state", "timer"])
        self.assertEqual((rec.names, rec.widths), (("state", "timer"), (2, 3)))
        self.assertEqual(rec.inputs, ())
        s2 = traffic_session()
        with self.assertRaises(NoSuchSignal):
            s2.start_recording(["nope"])
        self.assertIsNone(s2.recording)

    def test_step_many_records_each_cycle(self) -> None:
        s = traffic_session()
        s.start_recording()
        s.step(3)
        rec = s.recording
        assert rec is not None
        self.assertEqual(rec.cycles, (0, 1, 2, 3))

    def test_reset_restarts(self) -> None:
        s = traffic_session()
        s.start_recording()
        s.step(4)
        s.reset()
        rec = s.recording
        assert rec is not None
        self.assertEqual(rec.cycles, (0,))

    def test_max_samples(self) -> None:
        s = traffic_session()
        s.start_recording(max_samples=3)
        s.step(5)
        rec = s.recording
        assert rec is not None
        self.assertEqual(len(rec.samples), 3)
        self.assertTrue(s.recording_full)
        self.assertEqual(s.cycle, 5)

    def test_stop_recording(self) -> None:
        s = traffic_session()
        s.start_recording()
        s.step(2)
        rec = s.stop_recording()
        assert rec is not None
        self.assertEqual(rec.cycles, (0, 1, 2))
        self.assertIsNone(s.recording)
        self.assertFalse(s.recording_full)
        self.assertIsNone(s.stop_recording())


class VcdTest(unittest.TestCase):
    def test_vcd_text_exact(self) -> None:
        rec = Recording(("a", "y"), (1, 2), (0, 1), ((0, 0), (1, 3)), ("clk",), inputs=("a",))
        self.assertEqual(vcd_text(rec), EXPECTED_VCD)

    def test_vcd_scopes(self) -> None:
        rec = Recording(("u0.q", "y"), (1, 1), (0,), ((0, 0),), ())
        lines = vcd_text(rec).splitlines()
        head = lines.index("$scope module top $end")
        tail = lines.index("$enddefinitions $end")
        self.assertEqual(
            lines[head + 1 : tail],
            [
                '$var wire 1 " y $end',
                "$scope module u0 $end",
                "$var wire 1 ! q $end",
                "$upscope $end",
                "$upscope $end",
            ],
        )

    def test_vcd_codes_and_names(self) -> None:
        names = tuple(f"n{i}" for i in range(94)) + ("bad name",)
        rec = Recording(names, (1,) * 95, (0,), ((0,) * 95,), ())
        lines = vcd_text(rec).splitlines()
        self.assertIn('$var wire 1 !" bad_name $end', lines)
        self.assertIn("$var wire 1 ~ n93 $end", lines)

    def test_vcd_unchanged_not_repeated(self) -> None:
        rec = Recording(("a", "y"), (1, 1), (0, 1), ((0, 1), (0, 1)), ("clk",), inputs=("a",))
        text = vcd_text(rec)
        self.assertNotIn("#2\n", text)
        self.assertIn("#5\n1!\n#10\n0!\n", text)
        self.assertEqual(text.count("0\""), 1)

    def test_vcd_empty(self) -> None:
        text = vcd_text(Recording((), (), (), (), ()))
        self.assertTrue(text.endswith("#0\n$dumpvars\n$end\n"))

    def test_write_vcd_atomic(self) -> None:
        rec = Recording(("a", "y"), (1, 2), (0, 1), ((0, 0), (1, 3)), ("clk",), inputs=("a",))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.vcd"
            write_vcd(rec, path)
            self.assertEqual(path.read_text(encoding="utf-8"), vcd_text(rec))
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["out.vcd"])

    def test_write_vcd_failure_removes_tmp(self) -> None:
        rec = Recording(("a",), (1,), (0,), ((0,),), ())
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.vcd"
            patched = mock.patch("wyrd.bifrost.vcd.os.replace", side_effect=OSError("boom"))
            with patched, self.assertRaises(OSError):
                write_vcd(rec, path)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_vcd_brackets_cleaned(self) -> None:
        rec = Recording(("u[3].q[0]",), (1,), (0,), ((0,),), ())
        text = vcd_text(rec)
        self.assertIn("$scope module u_3_ $end", text)
        self.assertIn("$var wire 1 ! q_0_ $end", text)


class RecordingNamesTest(unittest.TestCase):
    def test_clock_names_dropped(self) -> None:
        s = traffic_session()
        rec = s.start_recording(["clk", "car_ns", "light_ns"])
        self.assertEqual(rec.names, ("car_ns", "light_ns"))
        self.assertEqual(rec.clocks, ("clk",))


if __name__ == "__main__":
    unittest.main()
