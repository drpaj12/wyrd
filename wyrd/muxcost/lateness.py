"""Select lateness of a mux from a routed run: select pins against data pins.

Input is VPR's ``report_net_timing.csv`` (``--generate_net_timing_report on``) of a routed run of
the BLIF this report wrote (the hash names must be the same). A pin's criticality is
``(s_max - slack) / (s_max - s_min)`` over the finite pin slacks of that report: 1 is the worst
pin of the design, 0 the most relaxed. A mux takes the worst (largest) criticality over its select
pins and over its data pins (greedy worst over pins); the select pin shown is one of the tied
worst, chosen at random with a fixed seed.

A LUT pin is a select pin when its net is a leaf of the select cone of the mux (the nets in the
fan-in of its select bits, up to the first net that exists in the mapped netlist) and is not itself
a data arm of the mux; every other input pin of the mux's LUTs is a data pin.
"""

from __future__ import annotations

import csv
import math
import random
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from wyrd.muxcost.blif import Blif
from wyrd.muxcost.logical import Logical
from wyrd.muxcost.netlist import SEQUENTIAL, Netlist

SEED = 20261114
CONE_LIMIT = 20000
MAX_CSV_BYTES = 1 << 30
_PIN = re.compile(r"^(.*)\.in\[(\d+)\]$")


class TimingFileError(Exception):
    """The timing report cannot be used; the message says why, in one line."""


@dataclass(frozen=True)
class Lateness:
    sel_crit: float
    data_crit: float
    late: float
    witness: str


def _sink_pins(field: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for item in field.split(";"):
        parts = item.rsplit(",", 2)
        if len(parts) != 3:
            continue
        try:
            slack = float(parts[1]) * 1e9
        except ValueError:
            continue
        if math.isfinite(slack):
            out.append((parts[0], slack))
    return out


def read_pin_slacks(path: Path) -> dict[tuple[str, int], float]:
    """(LUT atom, input index) to slack in ns, for each sink pin ``<atom>.in[<i>]``."""
    csv.field_size_limit(min(MAX_CSV_BYTES, sys.maxsize))
    out: dict[tuple[str, int], float] = {}
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                for pin, slack in _sink_pins(row.get("sinks", "")):
                    m = _PIN.match(pin)
                    if m:
                        out[(m.group(1), int(m.group(2)))] = slack
    except (OSError, csv.Error, UnicodeDecodeError) as e:
        raise TimingFileError(f"cannot read {path.name}: {e}") from e
    return out


def criticality(slacks: dict[tuple[str, int], float]) -> dict[tuple[str, int], float]:
    if not slacks:
        return {}
    lo, hi = min(slacks.values()), max(slacks.values())
    span = hi - lo
    return {k: (1.0 if span <= 0 else (hi - s) / span) for k, s in slacks.items()}


def bit_names(nl: Netlist) -> dict[int, list[str]]:
    """Candidate mapped-netlist names of each net bit."""
    out: dict[int, list[str]] = {}
    for name, bits in nl.netnames.items():
        for i, bit in enumerate(bits):
            if isinstance(bit, int):
                cands = [f"{name}[{i}]"] + ([name] if len(bits) == 1 else [])
                out.setdefault(bit, []).extend(cands)
    return out


def _visible(names: dict[int, list[str]], nets: set[str], bit: int) -> list[str]:
    return [n for n in names.get(bit, ()) if n in nets]


def _inputs(nl: Netlist, cell: str) -> list[int]:
    spec = nl.cells[cell]
    dirs = spec.get("port_directions")
    conns = spec.get("connections")
    if not isinstance(dirs, dict) or not isinstance(conns, dict):
        return []
    return [
        b for p, bits in conns.items() if dirs.get(p) == "input" for b in bits if isinstance(b, int)
    ]


def cone_leaves(
    nl: Netlist, bits: tuple[int, ...], names: dict[int, list[str]], nets: set[str]
) -> set[str]:
    """Mapped-netlist nets in the fan-in of ``bits``, stopping at the first one that exists."""
    leaves: set[str] = set()
    seen: set[int] = set()
    stack = list(bits)
    while stack and len(seen) < CONE_LIMIT:
        bit = stack.pop()
        if bit in seen:
            continue
        seen.add(bit)
        vis = _visible(names, nets, bit)
        driver = nl.driver.get(bit)
        if vis:
            leaves.update(vis)
        elif driver is not None and nl.cells[driver].get("type") not in SEQUENTIAL:
            stack.extend(_inputs(nl, driver))
    return leaves


def arm_nets(mux: Logical, names: dict[int, list[str]], nets: set[str]) -> set[str]:
    out: set[str] = set()
    for arm in mux.leaf_arms:
        for bit in arm:
            if isinstance(bit, int):
                out.update(_visible(names, nets, bit))
    return out


def _worst(pins: dict[str, float]) -> tuple[float, list[str]]:
    top = max(pins.values())
    return top, sorted(p for p, c in pins.items() if round(c, 9) == round(top, 9))


def lateness(
    luts: frozenset[str],
    blif: Blif,
    crit: dict[tuple[str, int], float],
    sel_nets: set[str],
    data_nets: set[str],
    rng: random.Random,
) -> Lateness | None:
    sel: dict[str, float] = {}
    data: dict[str, float] = {}
    for lut in sorted(luts):
        for i, net in enumerate(blif.luts[lut]):
            c = crit.get((lut, i))
            if c is None:
                continue
            (sel if net in sel_nets and net not in data_nets else data)[f"{lut}.in[{i}]"] = c
    if not sel or not data:
        return None
    s_top, tied = _worst(sel)
    d_top, _ = _worst(data)
    return Lateness(s_top, d_top, s_top - d_top, rng.choice(tied))
