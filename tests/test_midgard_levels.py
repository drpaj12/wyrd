import unittest

from wyrd.midgard.model.grid import (
    CORNER_TYPES,
    END_TYPES,
    START_TYPES,
    GridType,
    Node,
    SignalState,
    decode_signal,
)
from wyrd.midgard.model.levelxml import (
    INTERSECTION_KINDS,
    LEVEL_NUMBERS,
    CarSpec,
    IntersectionSpec,
    LevelFormatError,
    level_path,
    parse_level_file,
    parse_level_xml,
)

CARS = [18, 10, 20, 34, 30, 16, 26, 19, 30, 34, 40, 40, 25]
INTERS = [1, 2, 3, 1, 1, 4, 9, 4, 4, 4, 6, 4, 11]
MIN_DELAY = [50, 100, 100, 20, 10, 1, 10, 20, 10, 20, 20, 23, 100]


def tiny(grids: str = "", cars: str = "<cars/>", size: int = 10) -> str:
    return f'<level lv="9"><map size_x="{size}" size_y="{size}">{grids}</map>{cars}</level>'


def grid(x: int, y: int, kind: str = "NON_ROAD", inter: str | None = None) -> str:
    extra = f"<intersection>{inter}</intersection>" if inter else ""
    return f'<grid x="{x}" y="{y}"><type>{kind}</type>{extra}</grid>'


def car(sx: int, sy: int, ex: int, ey: int, delay: int) -> str:
    return (
        f'<car><start x="{sx}" y="{sy}"/><end x="{ex}" y="{ey}"/><delay>{delay}</delay></car>'
    )


class LevelsTest(unittest.TestCase):
    def test_enums(self) -> None:
        self.assertEqual(len(GridType), 25)
        self.assertEqual(len(END_TYPES), 4)
        self.assertEqual(len(CORNER_TYPES), 8)
        self.assertEqual(len(START_TYPES), 4)
        self.assertIs(decode_signal(0), SignalState.STOP)
        self.assertIs(decode_signal(4), SignalState.GO)
        self.assertIs(decode_signal(5), SignalState.STOP)
        self.assertIs(decode_signal(7), SignalState.STOP)
        self.assertEqual(SignalState.NO_SIGNAL, 5)

    def test_all_levels_parse(self) -> None:
        self.assertEqual(LEVEL_NUMBERS, tuple(range(13)))
        for n in range(13):
            data = parse_level_file(level_path(n))
            self.assertEqual(data.number, n)
            self.assertEqual((data.size_x, data.size_y), (22, 22))
            self.assertEqual(len(data.cars), CARS[n], n)
            self.assertEqual(len(data.intersections), INTERS[n], n)
            self.assertEqual(min(c.delay for c in data.cars), MIN_DELAY[n], n)
            for c in data.cars:
                self.assertGreaterEqual(c.delay, 1)
                for x, y in (c.start, c.end):
                    self.assertTrue(0 <= x < 22 and 0 <= y < 22)
            for i in data.intersections:
                self.assertIn(i.kind, INTERSECTION_KINDS)

    def test_level1_facts(self) -> None:
        data = parse_level_file(level_path(1))
        self.assertEqual(
            data.intersections,
            (IntersectionSpec("FOUR_WAY", 5, 12), IntersectionSpec("FOUR_WAY", 13, 12)),
        )
        self.assertEqual(data.cars[0], CarSpec((5, 21), (5, 0), 100))
        self.assertIs(data.tiles[(5, 12)], GridType.INTER_TURN_S2WS)
        self.assertIs(data.tiles[(6, 0)], GridType.START_SEDGE2N)
        self.assertIn(data.tiles.get((2, 2), GridType.NON_ROAD), (GridType.NON_ROAD,))
        level0 = parse_level_file(level_path(0))
        self.assertEqual(level0.intersections, (IntersectionSpec("THREE_WAY_NEW", 7, 18),))

    def test_intersection_order(self) -> None:
        text = tiny(
            grid(3, 5, inter="FOUR_WAY") + grid(1, 9, inter="FOUR_WAY")
            + grid(2, 9, inter="FOUR_WAY")
        )
        data = parse_level_xml(text)
        self.assertEqual([(i.x, i.y) for i in data.intersections], [(1, 9), (2, 9), (3, 5)])

    def test_bad_input(self) -> None:
        data = parse_level_xml(tiny(grid(1, 1, "SOMETHING_ELSE")))
        self.assertIs(data.tiles.get((1, 1), GridType.NON_ROAD), GridType.NON_ROAD)
        with self.assertRaises(LevelFormatError):
            parse_level_xml("<level><map")
        with self.assertRaises(LevelFormatError) as ctx:
            parse_level_xml(tiny(cars="<cars>" + car(1, 1, 2, 2, 0) + "</cars>"))
        self.assertIn("delay must be at least 1", str(ctx.exception))
        with self.assertRaises(LevelFormatError) as ctx:
            parse_level_xml(tiny(cars="<cars>" + car(10, 1, 2, 2, 5) + "</cars>"))
        self.assertIn("outside the map", str(ctx.exception))
        with self.assertRaises(LevelFormatError):
            parse_level_xml(tiny(grid(1, 1, inter="SEVEN_WAY")))

    def test_node_signal(self) -> None:
        self.assertIs(Node(1, 1, GridType.NON_ROAD).traffic_signal(), SignalState.NO_SIGNAL)


if __name__ == "__main__":
    unittest.main()
