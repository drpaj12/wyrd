"""The word-level netlist of ``write_json --odin3`` (Yosys schema), reduced to its muxes.

Reads the file only; never imports odin3. Mux cell types are the ones Odin III has before ``lower``:
``$mux``, ``$pmux`` and ``$shiftx`` (the registry has no ``$bmux`` or ``$demux``).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

Bit = int | str
Arm = tuple[Bit, ...]
CHAIN_TYPES = ("$mux", "$pmux")
MUX_TYPES = (*CHAIN_TYPES, "$shiftx")
MAX_JSON_BYTES = 1 << 30
SEQUENTIAL = ("$dff", "$adff", "$sdff", "$aldff", "$dlatch", "$adlatch", "$dlatchsr", "$sr", "$mem")


class NetlistError(Exception):
    """The netlist cannot be used; the message says why, in one line."""


@dataclass(frozen=True)
class MuxCell:
    name: str
    type: str
    width: int
    arms: tuple[Arm, ...]
    select: tuple[Bit, ...]
    out: tuple[Bit, ...]
    src: str

    @property
    def bits(self) -> int:
        """2:1 equivalents: width x (arms - 1)."""
        return self.width * max(len(self.arms) - 1, 0)


@dataclass
class Netlist:
    top: str
    cells: dict[str, dict[str, object]]
    ports_in: dict[int, str] = field(default_factory=dict)
    port_out_bits: set[int] = field(default_factory=set)
    netnames: dict[str, list[Bit]] = field(default_factory=dict)
    driver: dict[int, str] = field(default_factory=dict)
    readers: dict[int, list[tuple[str, str]]] = field(default_factory=lambda: defaultdict(list))
    muxes: dict[str, MuxCell] = field(default_factory=dict)


def _param(cell: dict[str, object], key: str, default: int = 0) -> int:
    params = cell.get("parameters")
    value = params.get(key) if isinstance(params, dict) else None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value and set(value) <= {"0", "1"}:
        return int(value, 2)
    return default


def _conn(cell: dict[str, object], port: str) -> list[Bit]:
    conns = cell.get("connections")
    bits = conns.get(port) if isinstance(conns, dict) else None
    return list(bits) if isinstance(bits, list) else []


def _src(cell: dict[str, object]) -> str:
    attrs = cell.get("attributes")
    src = attrs.get("src") if isinstance(attrs, dict) else None
    return src if isinstance(src, str) else ""


def _is_top(module: dict[str, object]) -> bool:
    attrs = module.get("attributes")
    top = attrs.get("top") if isinstance(attrs, dict) else None
    return top not in (None, 0, "0", "00000000000000000000000000000000")


def _cell_count(module: dict[str, object]) -> int:
    cells = module.get("cells")
    return len(cells) if isinstance(cells, dict) else 0


def _pick_top(modules: dict[str, dict[str, object]]) -> str:
    flagged = [n for n, m in modules.items() if _is_top(m)]
    if flagged:
        return flagged[-1]
    return max(modules, key=lambda n: _cell_count(modules[n]))


def mux_arms(cell: dict[str, object], kind: str) -> tuple[Arm, ...]:
    """The data arms of a mux cell, each a tuple of bits of the cell's output width."""
    width = len(_conn(cell, "Y"))
    if kind == "$mux":
        return (tuple(_conn(cell, "A")), tuple(_conn(cell, "B")))
    if kind == "$pmux":
        b = _conn(cell, "B")
        n = len(_conn(cell, "S"))
        return (tuple(_conn(cell, "A")), *(tuple(b[i * width : (i + 1) * width]) for i in range(n)))
    a = _conn(cell, "A")
    sel = _conn(cell, "B")
    if not any(isinstance(b, int) for b in sel) or width == 0:
        return (tuple(a[:width]),)
    offsets = max(len(a) - width + 1, 1)
    count = min(offsets, 1 << min(len(sel), 30))
    return tuple(tuple(a[k : k + width]) for k in range(count))


def _select_bits(cell: dict[str, object], kind: str) -> tuple[Bit, ...]:
    return tuple(_conn(cell, "B" if kind == "$shiftx" else "S"))


def _mux_cell(name: str, cell: dict[str, object]) -> MuxCell | None:
    kind = cell.get("type")
    if kind not in MUX_TYPES or not isinstance(kind, str):
        return None
    width = len(_conn(cell, "Y"))
    arms = mux_arms(cell, kind)
    if len(arms) < 2 or width == 0:
        return None
    return MuxCell(
        name, kind, width, arms, _select_bits(cell, kind), tuple(_conn(cell, "Y")), _src(cell)
    )


def _index(nl: Netlist) -> None:
    for name, cell in nl.cells.items():
        dirs = cell.get("port_directions")
        conns = cell.get("connections")
        if not isinstance(dirs, dict) or not isinstance(conns, dict):
            continue
        for port, bits in conns.items():
            for bit in bits:
                if not isinstance(bit, int):
                    continue
                if dirs.get(port) == "output":
                    nl.driver[bit] = name
                else:
                    nl.readers[bit].append((name, port))


def _ports(nl: Netlist, module: dict[str, object]) -> None:
    ports = module.get("ports")
    for pname, port in ports.items() if isinstance(ports, dict) else ():
        for bit in port.get("bits", []):
            if not isinstance(bit, int):
                continue
            if port.get("direction") == "input":
                nl.ports_in[bit] = pname
            else:
                nl.port_out_bits.add(bit)
    names = module.get("netnames")
    for nname, net in names.items() if isinstance(names, dict) else ():
        nl.netnames[nname] = list(net.get("bits", []))


def parse(data: object) -> Netlist:
    """Build the model from decoded JSON; raise ``NetlistError``."""
    modules = data.get("modules") if isinstance(data, dict) else None
    if not isinstance(modules, dict) or not modules:
        raise NetlistError("netlist JSON has no modules")
    top = _pick_top(modules)
    module = modules[top]
    cells = module.get("cells")
    nl = Netlist(top, cells if isinstance(cells, dict) else {})
    _ports(nl, module)
    _index(nl)
    for name, cell in nl.cells.items():
        mux = _mux_cell(name, cell)
        if mux is not None:
            nl.muxes[name] = mux
    return nl


def load(path: Path) -> Netlist:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            raise NetlistError(f"{path.name} is over the {MAX_JSON_BYTES} byte limit")
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as e:
        raise NetlistError(f"cannot read {path.name}: {e.strerror or e}") from e
    except ValueError as e:
        raise NetlistError(f"{path.name} is not valid JSON: {e}") from e
    return parse(data)
