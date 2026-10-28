"""The map: grid, links, intersections, path finding (port of VerilogTownMap)."""

from __future__ import annotations

from collections import deque

from wyrd.midgard.model.car import Car
from wyrd.midgard.model.grid import (
    END_TYPES,
    Direction,
    GridType,
    Node,
    SignalState,
)
from wyrd.midgard.model.levelxml import IntersectionSpec, LevelData, LevelFormatError
from wyrd.midgard.model.traffic import TrafficControl

GT = GridType
_NORTH = {
    GT.START_SEDGE2N,
    GT.STRAIGHT_ROAD_N2N,
    GT.CORNER_ROAD_E2N,
    GT.CORNER_ROAD_W2N,
    GT.INTER_TURN_N2EN,
    GT.INTER_TURN_W2NW,
}
_SOUTH = {
    GT.START_NEDGE2S,
    GT.STRAIGHT_ROAD_S2S,
    GT.CORNER_ROAD_W2S,
    GT.CORNER_ROAD_E2S,
    GT.INTER_TURN_S2WS,
    GT.INTER_TURN_E2SE,
}
_WEST = {
    GT.START_EEDGE2W,
    GT.STRAIGHT_ROAD_W2W,
    GT.CORNER_ROAD_N2W,
    GT.CORNER_ROAD_S2W,
    GT.INTER_TURN_S2WS,
    GT.INTER_TURN_W2NW,
}
_EAST = {
    GT.START_WEDGE2E,
    GT.STRAIGHT_ROAD_E2E,
    GT.CORNER_ROAD_N2E,
    GT.CORNER_ROAD_S2E,
    GT.INTER_TURN_N2EN,
    GT.INTER_TURN_E2SE,
}
_ENTRIES = {
    "FOUR_WAY": "NSEW",
    "THREE_WAY_NSE": "NSE",
    "THREE_WAY_SEW": "SEW",
    "THREE_WAY_NSW": "NSW",
    "THREE_WAY_NEW": "NEW",
}


_TURNS: dict[SignalState, dict[Direction, str]] = {
    SignalState.GO_FORWARD: {
        Direction.N: "nnn",
        Direction.S: "sss",
        Direction.E: "eee",
        Direction.W: "www",
    },
    SignalState.GO_LEFT: {
        Direction.N: "nnww",
        Direction.S: "ssee",
        Direction.E: "eenn",
        Direction.W: "wwss",
    },
    SignalState.GO_RIGHT: {
        Direction.N: "ne",
        Direction.S: "sw",
        Direction.E: "es",
        Direction.W: "wn",
    },
}


def _step(node: Node, name: str) -> Node | None:
    if name == "n":
        return node.north
    if name == "s":
        return node.south
    if name == "e":
        return node.east
    return node.west


def _walk(node: Node | None, steps: str) -> Node | None:
    for name in steps:
        if node is None:
            return None
        node = _step(node, name)
    return node


def _neighbours(node: Node) -> tuple[Node | None, ...]:
    return (node.north, node.south, node.east, node.west)


