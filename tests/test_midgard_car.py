import dataclasses
import unittest
from collections.abc import Callable
from pathlib import Path

from wyrd.bifrost import Recording
from wyrd.midgard.model.car import (
    Car,
    CarState,
    animation_direction_of,
    check_for_crash,
    direction_on_arrival,
)
from wyrd.midgard.model.grid import END_TYPES, Direction, GridType, Node
from wyrd.midgard.model.levelxml import CarSpec, LevelData, level_path, parse_level_file
from wyrd.midgard.model.logic import LevelLogic
from wyrd.midgard.model.sensors import SensorSet
from wyrd.midgard.model.townmap import TownMap

GT = GridType
GO = (4, 4, 4, 4)


class Stub:
    """Minimal LightController stand-in."""

    def __init__(self, fn: Callable[[], tuple[int, int, int, int]]) -> None:
        self.fn = fn
        self.last_inputs: tuple[int, int] | None = None
        self.last_outputs: tuple[int, int, int, int] | None = None

    def start(self) -> None:
        return None

    def step(self, light_sensors: int, general_sensors: int) -> tuple[int, int, int, int]:
        self.last_inputs = (light_sensors, general_sensors)
        self.last_outputs = self.fn()
        return self.last_outputs

    def close(self) -> None:
        return None

    def start_recording(self) -> None:
        return None

    def stop_recording(self) -> None:
        return None

    def recording(self) -> Recording | None:
        return None

    def export_vcd(self, path: Path) -> None:
        raise RuntimeError("stub")


class Rig:
    def __init__(self, cars: list[CarSpec], fn: Callable[[], tuple[int, int, int, int]]) -> None:
        data = parse_level_file(level_path(1))
        self.data = dataclasses.replace(data, cars=tuple(cars))
        self.town = TownMap(self.data)
        self.cars = self.town.make_cars(self.data)
        self.logic = LevelLogic()
        self.sensors = SensorSet()
        self.ctl = [Stub(fn) for _ in self.town.controls]
        self.ticks = 0

    def tick(self) -> bool:
        self.ticks += 1
        return self.logic.update(self.cars, self.town, self.ctl, self.sensors)

    def run(self, limit: int = 5000) -> int:
        while self.ticks < limit:
            if self.tick():
                return self.ticks
        return -1


def straight(delay: int = 1) -> CarSpec:
    return CarSpec((5, 21), (5, 0), delay)


class CarRulesTest(unittest.TestCase):
    def test_direction_rules(self) -> None:
        d = direction_on_arrival
        self.assertIs(d(None, Node(0, 0, GT.START_NEDGE2S)), Direction.S)
        self.assertIs(d(None, Node(0, 0, GT.START_SEDGE2N)), Direction.N)
        self.assertIs(d(None, Node(0, 0, GT.START_EEDGE2W)), Direction.W)
        self.assertIs(d(None, Node(0, 0, GT.START_WEDGE2E)), Direction.E)
        frm = Node(5, 5, GT.STRAIGHT_ROAD_N2N)
        table = {
            GT.CORNER_ROAD_W2S: Direction.S,
            GT.CORNER_ROAD_E2S: Direction.S,
            GT.CORNER_ROAD_N2E: Direction.E,
            GT.CORNER_ROAD_S2E: Direction.E,
            GT.CORNER_ROAD_N2W: Direction.W,
            GT.CORNER_ROAD_S2W: Direction.W,
            GT.CORNER_ROAD_E2N: Direction.N,
            GT.CORNER_ROAD_W2N: Direction.N,
        }
        for kind, expect in table.items():
            self.assertIs(d(frm, Node(9, 9, kind)), expect, kind)
        plain = GT.STRAIGHT_ROAD_E2E
        self.assertIs(d(frm, Node(6, 5, plain)), Direction.E)
        self.assertIs(d(frm, Node(4, 5, plain)), Direction.W)
        self.assertIs(d(frm, Node(5, 6, plain)), Direction.N)
        self.assertIs(d(frm, Node(5, 4, plain)), Direction.S)

    def test_animation_direction_uses_from_type(self) -> None:
        a = animation_direction_of
        to = Node(9, 9, GT.STRAIGHT_ROAD_N2N)
        self.assertIs(a(Node(1, 1, GT.CORNER_ROAD_N2E), to), Direction.E)
        self.assertIs(a(Node(1, 1, GT.CORNER_ROAD_W2N), to), Direction.N)
        self.assertIs(a(None, Node(0, 0, GT.START_NEDGE2S)), Direction.S)
        road = Node(5, 5, GT.STRAIGHT_ROAD_N2N)
        self.assertIs(a(road, Node(5, 6, GT.STRAIGHT_ROAD_N2N)), Direction.N)
        self.assertIs(a(road, Node(4, 5, GT.STRAIGHT_ROAD_N2N)), Direction.W)

    def test_crash_box(self) -> None:
        def pair(bx: int, by: int) -> bool:
            a = Car(Node(0, 0, GT.NON_ROAD), Node(0, 0, GT.NON_ROAD), 1)
            b = Car(Node(0, 0, GT.NON_ROAD), Node(0, 0, GT.NON_ROAD), 1)
            a.px, a.py, b.px, b.py = 100, 100, bx, by
            return check_for_crash(a, b)

        self.assertTrue(pair(110, 100))
        self.assertTrue(pair(144, 100))
        self.assertFalse(pair(145, 100))
        self.assertTrue(pair(140, 140))
        self.assertFalse(pair(164, 100))
        self.assertTrue(pair(100, 100))

    def test_crash_order_quirk(self) -> None:
        cars = []
        for x, y in ((0, 0), (300, 300), (10, 0), (310, 300)):
            n = Node(0, 0, GT.NON_ROAD)
            c = Car(n, n, 1)
            c.started = True
            c.px, c.py = x, y
            cars.append(c)
        logic = LevelLogic()
        logic.check_crashes(cars)
        self.assertEqual((logic.crash_count, logic.done_count), (2, 2))
        self.assertEqual([c.running for c in cars], [False, True, False, True])
        logic.check_crashes(cars)
        self.assertEqual(logic.crash_count, 4)
        self.assertTrue(all(c.crashed for c in cars))

    def test_crash_clears_node(self) -> None:
        n = Node(1, 1, GT.STRAIGHT_ROAD_N2N)
        c = Car(n, n, 1)
        c.current = n
        n.car = c
        c.crash()
        self.assertIsNone(n.car)
        self.assertIsNone(c.current)
        self.assertTrue(c.crashed and c.done)

    def test_animate(self) -> None:
        n = Node(1, 1, GT.NON_ROAD)
        c = Car(n, n, 1)
        c.animation_direction = Direction.N
        c.animate()
        self.assertEqual((c.px, c.py), (0, 0))
        c.state = CarState.MOVING
        for direction, expect in (
            (Direction.N, (0, 4)),
            (Direction.S, (0, 0)),
            (Direction.E, (4, 0)),
            (Direction.W, (0, 0)),
        ):
            c.animation_direction = direction
            c.animate()
            self.assertEqual((c.px, c.py), expect)
        self.assertTrue(c.at_next_grid())


