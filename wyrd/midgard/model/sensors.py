"""General sensors, the sensor file, and sensor placement (port of GeneralSensor, LevelScreen)."""

from __future__ import annotations

from wyrd.midgard.model.grid import GridType, Node

SENSOR_COUNT = 7
PILE = (1, 1)


class Sensor:
    def __init__(self, number: int) -> None:
        self.number = number
        self.x = 0
        self.y = 0
        self.node: Node | None = None

    @property
    def placed(self) -> bool:
        return self.x != 0 or self.y != 0

    def read(self) -> int:
        """4 bits: 0 without a car, else 1 followed by the low 3 bits of the car's end counter."""
        node = self.node
        if not self.placed or node is None or node.car is None:
            return 0
        return 8 | (node.car.end.ending_counter & 7)

    def unplace(self) -> None:
        if self.node is not None and self.node.sensor is self:
            self.node.sensor = None
        self.node = None
        self.x = 0
        self.y = 0


def _tile(grid: list[list[Node]], ix: int, iy: int) -> Node | None:
    if 0 <= ix < len(grid) and 0 <= iy < len(grid[ix]):
        return grid[ix][iy]
    return None


def valid_tile(grid: list[list[Node]], ix: int, iy: int) -> bool:
    node = _tile(grid, ix, iy)
    return (
        node is not None
        and node.type is not GridType.NON_ROAD
        and node.control is None
        and node.sensor is None
    )


def _parse_line(line: str) -> tuple[int, int, int] | None:
    parts = line.split()
    if len(parts) != 3:
        return None
    try:
        k, x, y = (int(p) for p in parts)
    except ValueError:
        return None
    return (k, x, y) if 0 <= k < SENSOR_COUNT else None


class SensorSet:
    def __init__(self) -> None:
        self.sensors = [Sensor(k) for k in range(SENSOR_COUNT)]

    def general_word(self) -> int:
        return sum(s.read() << (4 * s.number) for s in self.sensors)

    def to_text(self) -> str:
        return "".join(f"{s.number} {s.x} {s.y}\n" for s in self.sensors)

    @classmethod
    def from_text(cls, text: str) -> SensorSet:
        result = cls()
        for line in text.splitlines():
            row = _parse_line(line)
            if row is not None:
                result.sensors[row[0]].x = row[1]
                result.sensors[row[0]].y = row[2]
        return result

    def attach(self, grid: list[list[Node]]) -> None:
        for s in self.sensors:
            if not s.placed:
                continue
            node = _tile(grid, s.x, s.y)
            if node is None or not valid_tile(grid, s.x, s.y):
                s.unplace()
                continue
            node.sensor = s
            s.node = node

    def unused_highest(self) -> Sensor | None:
        for s in reversed(self.sensors):
            if not s.placed:
                return s
        return None


class SensorEditor:
    """Mouse-release rules of the original level screen (spec 5.3); (ix, iy) are nodes."""

    def __init__(self, sensors: SensorSet, grid: list[list[Node]]) -> None:
        self.sensors = sensors
        self.grid = grid
        self.placing: Sensor | None = None
        self.dirty = False

    def valid_tile(self, ix: int, iy: int) -> bool:
        return valid_tile(self.grid, ix, iy)

    def left_release(self, ix: int, iy: int) -> None:
        if self.placing is None:
            self._pick(ix, iy)
        else:
            self._drop(ix, iy)

    def _pick(self, ix: int, iy: int) -> None:
        node = _tile(self.grid, ix, iy)
        if node is not None and node.sensor is not None:
            self.placing = node.sensor
        elif (ix, iy) == PILE:
            self.placing = self.sensors.unused_highest()

    def _drop(self, ix: int, iy: int) -> None:
        sensor = self.placing
        node = _tile(self.grid, ix, iy)
        if sensor is None or node is None or not self.valid_tile(ix, iy):
            return
        sensor.unplace()
        sensor.x, sensor.y, sensor.node = ix, iy, node
        node.sensor = sensor
        self.placing = None
        self.dirty = True

    def can_drag_from(self, ix: int, iy: int) -> bool:
        """True on the pile (while it holds a sensor) and on a placed sensor."""
        node = _tile(self.grid, ix, iy)
        if node is not None and node.sensor is not None:
            return True
        return (ix, iy) == PILE and self.sensors.unused_highest() is not None

    def drag_release(self, start: tuple[int, int], end: tuple[int, int]) -> None:
        """Press on the pile or a sensor, release on another tile: pick it up and drop it there.

        A drop on a bad tile leaves the sensor in hand, as after a click.
        """
        if self.placing is None:
            self._pick(*start)
        if self.placing is not None:
            self._drop(*end)

    def right_release(self, ix: int, iy: int) -> None:
        if self.placing is not None:
            self.placing = None
            return
        node = _tile(self.grid, ix, iy)
        if node is not None and node.sensor is not None:
            node.sensor.unplace()
            self.dirty = True

    def clear_all(self) -> None:
        for s in self.sensors.sensors:
            if s.placed:
                self.dirty = True
            s.unplace()
        self.placing = None
