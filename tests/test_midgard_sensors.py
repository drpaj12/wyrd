import unittest

from wyrd.midgard.model.car import Car
from wyrd.midgard.model.grid import Direction, Node, SignalState
from wyrd.midgard.model.levelxml import level_path, parse_level_file
from wyrd.midgard.model.sensors import Sensor, SensorEditor, SensorSet
from wyrd.midgard.model.townmap import TownMap


def put_car(node: Node, end: Node) -> Car:
    car = Car(node, end, 1)
    node.car = car
    return car


def place(sensor: Sensor, node: Node) -> None:
    sensor.x, sensor.y, sensor.node = node.x, node.y, node
    node.sensor = sensor


class SensorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.town = TownMap(parse_level_file(level_path(1)))
        self.g = self.town.grid

    def test_read_sensors_bits(self) -> None:
        g, c = self.g, self.town.controls[0]
        put_car(g[7][12], g[5][0])
        put_car(g[5][12], g[5][0])
        self.assertEqual(c.read_sensors(), 129)
        g[7][12].car = None
        g[5][12].car = None
        for node, bits in (
            (g[6][10], 64),
            (g[5][13], 16),
            (g[4][11], 32),
            (g[6][11], 8),
            (g[5][11], 4),
            (g[6][12], 2),
        ):
            put_car(node, g[5][0])
            self.assertEqual(c.read_sensors(), bits)
            node.car = None
        self.assertEqual(c.read_sensors(), 0)

    def test_read_sensors_three_way(self) -> None:
        town = TownMap(parse_level_file(level_path(0)))
        c = town.controls[0]
        end = town.grid[0][0]
        for col in town.grid:
            for n in col:
                if n.control is c:
                    put_car(n, end)
        self.assertEqual(c.read_sensors() & 0b10000, 0)
        self.assertEqual(c.read_sensors() & 0b11101111, 0b11101111)

    def test_signal_state(self) -> None:
        g, c = self.g, self.town.controls[0]
        c.set_signals(SignalState.GO, SignalState.STOP, SignalState.GO_LEFT, SignalState.STOP)
        self.assertIs(g[6][10].traffic_signal(), SignalState.GO)
        self.assertIs(g[5][13].traffic_signal(), SignalState.STOP)
        self.assertIs(g[4][11].traffic_signal(), SignalState.GO_LEFT)
        self.assertIs(g[7][12].traffic_signal(), SignalState.STOP)
        self.assertIs(g[5][12].traffic_signal(), SignalState.NO_SIGNAL)
        self.assertIs(g[5][20].traffic_signal(), SignalState.NO_SIGNAL)
        self.assertIs(c.signal_when(4), SignalState.NO_SIGNAL)
        self.assertIs(c.facing[Direction.E], SignalState.GO_LEFT)

    def test_sensor_read(self) -> None:
        g = self.g
        s = Sensor(0)
        self.assertEqual(s.read(), 0)
        place(s, g[5][13])
        self.assertTrue(s.placed)
        self.assertEqual(s.read(), 0)
        put_car(g[5][13], g[13][0])
        self.assertEqual(s.read(), 11)
        g[5][13].car = None
        put_car(g[5][13], g[5][0])
        self.assertEqual(s.read(), 12)
        g[5][13].car = None
        end = Node(1, 1, g[5][0].type)
        end.ending_counter = 9
        put_car(g[5][13], end)
        self.assertEqual(s.read(), 9)
        self.assertEqual(Sensor(2).read(), 0)
        self.assertFalse(Sensor(2).placed)

    def test_general_word(self) -> None:
        g = self.g
        ss = SensorSet()
        self.assertEqual(ss.general_word(), 0)
        place(ss.sensors[3], g[5][13])
        place(ss.sensors[0], g[6][10])
        put_car(g[5][13], g[13][0])
        put_car(g[6][10], g[5][0])
        self.assertEqual(ss.general_word(), (11 << 12) | 12)
        self.assertEqual(ss.general_word(), 45068)
        top = Node(0, 0, g[5][0].type)
        top.ending_counter = 7
        for k, s in enumerate(ss.sensors):
            node = g[5 + k][14]
            place(s, node)
            put_car(node, top)
        self.assertEqual(ss.general_word(), 2**28 - 1)
        self.assertLess(ss.general_word(), 2**30)

    def test_sensor_file(self) -> None:
        self.assertEqual(SensorSet().to_text(), "0 0 0\n1 0 0\n2 0 0\n3 0 0\n4 0 0\n5 0 0\n6 0 0\n")
        ss = SensorSet.from_text("0 5 13\n3 6 10\n")
        self.assertEqual((ss.sensors[0].x, ss.sensors[0].y), (5, 13))
        self.assertEqual((ss.sensors[3].x, ss.sensors[3].y), (6, 10))
        self.assertFalse(ss.sensors[1].placed)
        for junk in ("hello", "9 1 1", "1 x 2", "", "1 2", "1 2 3 4"):
            SensorSet.from_text(junk + "\n")
        self.assertEqual(SensorSet.from_text("9 1 1\n1 x 2\n").to_text(), SensorSet().to_text())
        again = SensorSet.from_text(ss.to_text())
        self.assertEqual(again.to_text(), ss.to_text())

    def test_attach_rejects_bad_tiles(self) -> None:
        g = self.g
        ss = SensorSet.from_text("1 1 2\n2 5 12\n4 500 500\n5 5 14\n")
        ss.attach(g)
        for k in (1, 2, 4):
            self.assertFalse(ss.sensors[k].placed)
            self.assertIsNone(ss.sensors[k].node)
        self.assertIsNone(g[1][2].sensor)
        self.assertIsNone(g[5][12].sensor)
        self.assertTrue(ss.sensors[5].placed)
        self.assertIs(g[5][14].sensor, ss.sensors[5])
        self.assertIs(ss.sensors[5].node, g[5][14])

    def test_editor_flow(self) -> None:
        g = self.g
        ss = SensorSet()
        ed = SensorEditor(ss, g)
        ed.left_release(1, 1)
        self.assertIs(ed.placing, ss.sensors[6])
        ed.left_release(5, 13)
        self.assertIs(ed.placing, ss.sensors[6])
        self.assertFalse(ss.sensors[6].placed)
        ed.left_release(1, 2)
        self.assertIs(ed.placing, ss.sensors[6])
        self.assertFalse(ed.dirty)
        ed.left_release(5, 15)
        self.assertEqual((ss.sensors[6].x, ss.sensors[6].y), (5, 15))
        self.assertIs(g[5][15].sensor, ss.sensors[6])
        self.assertIsNone(ed.placing)
        self.assertTrue(ed.dirty)

    def test_editor_move_remove(self) -> None:
        g = self.g
        ss = SensorSet()
        ed = SensorEditor(ss, g)
        ed.left_release(1, 1)
        ed.left_release(5, 15)
        ed.left_release(5, 15)
        self.assertIs(ed.placing, ss.sensors[6])
        ed.right_release(0, 0)
        self.assertIsNone(ed.placing)
        self.assertTrue(ss.sensors[6].placed)
        ed.left_release(5, 15)
        ed.left_release(5, 16)
        self.assertIsNone(g[5][15].sensor)
        self.assertIs(g[5][16].sensor, ss.sensors[6])
        ed.right_release(5, 16)
        self.assertEqual((ss.sensors[6].x, ss.sensors[6].y), (0, 0))
        self.assertIsNone(g[5][16].sensor)
        ed.left_release(1, 1)
        ed.left_release(5, 15)
        ed.left_release(1, 1)
        self.assertIs(ed.placing, ss.sensors[5])
        ed.left_release(5, 15)
        self.assertFalse(ss.sensors[5].placed)
        self.assertIs(ed.placing, ss.sensors[5])

    def test_drag_from_pile_places(self) -> None:
        ss = SensorSet()
        ed = SensorEditor(ss, self.g)
        self.assertTrue(ed.can_drag_from(1, 1))
        ed.drag_release((1, 1), (5, 15))
        self.assertEqual((ss.sensors[6].x, ss.sensors[6].y), (5, 15))
        self.assertIsNone(ed.placing)
        self.assertTrue(ed.dirty)

    def test_drag_moves_placed_sensor(self) -> None:
        ss = SensorSet()
        ed = SensorEditor(ss, self.g)
        ed.drag_release((1, 1), (5, 15))
        self.assertTrue(ed.can_drag_from(5, 15))
        ed.drag_release((5, 15), (5, 16))
        self.assertIsNone(self.g[5][15].sensor)
        self.assertIs(self.g[5][16].sensor, ss.sensors[6])

    def test_drag_onto_bad_tile_keeps_sensor_in_hand(self) -> None:
        ss = SensorSet()
        ed = SensorEditor(ss, self.g)
        ed.drag_release((1, 1), (1, 2))
        self.assertIs(ed.placing, ss.sensors[6])
        self.assertFalse(ss.sensors[6].placed)
        self.assertFalse(ed.dirty)

    def test_drag_from_empty_tile_does_nothing(self) -> None:
        ss = SensorSet()
        ed = SensorEditor(ss, self.g)
        self.assertFalse(ed.can_drag_from(5, 15))
        ed.drag_release((5, 15), (5, 16))
        self.assertIsNone(ed.placing)
        self.assertFalse(any(s.placed for s in ss.sensors))

    def test_pile_empty(self) -> None:
        g = self.g
        ss = SensorSet()
        ed = SensorEditor(ss, g)
        for k in range(7):
            ed.left_release(1, 1)
            ed.left_release(5, 14 + k)
        self.assertTrue(all(s.placed for s in ss.sensors))
        ed.left_release(1, 1)
        self.assertIsNone(ed.placing)
        self.assertIsNone(ss.unused_highest())
        ed.clear_all()
        self.assertFalse(any(s.placed for s in ss.sensors))
        self.assertTrue(all(n.sensor is None for col in g for n in col))
        self.assertIs(ss.unused_highest(), ss.sensors[6])


if __name__ == "__main__":
    unittest.main()
