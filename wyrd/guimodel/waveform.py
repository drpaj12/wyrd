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


MAX_VIEW_SAMPLES = 100_000


def view_start(count: int, limit: int = MAX_VIEW_SAMPLES) -> int:
    """First sample shown when only the last `limit` of `count` samples are kept in the view."""
    return max(0, count - max(1, limit))


def visible_range(
    left: float, right: float, name_width: int, cell_width: int, first: int, count: int
) -> tuple[int, int]:
    """Samples [lo, hi) whose cells touch the pixel span left..right, clamped to first..count."""
    lo = first + int((left - name_width) // cell_width)
    hi = first + int((right - name_width) // cell_width) + 1
    high = max(first, min(count, hi))
    return min(max(first, lo), high), high


def rows_from_recording(rec: Recording, start: int = 0) -> list[WaveRow]:
    """One row per name from sample `start` on (older samples stay in the recording only)."""
    samples = rec.samples[start:]
    return [
        WaveRow(name, rec.widths[i], tuple(sample[i] for sample in samples))
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
