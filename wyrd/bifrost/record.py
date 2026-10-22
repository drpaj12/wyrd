"""Recorded signal values (spec 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Recording:
    names: tuple[str, ...]
    widths: tuple[int, ...]
    cycles: tuple[int, ...]
    samples: tuple[tuple[int, ...], ...]
    clocks: tuple[str, ...]
    # Names in `names` that are inputs; the VCD writes them earlier in the cycle than outputs.
    inputs: tuple[str, ...] = ()


class Recorder:
    def __init__(
        self,
        names: Sequence[str],
        widths: Sequence[int],
        clocks: Sequence[str],
        max_samples: int,
        inputs: Sequence[str] = (),
    ) -> None:
        self.names = tuple(names)
        self.widths = tuple(widths)
        self.clocks = tuple(clocks)
        self.inputs = tuple(inputs)
        self.max_samples = max_samples
        self._cycles: list[int] = []
        self._samples: list[tuple[int, ...]] = []

    @property
    def full(self) -> bool:
        return len(self._samples) >= self.max_samples

    def add(self, cycle: int, values: Sequence[int]) -> None:
        if self.full:
            return
        self._cycles.append(cycle)
        self._samples.append(tuple(values))

    def snapshot(self) -> Recording:
        return Recording(
            self.names,
            self.widths,
            tuple(self._cycles),
            tuple(self._samples),
            self.clocks,
            self.inputs,
        )
