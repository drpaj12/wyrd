import unittest

from wyrd.midgard.model.car import Car
from wyrd.midgard.model.grid import END_TYPES, Direction, GridType, SignalState
from wyrd.midgard.model.levelxml import (
    CarSpec,
    LevelData,
    level_path,
    parse_level_file,
)
from wyrd.midgard.model.townmap import TownMap


def level1() -> tuple[LevelData, TownMap]:
    data = parse_level_file(level_path(1))
    return data, TownMap(data)


class TownMapTest(unittest.TestCase):
    def test_links(self) -> None:
        _, town = level1()
        g = town.grid
        self.assertIs(g[5][13].south, g[5][12])
        self.assertIs(g[5][12].west, g[4][12])
        self.assertIs(g[5][12].south, g[5][11])
        self.assertIsNone(g[5][12].north)
        self.assertIs(g[5][11].east, g[6][11])
        self.assertIs(g[5][11].south, g[5][10])
        n = g[6][21]
        self.assertIs(n.type, GridType.END_N2NEDGE)
        self.assertEqual((n.north, n.south, n.east, n.west), (None, None, None, None))
        self.assertIs(g[6][0].north, g[6][1])
        self.assertIs(g[2][2].type, GridType.NON_ROAD)

    def test_controls(self) -> None:
        _, town = level1()
        g = town.grid
        self.assertEqual(len(town.controls), 2)
        c = town.controls[0]
        self.assertIs(c.entries[Direction.N], g[6][10])
        self.assertIs(c.entries[Direction.S], g[5][13])
        self.assertIs(c.entries[Direction.E], g[4][11])
        self.assertIs(c.entries[Direction.W], g[7][12])
        self.assertEqual(c.internal, (g[5][12], g[6][12], g[5][11], g[6][11]))
        self.assertEqual(g[5][13].location, 1)
        self.assertIs(g[5][13].control, c)
        self.assertEqual(g[6][10].location, 0)
        self.assertEqual(g[5][12].location, 4)
        self.assertIs(town.controls[1].internal[0], g[13][12])
        self.assertIsNone(g[3][3].control)

    def test_three_way(self) -> None:
        town = TownMap(parse_level_file(level_path(0)))
        c = town.controls[0]
        self.assertEqual(c.kind, "THREE_WAY_NEW")
        self.assertIsNone(c.entries[Direction.S])
        for d in (Direction.N, Direction.E, Direction.W):
            self.assertIsNotNone(c.entries[d])

    def test_ending_counters(self) -> None:
        _, town = level1()
        g = town.grid
        got = [
            g[6][21].ending_counter, g[14][21].ending_counter, g[21][11].ending_counter,
            g[13][0].ending_counter, g[5][0].ending_counter, g[0][12].ending_counter,
        ]
        self.assertEqual(got, [0, 1, 2, 3, 4, 5])

    def test_find_path_straight(self) -> None:
        data, town = level1()
        g = town.grid
        car = town.make_cars(data)[0]
        p = town.find_path(None, car.start, car.end, car)
        self.assertEqual(len(p), 21)
        self.assertIs(p[-1], g[5][20])
        self.assertIs(p[0], g[5][0])
        self.assertTrue(all(n.x == 5 for n in p))
        self.assertEqual(town.forced_cars, 0)

    def test_find_path_adjacent(self) -> None:
        data, town = level1()
        g = town.grid
        car = town.make_cars(data)[0]
        self.assertEqual(town.find_path(None, g[5][1], g[5][0], car), [g[5][0]])

    def test_forced_unreachable(self) -> None:
        data, town = level1()
        g = town.grid
        car = town.make_cars(data)[0]
        car.end = g[6][0]
        p = town.find_path(None, car.start, car.end, car)
        self.assertIn(p[0].type, END_TYPES)
        self.assertIs(car.end, p[0])
        self.assertTrue(car.forced_turned)
        self.assertEqual(town.forced_cars, 1)
        town.find_path(None, car.start, g[6][0], car)
        self.assertEqual(town.forced_cars, 1)

    def test_no_end_reachable(self) -> None:
        tiles = {
            (1, 4): GridType.START_NEDGE2S,
            (1, 3): GridType.STRAIGHT_ROAD_S2S,
            (3, 0): GridType.END_S2SEDGE,
        }
        data = LevelData(99, 5, 5, tiles, (), (CarSpec((1, 4), (3, 0), 1),))
        town = TownMap(data)
        car = town.make_cars(data)[0]
        self.assertEqual(town.find_path(None, car.start, car.end, car), [])
        self.assertTrue(car.done)
        self.assertTrue(car.forced_turned)
        self.assertEqual(town.forced_cars, 1)
        self.assertIsNone(car.current)

    def test_set_path_with_waypoint(self) -> None:
        data, town = level1()
        g = town.grid
        car = town.make_cars(data)[0]
        via = g[4][12]
        town.set_path(car, g[5][13], via)
        self.assertIs(car.way_point, via)
        self.assertIs(car.path[-1], g[5][12])
        self.assertIn(via, car.path)
        town.set_path(car, via, None)
        self.assertIsNone(car.way_point)
        self.assertIs(car.path[0], car.end)

    def test_get_turn(self) -> None:
        _, town = level1()
        g = town.grid
        turn = town.get_turn
        self.assertIs(turn(g[5][13], SignalState.GO_FORWARD, Direction.S), g[5][10])
        self.assertIs(turn(g[5][13], SignalState.GO_LEFT, Direction.S), g[7][11])
        self.assertIs(turn(g[5][13], SignalState.GO_RIGHT, Direction.S), g[4][12])
        self.assertIs(turn(g[6][10], SignalState.GO_LEFT, Direction.N), g[4][12])
        self.assertIs(turn(g[6][10], SignalState.GO_RIGHT, Direction.N), g[7][11])
        self.assertIsNone(turn(g[6][0], SignalState.GO_RIGHT, Direction.N))
        self.assertIsNone(turn(g[5][13], SignalState.GO, Direction.S))

    def test_clear_cars(self) -> None:
        data, town = level1()
        g = town.grid
        g[5][13].car = town.make_cars(data)[0]
        town.clear_cars()
        self.assertTrue(all(n.car is None for col in g for n in col))

    def test_car_attributes(self) -> None:
        data, town = level1()
        car: Car = town.make_cars(data)[0]
        self.assertIs(car.original_end, car.end)
        self.assertEqual(car.start_time, 100)
        self.assertFalse(car.running)
        car.started = True
        self.assertTrue(car.running)


if __name__ == "__main__":
    unittest.main()
