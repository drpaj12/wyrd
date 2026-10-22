import unittest

from wyrd.bifrost.record import Recording
from wyrd.guimodel.waveform import (
    Segment,
    WaveRow,
    format_value,
    parse_int_text,
    rows_from_recording,
    segments,
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
