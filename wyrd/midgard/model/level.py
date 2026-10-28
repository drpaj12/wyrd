"""The level state machine (port of LevelScreen's logic; spec 5.7, 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from wyrd.midgard.model.car import Car
from wyrd.midgard.model.clock import ticks_to_seconds
from wyrd.midgard.model.controllers import LightController
from wyrd.midgard.model.levelxml import LevelData
from wyrd.midgard.model.logic import LevelLogic
from wyrd.midgard.model.sensors import SensorEditor, SensorSet
from wyrd.midgard.model.townmap import TownMap


class Phase(Enum):
    EDIT = 1
    RUN = 2
    PAUSE = 3
    DONE = 4


@dataclass(frozen=True)
class LevelResult:
    passed: int
    failed: int
    crashed: int
    forced: int
    ticks: int
    cars: int

    @property
    def seconds(self) -> int:
        return ticks_to_seconds(self.ticks)


class Level:
    def __init__(self, data: LevelData, sensors: SensorSet) -> None:
        self.data = data
        self.phase = Phase.EDIT
        self.ticks = 0
        self.town = TownMap(data)
        self.cars: list[Car] = self.town.make_cars(data)
        self.sensors = sensors
        sensors.attach(self.town.grid)
        self.editor = SensorEditor(sensors, self.town.grid)
        self.logic = LevelLogic()
        self.controllers: list[LightController] = []

    def start(self, controllers: Sequence[LightController]) -> None:
        if self.phase is not Phase.EDIT:
            raise ValueError("a level can only be started from the EDIT phase")
        if len(controllers) != len(self.town.controls):
            raise ValueError(f"need {len(self.town.controls)} controllers, got {len(controllers)}")
        self.controllers = list(controllers)
        for c in self.controllers:
            c.start()
        self.phase = Phase.RUN

    def toggle_pause(self) -> None:
        if self.phase is Phase.RUN:
            self.phase = Phase.PAUSE
        elif self.phase is Phase.PAUSE:
            self.phase = Phase.RUN

    def tick(self) -> bool:
        if self.phase is not Phase.RUN:
            return False
        self.ticks += 1
        done = self.logic.update(self.cars, self.town, self.controllers, self.sensors)
        if done:
            self.phase = Phase.DONE
        return done

    def step_once(self) -> bool:
        if self.phase is not Phase.PAUSE:
            return False
        self.phase = Phase.RUN
        done = self.tick()
        if self.phase is Phase.RUN:
            self.phase = Phase.PAUSE
        return done

    def result(self) -> LevelResult:
        forced = self.town.forced_cars
        return LevelResult(
            passed=max(0, self.logic.success_raw - forced),
            failed=forced + self.logic.crash_count,
            crashed=self.logic.crash_count,
            forced=forced,
            ticks=self.ticks,
            cars=len(self.cars),
        )

    def close_controllers(self) -> None:
        for c in self.controllers:
            c.close()