class TickTest(unittest.TestCase):
    def test_single_car_straight(self) -> None:
        rig = Rig([straight()], lambda: GO)
        for _ in range(17):
            rig.tick()
        self.assertIs(rig.cars[0].current, rig.town.grid[5][20])
        self.assertEqual((rig.cars[0].px, rig.cars[0].py), (4 * 64, 19 * 64))
        self.assertEqual(rig.run(), 337)
        self.assertEqual(rig.logic.success_raw, 1)
        self.assertEqual(rig.town.forced_cars, 0)
        self.assertEqual(rig.logic.crash_count, 0)

    def test_stop_then_go(self) -> None:
        rig = Rig([straight()], lambda: GO)
        state = {"go": False}
        for c in rig.ctl:
            c.fn = lambda: GO if state["go"] else (0, 0, 0, 0)
        g = rig.town.grid
        for _ in range(129):
            rig.tick()
        self.assertIs(rig.cars[0].current, g[5][13])
        for _ in range(71):
            rig.tick()
        self.assertEqual(rig.ticks, 200)
        self.assertIs(rig.cars[0].current, g[5][13])
        self.assertFalse(rig.cars[0].done)
        state["go"] = True
        self.assertEqual(rig.run(), 409)

    def test_two_cars_start_together_crash(self) -> None:
        rig = Rig([straight(1), straight(2)], lambda: GO)
        self.assertEqual(rig.run(), 2)
        self.assertEqual(rig.logic.crash_count, 2)
        self.assertEqual(rig.logic.success_raw, 0)

    def test_two_cars_follow(self) -> None:
        rig = Rig([straight(1), straight(30)], lambda: GO)
        while rig.ticks < 2000:
            done = rig.tick()
            a, b = rig.cars
            if not a.done and not b.done and a.current is not None:
                self.assertIsNot(a.current, b.current)
            if done:
                break
        self.assertTrue(rig.cars[0].done and rig.cars[1].done)
        self.assertEqual(rig.logic.success_raw, 2)
        self.assertEqual(rig.logic.crash_count, 0)

    def test_forced_turn_signal(self) -> None:
        rig = Rig([straight()], lambda: (3, 3, 3, 3))
        self.assertGreater(rig.run(), 0)
        self.assertEqual(rig.town.forced_cars, 1)
        self.assertEqual(rig.logic.success_raw, 1)
        self.assertEqual(rig.logic.crash_count, 0)
        self.assertIn(rig.cars[0].end.type, END_TYPES)
        passed = max(0, rig.logic.success_raw - rig.town.forced_cars)
        failed = rig.town.forced_cars + rig.logic.crash_count
        self.assertEqual((passed, failed), (0, 1))

    def test_illegal_forced_turn_stops(self) -> None:
        rig = Rig([straight()], lambda: (1, 1, 1, 1))
        g = rig.town.grid
        g[5][11].south = None
        for _ in range(200):
            rig.tick()
        car = rig.cars[0]
        self.assertIs(car.state, CarState.STOPPED)
        self.assertIs(car.current, g[5][13])
        pos = (car.px, car.py)
        for _ in range(20):
            rig.tick()
        self.assertEqual((car.px, car.py), pos)
        self.assertIs(car.current, g[5][13])

    def test_data_type(self) -> None:
        self.assertIsInstance(Rig([straight()], lambda: GO).data, LevelData)


if __name__ == "__main__":
    unittest.main()
