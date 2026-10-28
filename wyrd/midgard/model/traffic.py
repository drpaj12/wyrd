"""Traffic control of one intersection (port of TrafficControl, logic only)."""

from __future__ import annotations

from collections.abc import Sequence

from wyrd.midgard.model.grid import Direction, Node, SignalState

PROCEED_NORTH, PROCEED_SOUTH, PROCEED_EAST, PROCEED_WEST, INTERNAL = 0, 1, 2, 3, 4
_ORDER = (Direction.N, Direction.S, Direction.E, Direction.W)


class TrafficControl:
    def __init__(self, kind: str, index: int) -> None:
        self.kind = kind
        self.index = index
        self.entries: dict[Direction, Node | None] = dict.fromkeys(_ORDER)
        self.internal: tuple[Node, ...] = ()
        self.facing: dict[Direction, SignalState] = dict.fromkeys(_ORDER, SignalState.STOP)

    def signal_when(self, location: int) -> SignalState:
        if 0 <= location < len(_ORDER):
            return self.facing[_ORDER[location]]
        return SignalState.NO_SIGNAL

    def set_signals(self, n: SignalState, s: SignalState, e: SignalState, w: SignalState) -> None:
        self.facing = {Direction.N: n, Direction.S: s, Direction.E: e, Direction.W: w}

    def read_sensors(self) -> int:
        """The 8 light-sensor bits (spec 5.3): W N E S entries, then LR LL UR UL."""
        w, n, e, s = (self.entries[d] for d in (Direction.W, Direction.N, Direction.E, Direction.S))
        nodes: list[Node | None] = [w, n, e, s]
        nodes += [self.internal[3], self.internal[2], self.internal[1], self.internal[0]]
        word = 0
        for node in nodes:
            word = (word << 1) | (1 if node is not None and node.car is not None else 0)
        return word

    def attach(self, entries: dict[Direction, Node | None], internal: Sequence[Node]) -> None:
        self.entries = dict(entries)
        self.internal = tuple(internal)
        for loc, d in enumerate(_ORDER):
            node = self.entries.get(d)
            if node is not None:
                node.control = self
                node.location = loc
        for node in self.internal:
            node.control = self
            node.location = INTERNAL
