"""One game tick (port of LevelLogic.update; spec 5.6)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from wyrd.midgard.model.car import (
    Car,
    CarState,
    animation_direction_of,
    check_for_crash,
    direction_on_arrival,
)
from wyrd.midgard.model.grid import (
    CORNER_TYPES,
    END_TYPES,
    TILE,
    Node,
    SignalState,
    decode_signal,
)
from wyrd.midgard.model.sensors import SensorSet
from wyrd.midgard.model.townmap import TownMap

if TYPE_CHECKING:
    from wyrd.midgard.model.controllers import LightController

_FORCED = (SignalState.GO_RIGHT, SignalState.GO_LEFT, SignalState.GO_FORWARD)


def set_current_point(car: Car, frm: Node | None, to: Node) -> None:
    car.direction = direction_on_arrival(frm, to)
    car.current = to
    if frm is not None:
        frm.car = None
    to.car = car
    if to is car.end or to.type in END_TYPES:
        if frm is not None:
            frm.car = None
        to.car = None
        car.done = True
        car.current = None


def car_starts(car: Car, town: TownMap) -> None:
    set_current_point(car, None, car.start)
    town.set_path(car, car.start, None)
    current = car.current
    if current is not None:
        car.px, car.py = (current.x - 1) * TILE, (current.y - 1) * TILE
        car.animation_direction = animation_direction_of(None, current)
    car.started = True


def _pop(car: Car) -> Node:
    if not car.path:
        raise RuntimeError("car path is empty")
    return car.path.pop()


def update_spot(car: Car) -> None:
    nxt = _pop(car)
    set_current_point(car, car.current, nxt)


def car_in_front(car: Car, nxt: Node) -> bool:
    other = nxt.car
    if other is None:
        return False
    if other.direction == car.direction:
        return True
    return other.current is not None and other.current.type in CORNER_TYPES


def _advance(car: Car, cur: Node, via: Node | None, town: TownMap) -> None:
    nxt = _pop(car)
    if car_in_front(car, nxt):
        car.path.append(nxt)
        car.state = CarState.STOPPED
        return
    car.animation_direction = animation_direction_of(cur, nxt)
    town.set_path(car, cur, via)


def free_movement(car: Car, cur: Node, town: TownMap) -> None:
    _advance(car, cur, None, town)


def forced_movement(car: Car, cur: Node, sig: SignalState, town: TownMap) -> None:
    if car.direction is None:
        car.state = CarState.STOPPED
        return
    via = town.get_turn(cur, sig, car.direction)
    if via is None:
        car.state = CarState.STOPPED
        return
    _advance(car, cur, via, town)


class LevelLogic:
    def __init__(self) -> None:
        self.time_step = 0
        self.done_count = 0
        self.success_raw = 0
        self.crash_count = 0

    def update(
        self,
        cars: Sequence[Car],
        town: TownMap,
        controllers: Sequence[LightController],
        sensors: SensorSet,
    ) -> bool:
        self.time_step += 1
        general = sensors.general_word()
        for tc, ctl in zip(town.controls, controllers, strict=True):
            n, s, e, w = ctl.step(tc.read_sensors(), general)
            tc.set_signals(decode_signal(n), decode_signal(s), decode_signal(e), decode_signal(w))
        queue = [c for c in cars if c.start_time == self.time_step or c.running]
        for car in queue:
            self._move(car, town)
        self.check_crashes(cars)
        return self.done_count >= len(cars)

    def _move(self, car: Car, town: TownMap) -> None:
        car.animate()
        if car.start_time == self.time_step:
            car_starts(car, town)
            car.state = CarState.MOVING
        elif car.at_next_grid():
            self._at_grid(car, town)

    def _at_grid(self, car: Car, town: TownMap) -> None:
        if car.state is not CarState.STOPPED:
            update_spot(car)
            if car.done:
                self.done_count += 1
                self.success_raw += 1
                return
        cur = car.current
        if cur is None:
            return
        sig = cur.traffic_signal()
        if sig in (SignalState.NO_SIGNAL, SignalState.GO):
            car.state = CarState.MOVING
            free_movement(car, cur, town)
        elif sig in _FORCED:
            car.state = CarState.MOVING
            forced_movement(car, cur, sig, town)
        else:
            car.state = CarState.STOPPED

    def check_crashes(self, cars: Sequence[Car]) -> None:
        i = 0
        while i < len(cars):
            if cars[i].running:
                for j in range(i + 1, len(cars)):
                    if cars[j].running and check_for_crash(cars[i], cars[j]):
                        cars[i].crash()
                        i += 1
                        cars[j].crash()
                        self.done_count += 2
                        self.crash_count += 2
                        break
            i += 1
