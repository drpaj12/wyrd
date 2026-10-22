import unittest
from pathlib import Path

from wyrd.midgard.model.grid import GridType
from wyrd.midgard.model.leveldoc import GROUP_TYPES, ROTATE_CYCLES, LevelDoc
from wyrd.midgard.model.levelxml import (
    LEVEL_NUMBERS,
    LevelFormatError,
    level_path,
    parse_level_file,
    parse_level_xml,
    write_level_xml,
)

ROOT = Path(__file__).resolve().parent
FIRST_MAP = ROOT / "data" / "midgard" / "first_map.xml"
LEVEL_FILES = [level_path(n) for n in LEVEL_NUMBERS]
# Hand-formatted shipped files (indented, with comments or edited by hand). Their content
# round-trips, their bytes do not, because the original editor wrote one compact line.
HAND_FORMATTED = {"lv01.xml", "lv12.xml"}


def read_text(path: Path) -> str:
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def first_difference(a: str, b: str) -> int:
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        if x != y:
            return i
    return min(len(a), len(b))


class RoundTripTest(unittest.TestCase):
    def check_bytes(self, path: Path, written: str) -> None:
        text = read_text(path)
        if path.name in HAND_FORMATTED:
            return
        # Some shipped files end with a newline the Java Transformer never wrote.
        self.assertEqual(
            written,
            text.removesuffix("\n"),
            f"{path.name}: first differing offset {first_difference(written, text)}",
        )

    def test_xml_roundtrip_bytes(self) -> None:
        compact = 0
        for path in LEVEL_FILES:
            data = parse_level_file(path)
            written = write_level_xml(data)
            self.check_bytes(path, written)
            self.assertEqual(parse_level_xml(written), data, path.name)
            compact += path.name not in HAND_FORMATTED
        self.assertEqual(compact, 11)

    def test_hand_formatted_files_are_the_indented_ones(self) -> None:
        for path in LEVEL_FILES:
            indented = "\n    " in read_text(path)
            self.assertEqual(indented, path.name in HAND_FORMATTED, path.name)

    def test_first_map_is_not_a_playable_level(self) -> None:
        # The original sample has size_y 23 and a car that ends on a road tile: the checked
        # parser refuses it, so it cannot round-trip through LevelData.
        with self.assertRaises(LevelFormatError):
            parse_level_file(FIRST_MAP)

    def test_doc_roundtrip(self) -> None:
        for path in LEVEL_FILES:
            data = parse_level_file(path)
            doc = LevelDoc.from_level_data(data)
            self.assertEqual(doc.to_level_data(), data, path.name)
            self.check_bytes(path, write_level_xml(doc.to_level_data()))

    def test_doc_start_end_order_matches_the_files(self) -> None:
        for path in LEVEL_FILES:
            if path.name in HAND_FORMATTED:
                continue
            data = parse_level_file(path)
            doc = LevelDoc.from_level_data(data)
            file_order = list(data.tiles)
            interleaved = [p for pair in zip(doc.starts, doc.ends, strict=True) for p in pair]
            self.assertEqual(file_order[: len(interleaved)], interleaved, path.name)
            doc.populate_starts_ends()
            self.assertEqual(
                file_order[: len(interleaved)],
                [p for pair in zip(doc.starts, doc.ends, strict=True) for p in pair],
                path.name,
            )


