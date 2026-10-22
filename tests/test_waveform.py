import unittest

from wyrd.bifrost.record import Recording
from wyrd.guimodel.waveform import (
    MAX_VIEW_SAMPLES,
    Segment,
    WaveRow,
    format_value,
    parse_int_text,
    rows_from_recording,
    segments,
    view_start,
    visible_range,
)


class WaveformTest(unittest.TestCase):
    def test_segments(self) -> None:
        self.assertEqual(
            segments([0, 0, 1, 1, 1, 0]), [Segment(0, 2, 0), Segment(2, 5, 1), Segment(5, 6, 0)]
        )
        self.assertEqual(segments([]), [])
        self.assertEqual(segments([7]), [Segment(0, 1, 7)])

    def test_rows_from_recording(self) -> None:
        rec = Recording(
            names=("a", "y"),
            widths=(1, 2),
            cycles=(0, 1),
            samples=((0, 0), (1, 3)),
            clocks=("clk",),
        )
        self.assertEqual(
            rows_from_recording(rec), [WaveRow("a", 1, (0, 1)), WaveRow("y", 2, (0, 3))]
        )

    def test_rows_from_recording_window(self) -> None:
        rec = Recording(
            names=("a",),
            widths=(1,),
            cycles=(0, 1, 2, 3),
            samples=((0,), (1,), (0,), (1,)),
            clocks=(),
        )
        self.assertEqual(rows_from_recording(rec, 2), [WaveRow("a", 1, (0, 1))])

    def test_view_start(self) -> None:
        self.assertEqual(view_start(10), 0)
        self.assertEqual(view_start(MAX_VIEW_SAMPLES), 0)
        self.assertEqual(view_start(MAX_VIEW_SAMPLES + 5), 5)
        self.assertEqual(view_start(350_001), 250_001)
        self.assertEqual(view_start(10, 4), 6)

    def test_visible_range(self) -> None:
        # 160 px of names, 10 px cells, samples 0..99 shown
        self.assertEqual(visible_range(0, 400, 160, 10, 0, 100), (0, 25))
        self.assertEqual(visible_range(165, 185, 160, 10, 0, 100), (0, 3))
        self.assertEqual(visible_range(1000, 5000, 160, 10, 0, 100), (84, 100))
        self.assertEqual(visible_range(5000, 6000, 160, 10, 0, 100), (100, 100))
        # a window that starts at sample 250000
        self.assertEqual(visible_range(160, 199, 160, 10, 250_000, 350_000), (250_000, 250_004))
        self.assertEqual(visible_range(0, 100, 160, 10, 250_000, 350_000), (250_000, 250_000))

    def test_format_value(self) -> None:
        self.assertEqual(format_value(5, 4, "bin"), "0101")
        self.assertEqual(format_value(10, 4, "hex"), "a")
        self.assertEqual(format_value(0x1F, 9, "hex"), "01f")
        self.assertEqual(format_value(300, 70, "dec"), "300")

    def test_parse_int_text(self) -> None:
        self.assertEqual(parse_int_text("17", 8), 17)
        self.assertEqual(parse_int_text("0x1f", 8), 31)
        self.assertEqual(parse_int_text("0b101", 8), 5)
        self.assertEqual(parse_int_text("1_000", 10), 1000)
        for bad in ("256", "-1", "abc", ""):
            with self.assertRaises(ValueError, msg=bad):
                parse_int_text(bad, 8)


if __name__ == "__main__":
    unittest.main()
