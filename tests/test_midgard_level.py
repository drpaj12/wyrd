import dataclasses
import random
import unittest
from collections.abc import Callable

from wyrd.midgard.model.clock import TickClock
from wyrd.midgard.model.controllers import ScriptedController, safe_controller
from wyrd.midgard.model.level import Level, LevelResult, Phase
from wyrd.midgard.model.levelxml import CarSpec, level_path, parse_level_file
from wyrd.midgard.model.sensors import SensorSet

CARS = [18, 10, 20, 34, 30, 16, 26, 19, 30, 34, 40, 40, 25]
INTERS = [1, 2, 3, 1, 1, 4, 9, 4, 4, 4, 6, 4, 11]
Fn = Callable[[int, int], tuple[int, int, int, int]]


def go_all(light: int, general: int) -> tuple[int, int, int, int]:
    return (4, 4, 4, 4)


def stop_all(light: int, general: int) -> tuple[int, int, int, int]:
    return (0, 0, 0, 0)


def make_level(n: int, cars: tuple[CarSpec, ...] | None = None) -> Level:
    data = parse_level_file(level_path(n))
    if cars is not None:
        data = dataclasses.replace(data, cars=cars)
    return Level(data, SensorSet())


def straight() -> tuple[CarSpec, ...]:
    return (CarSpec((5, 21), (5, 0), 1),)


def scripted(level: Level, fn: Fn) -> list[ScriptedController]:
    return [ScriptedController(fn) for _ in level.town.controls]


def run_until_done(level: Level, limit: int = 20000) -> int:
    n = 0
    while n < limit:
        n += 1
        if level.tick():
            return n
    return -1


class LevelTest(unittest.TestCase):
    def test_phases(self) -> None:
        level = make_level(1)
        self.assertIs(level.phase, Phase.EDIT)
        self.assertFalse(level.tick())
        self.assertEqual(level.ticks, 0)
        level.toggle_pause()
        self.assertIs(level.phase, Phase.EDIT)
        with self.assertRaises(ValueError):
            level.start([ScriptedController(go_all)])
        ctls = scripted(level, go_all)
        level.start(ctls)
        self.assertEqual([c.starts for c in ctls], [1, 1])
        self.assertIs(level.phase, Phase.RUN)
        with self.assertRaises(ValueError):
            level.start(ctls)
        level.toggle_pause()
        self.assertIs(level.phase, Phase.PAUSE)
        self.assertFalse(level.tick())
        self.assertEqual(level.ticks, 0)
        level.toggle_pause()
        self.assertIs(level.phase, Phase.RUN)

    def test_straight_car_result(self) -> None:
        level = make_level(1, straight())
        level.start(scripted(level, go_all))
        self.assertEqual(run_until_done(level), 337)
        self.assertIs(level.phase, Phase.DONE)
        res = level.result()
        expected = LevelResult(passed=1, failed=0, crashed=0, forced=0, ticks=337, cars=1)
        self.assertEqual(res, expected)
        self.assertEqual(res.seconds, 5)

    def test_crash_result(self) -> None:
        level = make_level(1, (CarSpec((5, 21), (5, 0), 1), CarSpec((5, 21), (5, 0), 2)))
        level.start(scripted(level, go_all))
        self.assertEqual(run_until_done(level), 2)
        res = level.result()
        self.assertEqual(res, LevelResult(passed=0, failed=2, crashed=2, forced=0, ticks=2, cars=2))
        self.assertEqual(res.seconds, 0)

    def test_safe_controller_finishes_level1(self) -> None:
        level = make_level(1)
        level.start([ScriptedController(safe_controller) for _ in level.town.controls])
        run_until_done(level)
        self.assertIs(level.phase, Phase.DONE)
        res = level.result()
        self.assertEqual(res.crashed, 0)
        self.assertEqual(res.passed + res.failed, 10)
        # regression value recorded at W4 Task 6
        self.assertEqual((res.passed, res.ticks), (10, 815))

    def test_cut_road_strands_cars_but_level_finishes(self) -> None:
        # Java would recurse forever when no end tile is reachable (spec section 13)
        level = make_level(1)
        level.start([ScriptedController(safe_controller) for _ in level.town.controls])
        for _ in range(40):
            level.tick()
        level.town.grid[5][17].south = None
        self.assertGreater(run_until_done(level), 0)
        self.assertIs(level.phase, Phase.DONE)
        res = level.result()
        self.assertEqual(level.logic.done_count, 10)
        self.assertEqual((res.passed, res.failed, res.forced, res.crashed), (8, 2, 2, 0))
        self.assertEqual(res.passed + res.failed, res.cars)

    def test_level6_safe_controller_gridlocks(self) -> None:
        # Genuine gridlock, not a port bug: the stub holds every entry while a middle tile is
        # busy; intersections 1 and 2 (x 11-16, y 15-16) each hold a car that waits on a queue
        # that waits at the other's entry. The Java LevelLogic has the same rules (W4 fix round).
        level = make_level(6)
        level.start([ScriptedController(safe_controller) for _ in level.town.controls])
        for _ in range(1100):
            level.tick()

        def snapshot() -> tuple[int, list[tuple[int, int]]]:
            return level.logic.done_count, [(c.px, c.py) for c in level.cars if c.running]

        frozen = snapshot()
        for _ in range(400):
            self.assertFalse(level.tick())
        self.assertEqual(snapshot(), frozen)
        self.assertIs(level.phase, Phase.RUN)
        self.assertEqual(len(frozen[1]), 13)
        for index in (1, 2):
            ctl = level.town.controls[index]
            self.assertTrue(any(n.car is not None for n in ctl.internal))
            self.assertTrue(all(s.name == "STOP" for s in ctl.facing.values()))

    def test_step_once(self) -> None:
        level = make_level(1, straight())
        calls = [0]

        def counting(light: int, general: int) -> tuple[int, int, int, int]:
            calls[0] += 1
            return (4, 4, 4, 4)

        self.assertFalse(level.step_once())
        level.start([ScriptedController(counting) for _ in level.town.controls])
        self.assertFalse(level.step_once())
        self.assertEqual(level.ticks, 0)
        level.toggle_pause()
        for _ in range(5):
            level.step_once()
            self.assertIs(level.phase, Phase.PAUSE)
        self.assertEqual(level.ticks, 5)
        self.assertEqual(calls[0], 5 * len(level.town.controls))
        for _ in range(331):
            self.assertFalse(level.step_once())
        self.assertTrue(level.step_once())
        self.assertIs(level.phase, Phase.DONE)
        self.assertEqual(level.ticks, 337)
        self.assertFalse(level.step_once())
        self.assertEqual(level.ticks, 337)

    def test_stop_all_never_finishes(self) -> None:
        level = make_level(1)
        level.start(scripted(level, stop_all))
        for _ in range(3000):
            level.tick()
        self.assertIs(level.phase, Phase.RUN)
        res = level.result()
        self.assertEqual((res.passed, res.crashed), (0, 0))

    def test_all_levels_construct(self) -> None:
        for n in range(13):
            level = make_level(n)
            self.assertEqual(len(level.cars), CARS[n])
            self.assertEqual(len(level.town.controls), INTERS[n])
            self.assertIs(level.phase, Phase.EDIT)

    def test_other_levels_run_safely(self) -> None:
        for n in (3, 5):
            level = make_level(n)
            level.start([ScriptedController(safe_controller) for _ in level.town.controls])
            for _ in range(6000):
                level.tick()
            res = level.result()
            self.assertLessEqual(res.passed + res.failed, res.cars)


