"""Waveform data and value text, Qt-free (spec 7.1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from wyrd.bifrost.record import Recording


@dataclass(frozen=True)
class Segment:
    start: int
    end: int
    value: int


@dataclass(frozen=True)
class WaveRow:
    name: str
    width: int
    values: tuple[int, ...]


def rows_from_recording(rec: Recording) -> list[WaveRow]:
    return [
        WaveRow(name, rec.widths[i], tuple(sample[i] for sample in rec.samples))
        for i, name in enumerate(rec.names)
    ]


def segments(values: Sequence[int]) -> list[Segment]:
    out: list[Segment] = []
    for index, value in enumerate(values):
        if out and out[-1].value == value:
            out[-1] = Segment(out[-1].start, index + 1, value)
        else:
            out.append(Segment(index, index + 1, value))
    return out


def format_value(value: int, width: int, radix: Literal["hex", "dec", "bin"]) -> str:
    if radix == "bin":
        return format(value, "b").zfill(width)
    if radix == "hex":
        return format(value, "x").zfill((width + 3) // 4)
    return str(value)


def parse_int_text(text: str, width: int) -> int:
    value = int(text.strip(), 0)
    if value < 0 or value >= 1 << width:
        raise ValueError(f"{text!r} does not fit in {width} bits")
    return value
