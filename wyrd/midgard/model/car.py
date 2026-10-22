"""Car state (port of Car). Movement methods are added with the tick logic."""

from __future__ import annotations

from enum import Enum

from wyrd.midgard.model.grid import Direction, Node


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