class TownMap:
    def __init__(self, data: LevelData) -> None:
        self.size_x = data.size_x
        self.size_y = data.size_y
        self.grid: list[list[Node]] = [
            [Node(x, y, data.tiles.get((x, y), GridType.NON_ROAD)) for y in range(data.size_y)]
            for x in range(data.size_x)
        ]
        self.controls: list[TrafficControl] = []
        self.forced_cars = 0
        self._link()
        for index, spec in enumerate(data.intersections):
            self.controls.append(self._build_control(spec, index))
        self._number_ends()

    def _at(self, x: int, y: int) -> Node | None:
        if 0 <= x < self.size_x and 0 <= y < self.size_y:
            return self.grid[x][y]
        return None

    def _link(self) -> None:
        for col in self.grid:
            for n in col:
                if n.type in _NORTH:
                    n.north = self._at(n.x, n.y + 1)
                if n.type in _SOUTH:
                    n.south = self._at(n.x, n.y - 1)
                if n.type in _WEST:
                    n.west = self._at(n.x - 1, n.y)
                if n.type in _EAST:
                    n.east = self._at(n.x + 1, n.y)

    def _build_control(self, spec: IntersectionSpec, index: int) -> TrafficControl:
        x, y = spec.x, spec.y
        present = _ENTRIES[spec.kind]
        spots = {
            Direction.N: self._at(x + 1, y - 2),
            Direction.S: self._at(x, y + 1),
            Direction.E: self._at(x - 1, y - 1),
            Direction.W: self._at(x + 2, y),
        }
        entries = {d: (n if d.name in present else None) for d, n in spots.items()}
        internal = [self._at(x, y), self._at(x + 1, y), self._at(x, y - 1), self._at(x + 1, y - 1)]
        if any(n is None for n in internal):
            raise LevelFormatError(f"intersection at {(x, y)} is not inside the map")
        control = TrafficControl(spec.kind, index)
        control.attach(entries, [n for n in internal if n is not None])
        return control

    def _number_ends(self) -> None:
        sx, sy = self.size_x, self.size_y
        counter = 0
        runs = (
            (GridType.END_N2NEDGE, [(x, sy - 1) for x in range(sx)]),
            (GridType.END_E2EEDGE, [(sx - 1, y) for y in range(sy - 1, -1, -1)]),
            (GridType.END_S2SEDGE, [(x, 0) for x in range(sx - 1, -1, -1)]),
            (GridType.END_W2WEDGE, [(0, y) for y in range(sy)]),
        )
        for kind, cells in runs:
            for x, y in cells:
                if self.grid[x][y].type is kind:
                    self.grid[x][y].ending_counter = counter
                    counter += 1

    def make_cars(self, data: LevelData) -> list[Car]:
        cars: list[Car] = []
        for spec in data.cars:
            start = self.grid[spec.start[0]][spec.start[1]]
            end = self.grid[spec.end[0]][spec.end[1]]
            cars.append(Car(start, end, spec.delay))
        return cars

    def find_path(
        self, existing: list[Node] | None, start: Node, end: Node, car: Car
    ) -> list[Node]:
        queue = deque([start])
        parent: dict[Node, Node] = {}
        possible_end: Node | None = None
        while queue:
            cur = queue.popleft()
            if possible_end is None and cur.type in END_TYPES:
                possible_end = cur
            if any(nb is end for nb in _neighbours(cur)):
                return _back_traverse(existing, end, start, cur, parent)
            for nb in _neighbours(cur):
                if nb is not None and nb not in parent and nb is not start:
                    queue.append(nb)
                    parent[nb] = cur
        return self._force(existing, start, car, possible_end)

    def _force(
        self, existing: list[Node] | None, start: Node, car: Car, possible_end: Node | None
    ) -> list[Node]:
        if not car.forced_turned:
            self.forced_cars += 1
        car.forced_turned = True
        if possible_end is None or possible_end is start:
            if car.current is not None:
                car.current.car = None
            car.done = True
            car.current = None
            return []
        car.end = possible_end
        return self.find_path(existing, start, possible_end, car)

    def set_path(self, car: Car, to: Node, via: Node | None) -> None:
        if via is None and car.way_point is None:
            car.path = self.find_path(None, to, car.end, car)
        elif car.way_point is to:
            car.way_point = None
            car.path = self.find_path(None, to, car.end, car)
        elif via is not None:
            car.way_point = via
            first = self.find_path(None, via, car.end, car)
            car.path = self.find_path(first, to, via, car)
        else:
            assert car.way_point is not None
            first = self.find_path(None, car.way_point, car.end, car)
            car.path = self.find_path(first, to, car.way_point, car)

    def get_turn(self, current: Node, signal: SignalState, direction: Direction) -> Node | None:
        steps = _TURNS.get(signal, {}).get(direction)
        return _walk(current, steps) if steps is not None else None

    def clear_cars(self) -> None:
        for col in self.grid:
            for n in col:
                n.car = None


def _back_traverse(
    existing: list[Node] | None, end: Node, start: Node, current: Node, parent: dict[Node, Node]
) -> list[Node]:
    path = existing if existing is not None else []
    path.append(end)
    if current is not start:
        node = current
        path.append(node)
        node = parent[node]
        while node is not start:
            path.append(node)
            node = parent[node]
    return path
