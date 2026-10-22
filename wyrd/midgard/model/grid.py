"""Grid tile types, directions, signal states and the map node (port of GridType, GridNode)."""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wyrd.midgard.model.car import Car
    from wyrd.midgard.model.sensors import Sensor
    from wyrd.midgard.model.traffic import TrafficControl

TILE = 64


class GridType(Enum):
    START_NEDGE2S = 1
    START_SEDGE2N = 2
    START_EEDGE2W = 3
    START_WEDGE2E = 4
    END_S2SEDGE = 5
    END_N2NEDGE = 6
    END_W2WEDGE = 7
    END_E2EEDGE = 8
    STRAIGHT_ROAD_N2N = 9
    STRAIGHT_ROAD_S2S = 10
    STRAIGHT_ROAD_E2E = 11
    STRAIGHT_ROAD_W2W = 12
    CORNER_ROAD_W2S = 13
    CORNER_ROAD_N2E = 14
    CORNER_ROAD_E2S = 15
    CORNER_ROAD_N2W = 16
    CORNER_ROAD_S2W = 17
    CORNER_ROAD_E2N = 18
    CORNER_ROAD_S2E = 19
    CORNER_ROAD_W2N = 20
    INTER_TURN_N2EN = 21
    INTER_TURN_W2NW = 22
    INTER_TURN_S2WS = 23
    INTER_TURN_E2SE = 24
    NON_ROAD = 25


END_TYPES = frozenset(
    {
        GridType.END_S2SEDGE,
        GridType.END_N2NEDGE,
        GridType.END_E2EEDGE,
        GridType.END_W2WEDGE,
    }
)
CORNER_TYPES = frozenset(t for t in GridType if t.name.startswith("CORNER_ROAD_"))
START_TYPES = frozenset(t for t in GridType if t.name.startswith("START_"))


class Direction(Enum):
    N = 1
    S = 2
    E = 3
    W = 4


class SignalState(IntEnum):
    STOP = 0
    GO_FORWARD = 1
    GO_LEFT = 2
    GO_RIGHT = 3
    GO = 4
    NO_SIGNAL = 5


def decode_signal(code: int) -> SignalState:
    """Light output code to a signal; codes 5 to 7 (and anything else) read as STOP."""
    if 0 <= code <= 4:
        return SignalState(code)
    return SignalState.STOP


class Node:
    """One map tile. Identity hashing on purpose (no __eq__)."""

    def __init__(self, x: int, y: int, type: GridType) -> None:
        self.x = x
        self.y = y
        self.type = type
        self.north: Node | None = None
        self.south: Node | None = None
        self.east: Node | None = None
        self.west: Node | None = None
        self.sensor: Sensor | None = None
        self.ending_counter: int = 0
        self.control: TrafficControl | None = None
        self.location: int = -1
        self.car: Car | None = None

    def traffic_signal(self) -> SignalState:
        if self.control is None or self.location == -1:
            return SignalState.NO_SIGNAL
        return self.control.signal_when(self.location)

    def __repr__(self) -> str:
        return f"Node({self.x}, {self.y}, {self.type.name})"
