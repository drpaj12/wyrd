"""Car state (port of Car). Movement methods are added with the tick logic."""

from __future__ import annotations

from enum import Enum

from wyrd.midgard.model.grid import Direction, GridType, Node

SPEED = 4
TILE_PX = 64

_START_DIRECTION = {
    GridType.START_NEDGE2S: Direction.S,
    GridType.START_SEDGE2N: Direction.N,
    GridType.START_EEDGE2W: Direction.W,
    GridType.START_WEDGE2E: Direction.E,
}
_CORNER_DIRECTION = {
    GridType.CORNER_ROAD_W2S: Direction.S,
    GridType.CORNER_ROAD_E2S: Direction.S,
    GridType.CORNER_ROAD_N2E: Direction.E,
    GridType.CORNER_ROAD_S2E: Direction.E,
    GridType.CORNER_ROAD_N2W: Direction.W,
    GridType.CORNER_ROAD_S2W: Direction.W,
    GridType.CORNER_ROAD_E2N: Direction.N,
    GridType.CORNER_ROAD_W2N: Direction.N,
}


def _by_position(frm: Node, to: Node) -> Direction | None:
    if to.x > frm.x:
        return Direction.E
    if to.x < frm.x:
        return Direction.W
    if to.y > frm.y:
        return Direction.N
    if to.y < frm.y:
        return Direction.S
    return None


def direction_on_arrival(frm: Node | None, to: Node) -> Direction | None:
    """Heading after arriving on `to` (set_car_direction): uses the type of `to`."""
    if frm is None:
        return _START_DIRECTION.get(to.type)
    corner = _CORNER_DIRECTION.get(to.type)
    return corner if corner is not None else _by_position(frm, to)


def animation_direction_of(frm: Node | None, to: Node) -> Direction | None:
    """Direction of travel on screen: uses the type of `frm` (ported as is)."""
    if frm is None:
        return _START_DIRECTION.get(to.type)
    corner = _CORNER_DIRECTION.get(frm.type)
    return corner if corner is not None else _by_position(frm, to)


def check_for_crash(a: Car, b: Car) -> bool:
    ax0, ax1, ay0, ay1 = a.px + 10, a.px + 54, a.py + 10, a.py + 54
    bx0, bx1, by0, by1 = b.px + 10, b.px + 54, b.py + 10, b.py + 54
    corners = ((bx0, by0), (bx1, by0), (bx0, by1), (bx1, by1))
    return any(ax0 <= x <= ax1 and ay0 <= y <= ay1 for x, y in corners)


class CarState(Enum):
    STOPPED = 1
    MOVING = 2


class Car:
    def __init__(self, start: Node, end: Node, start_time: int) -> None:
        self.start = start
        self.end = end
        self.original_end = end
        self.start_time = start_time
        self.current: Node | None = None
        self.way_point: Node | None = None
        self.path: list[Node] = []
        self.started = False
        self.done = False
        self.crashed = False
        self.forced_turned = False
        self.direction: Direction | None = None
        self.animation_direction: Direction | None = None
        self.state = CarState.STOPPED
        self.px = 0
        self.py = 0

    @property
    def running(self) -> bool:
        return self.started and not self.done

    def animate(self) -> None:
        if self.state is not CarState.MOVING:
            return
        d = self.animation_direction
        if d is Direction.N:
            self.py += SPEED
        elif d is Direction.S:
            self.py -= SPEED
        elif d is Direction.E:
            self.px += SPEED
        elif d is Direction.W:
            self.px -= SPEED

    def at_next_grid(self) -> bool:
        return self.px % TILE_PX == 0 and self.py % TILE_PX == 0

    def crash(self) -> None:
        if self.current is not None:
            self.current.car = None
        self.crashed = True
        self.done = True
        self.current = None