class DocTest(unittest.TestCase):
    def test_group_types(self) -> None:
        self.assertEqual(len(GROUP_TYPES), 17)
        self.assertEqual(GROUP_TYPES[0], "STRAIGHT_NS")
        self.assertEqual(GROUP_TYPES[-1], "NON_ROAD_2")
        self.assertEqual(
            GROUP_TYPES[11:15],
            ("THREE_WAY_NSW", "THREE_WAY_NEW", "THREE_WAY_NSE", "THREE_WAY_SEW"),
        )

    def test_new_level(self) -> None:
        doc = LevelDoc(5, 20, 20)
        self.assertEqual(len(doc.groups), 10)
        self.assertTrue(all(len(col) == 10 for col in doc.groups))
        self.assertTrue(all(t == "NON_ROAD" for col in doc.groups for t in col))
        self.assertEqual(doc.to_level_data().size_x, 22)
        for size in ((3, 20), (2, 20), (20, 5), (21, 20)):
            with self.assertRaises(ValueError):
                LevelDoc(5, *size)
        doc.set_type(0, 0, "FOUR_WAY")
        self.assertFalse(doc.populate_starts_ends())
        doc.set_type(0, 0, "NON_ROAD")
        doc.set_type(1, 1, "FOUR_WAY")
        self.assertTrue(doc.populate_starts_ends())

    def test_set_type_rejects_unknown_and_out_of_range(self) -> None:
        doc = LevelDoc(5, 20, 20)
        with self.assertRaises(ValueError):
            doc.set_type(0, 0, "BOGUS")
        with self.assertRaises(ValueError):
            doc.set_type(10, 0, "NON_ROAD")

    def test_rotate_and_clear(self) -> None:
        self.assertEqual(
            ROTATE_CYCLES,
            (
                ("NON_ROAD", "NON_ROAD_2"),
                ("STRAIGHT_NS", "STRAIGHT_NS_2", "STRAIGHT_NS_3"),
                ("STRAIGHT_EW", "STRAIGHT_EW_2"),
                ("FOUR_WAY", "FOUR_WAY_2"),
            ),
        )
        doc = LevelDoc(5, 20, 20)
        for cycle in ROTATE_CYCLES:
            doc.set_type(2, 2, cycle[0])
            seen = [cycle[0]]
            for _ in cycle:
                doc.rotate_type(2, 2)
                seen.append(doc.groups[2][2])
            self.assertEqual(seen, [*cycle, cycle[0]])
        for fixed in ("CORNER_NW", "THREE_WAY_NSE"):
            doc.set_type(2, 2, fixed)
            doc.rotate_type(2, 2)
            self.assertEqual(doc.groups[2][2], fixed)
        doc.set_type(0, 0, "STRAIGHT_NS")
        doc.populate_starts_ends()
        self.assertTrue(doc.starts)
        doc.clear_map()
        self.assertTrue(all(t == "NON_ROAD" for col in doc.groups for t in col))
        self.assertEqual((doc.starts, doc.ends, doc.cars), ([], [], []))

    def test_cars(self) -> None:
        doc = LevelDoc.from_level_data(parse_level_file(level_path(1)))
        before = len(doc.cars)
        doc.add_car(doc.starts[0], doc.ends[0], 10)
        self.assertEqual(len(doc.cars), before + 1)
        self.assertEqual(doc.cars[-1].delay, 10)
        with self.assertRaises(ValueError):
            doc.add_car(doc.starts[0], doc.ends[0], 0)
        with self.assertRaises(ValueError):
            doc.add_car((3, 3), doc.ends[0], 5)
        with self.assertRaises(ValueError):
            doc.add_car(doc.starts[0], (3, 3), 5)
        doc.remove_car(0)
        self.assertEqual(len(doc.cars), before)
        with self.assertRaises(IndexError):
            doc.remove_car(99)

    def test_new_doc_clears_cars_when_starts_change(self) -> None:
        doc = LevelDoc(5, 20, 20)
        doc.set_type(0, 0, "STRAIGHT_NS")
        doc.set_type(1, 9, "STRAIGHT_NS")
        self.assertTrue(doc.populate_starts_ends())
        doc.add_car(doc.starts[0], doc.ends[0], 10)
        self.assertEqual(len(doc.cars), 1)
        self.assertTrue(doc.populate_starts_ends())
        self.assertEqual(len(doc.cars), 1)
        doc.set_type(0, 0, "NON_ROAD")
        self.assertTrue(doc.populate_starts_ends())
        self.assertEqual(doc.cars, [])

    def test_loaded_doc_keeps_cars_when_starts_change(self) -> None:
        doc = LevelDoc.from_level_data(parse_level_file(level_path(1)))
        cars = list(doc.cars)
        doc.set_type(0, 0, "STRAIGHT_NS")
        self.assertTrue(doc.populate_starts_ends())
        self.assertEqual(doc.cars, cars)

    def test_level_number_and_name(self) -> None:
        doc = LevelDoc(5, 20, 20)
        self.assertEqual(doc.to_level_data().number, 5)
        self.assertIn('lv="5"', write_level_xml(doc.to_level_data()))

    def test_unknown_cell_pattern(self) -> None:
        data = parse_level_file(level_path(2))
        tiles = dict(data.tiles)
        tiles[(1, 1)] = GridType.INTER_TURN_N2EN
        bad = type(data)(
            data.number, data.size_x, data.size_y, tiles, data.intersections, data.cars
        )
        with self.assertRaises(ValueError) as cm:
            LevelDoc.from_level_data(bad)
        self.assertIn("(1, 2)", str(cm.exception))

    def test_straight_road_new_level_writes_a_valid_file(self) -> None:
        doc = LevelDoc(5, 20, 20)
        for gy in range(10):
            doc.set_type(4, gy, "STRAIGHT_NS")
        self.assertTrue(doc.populate_starts_ends())
        doc.add_car(doc.starts[0], doc.ends[0], 20)
        data = doc.to_level_data()
        again = parse_level_xml(write_level_xml(data))
        self.assertEqual(again, data)


if __name__ == "__main__":
    unittest.main()