Trace = list[tuple[int, int, int, tuple[int, int, int, int]]]


def traced_run(dts: Callable[[], float], speed: int = 1) -> tuple[Trace, LevelResult, int]:
    level = make_level(1)
    trace: Trace = []

    def wrap(light: int, general: int) -> tuple[int, int, int, int]:
        out = safe_controller(light, general)
        trace.append((level.ticks, light, general, out))
        return out

    level.start(scripted(level, wrap))
    clock = TickClock(max_backlog=10**6)
    frames = 0
    while level.phase is not Phase.DONE and frames < 2_000_000:
        frames += 1
        for _ in range(clock.advance(dts(), speed)):
            if level.tick():
                break
    return trace, level.result(), frames


class DeterminismTest(unittest.TestCase):
    def test_ticks_independent_of_frame_rate(self) -> None:
        rng = random.Random(7)
        schedules: list[Callable[[], float]] = [
            lambda: 1 / 60,
            lambda: 1 / 30,
            lambda: 1 / 144,
            lambda: rng.uniform(0.001, 0.2),
        ]
        runs = [traced_run(s) for s in schedules]
        for trace, result, _ in runs[1:]:
            self.assertEqual(trace, runs[0][0])
            self.assertEqual(result, runs[0][1])
        self.assertEqual(runs[0][1].ticks, runs[3][1].ticks)
        self.assertIs(runs[0][1].cars > 0, True)

    def test_speed_does_not_change_outcome(self) -> None:
        runs = [traced_run(lambda: 0.05, speed) for speed in (1, 2, 4)]
        for trace, result, _ in runs[1:]:
            self.assertEqual(trace, runs[0][0])
            self.assertEqual(result, runs[0][1])
        self.assertLess(runs[2][2] * 3, runs[0][2])


if __name__ == "__main__":
    unittest.main()
