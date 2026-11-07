"""OpenROAD / OpenSTA power: script generation and report parsing (no read_vcd needed)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wyrd.bifrost.power.vcdact import NetAct

_TOTAL = re.compile(r"^Total\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)", re.M)
_INST = re.compile(
    r"^\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+([0-9.e+-]+)\s+(\S+)\s*$", re.M
)
_ACT = re.compile(r"^ACT set=(\d+) nets=(\d+)", re.M)


@dataclass
class AsicPower:
    internal_w: float
    switching_w: float
    leakage_w: float
    total_w: float
    clock_w: float = 0.0
    activity_set: int = 0
    nets: int = 0
    instances: dict[str, tuple[float, float]] = field(default_factory=dict)  # dynamic, static

    @property
    def dynamic_w(self) -> float:
        return self.total_w - self.leakage_w

    @property
    def matched_fraction(self) -> float:
        return self.activity_set / self.nets if self.nets else 0.0


def write_activity_table(path: Path, acts: Mapping[str, NetAct], skip: set[str]) -> int:
    """One line per net: ``name duty activity``. A net toggling every half cycle is a clock."""
    lines = [
        f"{n} {a.p1:.6f} {a.activity:.6f}"
        for n, a in acts.items()
        if n not in skip and a.activity < 1.9
    ]
    path.write_text("\n".join(lines) + "\n")
    return len(lines)


def sta_script(lib: Path, odb: Path, clock_port: str, period_ns: float, table: Path) -> str:
    """The Tcl that sets per-net activity from ``table`` and reports power."""
    return f"""read_liberty {lib}
read_db {odb}
create_clock -name clk -period {period_ns} [get_ports {clock_port}]
set_wire_rc -signal -layer met2
set_wire_rc -clock -layer met5
estimate_parasitics -placement
set_propagated_clock [all_clocks]
set nset 0
set f [open {table}]
while {{[gets $f line] >= 0}} {{
  lassign $line nm duty act
  set n [get_nets -quiet $nm]
  if {{$n eq ""}} continue
  set drv [get_pins -quiet -of_objects $n -filter "direction == output"]
  if {{$drv ne ""}} {{
    set_power_activity -pins $drv -activity $act -duty $duty
    incr nset
  }} elseif {{[get_ports -quiet $nm] ne ""}} {{
    set_power_activity -input_ports [get_ports $nm] -activity $act -duty $duty
    incr nset
  }}
}}
close $f
puts "ACT set=$nset nets=[llength [get_nets *]]"
report_power
puts INST_BEGIN
report_power -instances [get_cells *]
exit
"""


def _f(text: str) -> float:
    return float(text)


def parse_sta_power(stdout: str) -> AsicPower:
    """Totals from ``report_power`` (Internal + Switching + Leakage) and the instance table."""
    stdout, _, inst_text = stdout.partition("INST_BEGIN")
    m = _TOTAL.search(stdout)
    if m is None:
        raise ValueError("no power total in the OpenROAD output")
    p = AsicPower(_f(m.group(1)), _f(m.group(2)), _f(m.group(3)), _f(m.group(4)))
    a = _ACT.search(stdout)
    if a:
        p.activity_set, p.nets = int(a.group(1)), int(a.group(2))
    for im in _INST.finditer(inst_text):
        intern, sw, leak = _f(im.group(1)), _f(im.group(2)), _f(im.group(3))
        p.instances[im.group(5)] = (intern + sw, leak)
    p.clock_w = sum(d + s for k, (d, s) in p.instances.items() if is_clock_cell(k))
    return p


def is_clock_cell(inst: str) -> bool:
    """Clock-tree cells the flow inserts (CTS buffers and loads)."""
    return inst.startswith(("clkbuf_", "clkload", "clkbuf"))
