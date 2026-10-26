"""Schematic view back end (Qt-free): Yosys-schema JSON from `odin3 write_json` to an SVG.

The drawing is done by netlistsvg (https://github.com/nturley/netlistsvg, MIT), an optional Node.js
program run as a subprocess. Without it every function here still works except `render`, which
raises `ToolMissing` with the install hint. Odin III output feeds netlistsvg directly (after
`proc`); this module only picks what to draw: one module, or the fan-in cone of a net or of an HDL
line, so that a large netlist is shown as a small, readable schematic.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path

MAX_NETLIST_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_CELLS = 300
RENDER_TIMEOUT_S = 120
INSTALL_HINT = (
    "The schematic view needs netlistsvg (MIT, Node.js). Install Node.js, then run "
    "`npm install netlistsvg` in a directory of your choice and set WYRD_NETLISTSVG to its "
    "node_modules/.bin/netlistsvg (and WYRD_NODE to the node program if it is not on PATH)."
)
_OUT_PORTS = ("Y", "Q", "O", "OUT", "Z")
_SRC = re.compile(r"^(?P<file>.+):(?P<l1>\d+)\.\d+-(?:(?P<l2>\d+)\.)?\d+$")

Netlist = dict[str, object]
Module = dict[str, object]


class SchematicError(Exception):
    """The schematic cannot be made; the message says why, in one line."""


class ToolMissing(SchematicError):
    """Node.js or netlistsvg is not installed."""


class TooLarge(SchematicError):
    """The selected part has more cells than the limit; pick a module, a net or a line."""

    def __init__(self, cells: int, limit: int) -> None:
        super().__init__(
            f"{cells} cells is more than the limit of {limit}; "
            "select a smaller module, a net (fan-in cone) or an HDL line"
        )
        self.cells = cells
        self.limit = limit


@dataclass(frozen=True)
class Tools:
    netlistsvg: Path
    node: Path


@dataclass(frozen=True)
class ModuleInfo:
    name: str
    cells: int
    top: bool


def _usable(candidate: str | None) -> Path | None:
    """The resolved executable, or None for a missing file or a Windows one (/mnt/, .exe, .cmd)."""
    if not candidate:
        return None
    try:
        path = Path(candidate).resolve()
    except (OSError, RuntimeError):
        return None
    text = str(path)
    if text.startswith("/mnt/") or text.lower().endswith((".exe", ".cmd", ".bat")):
        return None
    return path if path.is_file() and os.access(path, os.X_OK) else None


def find_tools(env: dict[str, str] | None = None) -> Tools | None:
    """Locate netlistsvg and node: $WYRD_NETLISTSVG / $WYRD_NODE, else PATH. None when absent.

    Each candidate is resolved and must be a Linux executable (not under /mnt/, not .exe/.cmd).
    """
    e = os.environ if env is None else env
    svg = _usable(e.get("WYRD_NETLISTSVG") or shutil.which("netlistsvg", path=e.get("PATH")))
    node = _usable(e.get("WYRD_NODE") or shutil.which("node", path=e.get("PATH")))
    return Tools(svg, node) if svg is not None and node is not None else None


def _dict(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise SchematicError(f"netlist: {what} is not an object")
    return value


def load_netlist(path: Path) -> Netlist:
    """Read a Yosys-schema JSON netlist (Odin III `write_json`); raises SchematicError."""
    try:
        if path.stat().st_size > MAX_NETLIST_BYTES:
            raise SchematicError(f"{path.name} is larger than {MAX_NETLIST_BYTES >> 20} MB")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError, MemoryError) as e:
        raise SchematicError(f"cannot read {path.name}: {e}") from e
    top = _dict(data, "the file")
    if not isinstance(top.get("modules"), dict) or not top["modules"]:
        raise SchematicError(f"{path.name} has no modules (is it a write_json file?)")
    return top


def _modules(netlist: Netlist) -> dict[str, object]:
    return _dict(netlist.get("modules"), "modules")


def modules_dict(netlist: Netlist) -> dict[str, Module]:
    """Module name to module object."""
    return {n: _module(netlist, n) for n in _modules(netlist)}


def _module(netlist: Netlist, name: str) -> Module:
    mods = _modules(netlist)
    if name not in mods:
        raise SchematicError(f"no module {name!r}; the netlist has {', '.join(sorted(mods))}")
    return _dict(mods[name], f"module {name}")


def _is_top(mod: Module) -> bool:
    attrs = mod.get("attributes")
    if not isinstance(attrs, dict):
        return False
    try:
        return int(str(attrs.get("top", "0")), 2) == 1
    except ValueError:
        return False


def modules(netlist: Netlist) -> list[ModuleInfo]:
    """The modules, top first, then by name."""
    out = []
    for name in _modules(netlist):
        mod = _module(netlist, name)
        out.append(ModuleInfo(name, len(_dict(mod.get("cells", {}), "cells")), _is_top(mod)))
    return sorted(out, key=lambda m: (not m.top, m.name))


def _wrap(netlist: Netlist, name: str, mod: Module) -> Netlist:
    """A one-module netlist in which `name` is the top (what netlistsvg draws)."""
    attrs = dict(_dict(mod.get("attributes", {}), "attributes"))
    attrs["top"] = 1
    out = dict(mod)
    out["attributes"] = attrs
    return {"creator": netlist.get("creator", ""), "modules": {name: out}}


def module_view(netlist: Netlist, name: str, max_cells: int = DEFAULT_MAX_CELLS) -> Netlist:
    """The whole module `name`; TooLarge when it has more than `max_cells` cells."""
    mod = _module(netlist, name)
    count = len(_dict(mod.get("cells", {}), "cells"))
    if count > max_cells:
        raise TooLarge(count, max_cells)
    return _wrap(netlist, name, mod)


def _cells(mod: Module) -> dict[str, dict[str, object]]:
    cells = _dict(mod.get("cells", {}), "cells")
    return {k: _dict(v, f"cell {k}") for k, v in cells.items()}


def _bits(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _dir(cell: dict[str, object], port: str) -> str:
    dirs = cell.get("port_directions")
    if isinstance(dirs, dict) and port in dirs:
        return str(dirs[port])
    return "output" if port in _OUT_PORTS else "input"


def _split(cell: dict[str, object]) -> tuple[list[int], list[int]]:
    """Integer input bits and output bits of a cell (constants are strings and are skipped).

    An inout port counts as both an input and an output.
    """
    ins: list[int] = []
    outs: list[int] = []
    conns = _dict(cell.get("connections", {}), "connections")
    for port, bits in conns.items():
        ints = [b for b in _bits(bits) if isinstance(b, int)]
        direction = _dir(cell, port)
        if direction != "output":
            ins.extend(ints)
        if direction in ("output", "inout"):
            outs.extend(ints)
    return ins, outs


def _drivers(cells: dict[str, dict[str, object]]) -> dict[int, str]:
    out: dict[int, str] = {}
    for name, cell in cells.items():
        for bit in _split(cell)[1]:
            out[bit] = name
    return out


def _net_bits(mod: Module, net: str) -> list[int]:
    names = _dict(mod.get("netnames", {}), "netnames")
    if net not in names:
        raise SchematicError(f"no net {net!r} in the module")
    return [b for b in _bits(_dict(names[net], net).get("bits")) if isinstance(b, int)]


def seeds_of_net(mod: Module, net: str) -> list[str]:
    """Cells driving `net`; SchematicError for an unknown net or one no cell drives."""
    drv = _drivers(_cells(mod))
    found = sorted({drv[b] for b in _net_bits(mod, net) if b in drv})
    if not found:
        raise SchematicError(f"net {net!r} is not driven by a cell (a port or a constant)")
    return found


def _same_file(f: str, file: str) -> bool:
    """`f` is `file` or ends with it at a path boundary (`a.v` does not match `data.v`)."""
    return f == file or f.endswith("/" + file)


def _covers(src: str, file: str, line: int) -> bool:
    m = _SRC.match(src)
    if m is None or not _same_file(m["file"], file):
        return False
    first = int(m["l1"])
    last = int(m["l2"]) if m["l2"] else first
    return first <= line <= last


def seeds_of_line(mod: Module, file: str, line: int) -> list[str]:
    """Cells whose `src` attribute covers file:line (the HDL construct, via provenance)."""
    found = []
    for name, cell in _cells(mod).items():
        attrs = cell.get("attributes")
        src = attrs.get("src") if isinstance(attrs, dict) else None
        if isinstance(src, str) and any(_covers(s, file, line) for s in src.split("|")):
            found.append(name)
    if not found:
        raise SchematicError(f"no cell comes from {file}:{line}")
    return sorted(found)


def fanin(mod: Module, seeds: list[str], max_cells: int) -> tuple[list[str], bool]:
    """Seeds plus every cell feeding them, breadth first; stops at `max_cells` (flag: cut)."""
    cells = _cells(mod)
    drv = _drivers(cells)
    keep: dict[str, None] = {}
    queue = deque(seeds)
    cut = False
    while queue:
        name = queue.popleft()
        if name in keep:
            continue
        if len(keep) >= max_cells:
            cut = True
            break
        keep[name] = None
        queue.extend(drv[b] for b in _split(cells[name])[0] if b in drv)
    return list(keep), cut


def _labels(mod: Module) -> dict[int, str]:
    """A readable name for each bit: its first visible net, with [index] for buses."""
    out: dict[int, str] = {}
    names = _dict(mod.get("netnames", {}), "netnames")
    for net, info in names.items():
        bits = _bits(_dict(info, net).get("bits"))
        for i, b in enumerate(bits):
            if isinstance(b, int) and b not in out:
                out[b] = net if len(bits) == 1 else f"{net}[{i}]"
    return out


def _port(direction: str, bit: int, labels: dict[int, str]) -> tuple[str, dict[str, object]]:
    return labels.get(bit, f"n{bit}"), {"direction": direction, "bits": [bit]}


def _used_bits(cells: dict[str, dict[str, object]], keep: list[str]) -> tuple[set[int], set[int]]:
    made: set[int] = set()
    read: set[int] = set()
    for name in keep:
        ins, outs = _split(cells[name])
        read.update(ins)
        made.update(outs)
    return made, read


def cone_view(
    netlist: Netlist, name: str, seeds: list[str], max_cells: int = DEFAULT_MAX_CELLS
) -> tuple[Netlist, bool]:
    """A module made of the fan-in cone of `seeds`; bits made outside become input ports.

    Output ports: the outputs of the seed cells that fit within `max_cells`; seeds beyond the limit
    are dropped and flag the cut. Returns the netlist and whether the cone was cut at
    `max_cells` (cells beyond the cut show up as input ports).
    """
    mod = _module(netlist, name)
    cells = _cells(mod)
    keep, cut = fanin(mod, seeds, max_cells)
    cells_kept = set(keep)
    made, read = _used_bits(cells, keep)
    labels = _labels(mod)
    ports: dict[str, object] = {}
    for bit in sorted(read - made):
        key, port = _port("input", bit, labels)
        ports[key] = port
    shown_seeds = [x for x in seeds if x in cells_kept]
    cut = cut or len(shown_seeds) < len(set(seeds))
    for seed in shown_seeds:
        for bit in _split(cells[seed])[1]:
            key, port = _port("output", bit, labels)
            ports[key] = port
    shown = made | read
    nets = _dict(mod.get("netnames", {}), "netnames")
    kept_nets = {
        n: v
        for n, v in nets.items()
        if (b := [x for x in _bits(_dict(v, n).get("bits")) if isinstance(x, int)])
        and set(b) <= shown
    }
    sub: Module = {
        "attributes": {"top": 1},
        "ports": ports,
        "cells": {k: cells[k] for k in keep},
        "netnames": kept_nets,
    }
    return {"creator": netlist.get("creator", ""), "modules": {name: sub}}, cut


def count_cells(netlist: Netlist) -> int:
    """Cells in the top module of a (one-module) view."""
    return sum(
        len(_dict(_module(netlist, m.name).get("cells", {}), "cells")) for m in modules(netlist)[:1]
    )


def _error_line(stderr: str) -> str:
    lines = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    for ln in lines:
        if "Error" in ln:
            return ln
    return lines[-1] if lines else "no message"


def render(
    view: Netlist,
    out_svg: Path,
    tools: Tools | None,
    work_dir: Path,
    timeout: int = RENDER_TIMEOUT_S,
) -> None:
    """Run netlistsvg on `view`, writing `out_svg`; ToolMissing when it is not installed."""
    if tools is None:
        raise ToolMissing(INSTALL_HINT)
    src = work_dir / f"{out_svg.stem}.json"
    try:
        src.write_text(json.dumps(view), encoding="utf-8")
    except (OSError, ValueError, RecursionError, MemoryError) as e:
        raise SchematicError(f"cannot write {src.name}: {e}") from e
    env = dict(os.environ)
    env["PATH"] = str(tools.node.parent) + os.pathsep + env.get("PATH", "")
    argv = [str(tools.node), str(tools.netlistsvg), str(src), "-o", str(out_svg)]
    try:
        done = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise SchematicError(f"netlistsvg took more than {timeout} s; show a smaller part") from e
    except OSError as e:
        raise ToolMissing(f"cannot run netlistsvg: {e}. {INSTALL_HINT}") from e
    if done.returncode == 0 and not out_svg.is_file():
        raise SchematicError("netlistsvg wrote no output file")
    if done.returncode != 0:
        raise SchematicError(
            f"netlistsvg failed (exit {done.returncode}): {_error_line(done.stderr)}"
        )


def find_netlist(run_dir: Path) -> Path | None:
    """A Yosys-schema JSON netlist inside a run directory (`write_json` output), if any."""
    skip = {"summary.json", "attribution.json", "inputs.json", "time.json"}
    for path in sorted(run_dir.rglob("*.json")):
        if path.name in skip or not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                head = f.read(4096)
        except (OSError, UnicodeDecodeError):
            continue
        if '"modules"' in head and '"creator"' in head:
            return path
    return None
