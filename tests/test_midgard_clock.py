import unittest

from wyrd.midgard.model.clock import (
    MAX_BACKLOG,
    SPEEDS,
    TICKS_PER_SECOND,
    TickClock,
    ticks_to_seconds,
)


class TickClockTest(unittest.TestCase):
    def test_constants(self) -> None:
        self.assertEqual((TICKS_PER_SECOND, MAX_BACKLOG, SPEEDS), (60, 30, (1, 2, 4)))
        self.assertEqual(ticks_to_seconds(337), 5)

    def test_tick_clock(self) -> None:
        clock = TickClock()
        counts = [clock.advance(1 / 60) for _ in range(60)]
        self.assertEqual(sum(counts), 60)
        self.assertTrue(all(c in (0, 1) for c in counts))
        clock = TickClock()
        self.assertEqual(clock.advance(1.0), 30)
        self.assertEqual(clock.acc, 0.0)
        self.assertEqual(TickClock().advance(0.5, 2), 30)
        self.assertEqual(TickClock().advance(0.25, 4), 30)
        self.assertEqual(TickClock(max_backlog=10**6).advance(0.25, 4), 60)

    def test_speeds(self) -> None:
        for speed in SPEEDS:
            clock = TickClock()
            total = sum(clock.advance(0.01, speed) for _ in range(100))
            self.assertLessEqual(abs(total - 60 * speed), 1)

    def test_errors(self) -> None:
        with self.assertRaises(ValueError):
            TickClock().advance(-0.1)
        with self.assertRaises(ValueError):
            TickClock().advance(0.1, 3)

    def test_fractional_dt(self) -> None:
        clock = TickClock()
        self.assertEqual([clock.advance(1 / 64) for _ in range(4)], [0, 1, 1, 1])

    def test_reset(self) -> None:
        clock = TickClock()
        clock.advance(0.01)
        clock.reset()
        self.assertEqual(clock.acc, 0.0)


if __name__ == "__main__":
    unittest.main()
