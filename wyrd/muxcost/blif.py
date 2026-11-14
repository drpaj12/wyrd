"""The mapped netlist (BLIF with hash names): its LUTs and the nets they read.

Reads the file only. ``.names`` with at least one input is a LUT; its atom name in VPR is its output
net, and its input ``i`` is VPR's pin ``in[i]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class BlifError(Exception):
    """The BLIF cannot be used; the message says why, in one line."""


@dataclass
class Blif:
    luts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    nets: set[str] = field(default_factory=set)


def parse(text: str) -> Blif:
    out = Blif()
    for line in text.replace("\\\n", " ").splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0] in (".inputs", ".outputs"):
            out.nets.update(words[1:])
        elif words[0] == ".names" and len(words) >= 2:
            out.nets.update(words[1:])
            if len(words) >= 3:
                out.luts[words[-1]] = tuple(words[1:-1])
        elif words[0] == ".latch" and len(words) >= 3:
            out.nets.update(words[1:3])
        elif words[0] == ".subckt":
            out.nets.update(w.split("=", 1)[1] for w in words[2:] if "=" in w)
    return out


def read(path: Path) -> Blif:
    try:
        return parse(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise BlifError(f"cannot read {path.name}: {e.strerror or e}") from e
