"""S1 `odin3-sim-vectors` text files: read, write, random (spec 8)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wyrd.bifrost.errors import VectorError
from wyrd.bifrost.record import Recording
from wyrd.bifrost.types import Signal

if TYPE_CHECKING:
    from wyrd.bifrost.session import BifrostSession

MAX_LINES = 1_048_576
_PORT_WORDS = ("input", "clock", "output")


@dataclass(frozen=True)
class VectorFile:
    rows: tuple[tuple[int, ...], ...]


def session_ports(session: BifrostSession) -> tuple[tuple[Signal, ...], tuple[Signal, ...]]:
    ports = tuple(s for s in session.signals if s.kind in ("input", "clock"))
    return ports, session.outputs


def data_ports(ports: Sequence[Signal]) -> tuple[Signal, ...]:
    return tuple(p for p in ports if p.kind == "input")


def _port_lines(ports: Sequence[Signal], outputs: Sequence[Signal]) -> list[str]:
    lines = [
        f"# clock {p.name} 0" if p.kind == "clock" else f"# input {p.name} {p.width}"
        for p in ports
    ]
    return lines + [f"# output {o.name} {o.width}" for o in outputs]


def _bits(values: Sequence[int], signals: Sequence[Signal]) -> str:
    text = "".join(f"{v:0{s.width}b}" for v, s in zip(values, signals, strict=True))
    return text or "-"


def _output_values(rec: Recording, outputs: Sequence[Signal], index: int) -> list[int]:
    sample = rec.samples[index + 1]
    try:
        return [sample[rec.names.index(o.name)] for o in outputs]
    except ValueError:
        raise ValueError("the recording does not hold every output port") from None


def format_vectors(
    vf: VectorFile,
    ports: Sequence[Signal],
    outputs: Sequence[Signal] = (),
    *,
    recording: Recording | None = None,
    title: str = "wyrd",
    seed: int = 0,
) -> str:
    data = data_ports(ports)
    lines = [f"# {title} seed {seed} cycles {len(vf.rows)}", *_port_lines(ports, outputs)]
    for c, row in enumerate(vf.rows):
        line = f"{c} {_bits(row, data)}"
        if recording is not None:
            line += " " + _bits(_output_values(recording, outputs, c), outputs)
        lines.append(line)
    return "\n".join(lines) + "\n"


def random_vectors(ports: Sequence[Signal], cycles: int, seed: int) -> VectorFile:
    if cycles < 0:
        raise ValueError("cycles must be >= 0")
    rng = random.Random(seed)
    data = data_ports(ports)
    return VectorFile(tuple(tuple(rng.getrandbits(p.width) for p in data) for _ in range(cycles)))


def _is_port_line(words: list[str]) -> bool:
    return len(words) >= 2 and words[0] == "#" and words[1] in _PORT_WORDS


def _check_port_line(line: str, seen: int, expected: list[str], number: int) -> None:
    want = expected[seen] if seen < len(expected) else "no port line"
    if line != want:
        raise VectorError(
            number, f"port line `{line}` does not match the design: expected `{want}`"
        )


def _split_row(word: str, data: Sequence[Signal], number: int) -> tuple[int, ...]:
    total = sum(p.width for p in data)
    if total == 0:
        if word != "-":
            raise VectorError(number, "expected `-`: the design has no input bit")
        return ()
    if len(word) != total or set(word) - {"0", "1"}:
        raise VectorError(number, f"expected {total} input bits of 0 and 1, found `{word}`")
    values: list[int] = []
    pos = 0
    for p in data:
        values.append(int(word[pos : pos + p.width], 2))
        pos += p.width
    return tuple(values)


def parse_vectors(
    text: str,
    ports: Sequence[Signal],
    outputs: Sequence[Signal] = (),
    name: str = "<vectors>",
) -> VectorFile:
    del name
    data = data_ports(ports)
    expected = _port_lines(ports, outputs)
    rows: list[tuple[int, ...]] = []
    seen = 0
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        words = line.split()
        if not words:
            continue
        if words[0].startswith("#"):
            if _is_port_line(words):
                _check_port_line(line.strip(), seen, expected, number)
                seen += 1
            continue
        if len(rows) >= MAX_LINES:
            raise VectorError(number, f"more than {MAX_LINES} vector lines")
        if len(words) not in (2, 3):
            raise VectorError(number, "expected `<cycle> <inputs> [<outputs>]`")
        if words[0] != str(len(rows)):
            raise VectorError(number, f"expected cycle {len(rows)}, found `{words[0]}`")
        rows.append(_split_row(words[1], data, number))
    return VectorFile(tuple(rows))
