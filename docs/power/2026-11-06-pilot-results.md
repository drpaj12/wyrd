# Bifrost power pilot results (2026-11-06)

Method and limits: `docs/specs/2026-11-06-bifrost-power-design.md`. Numbers come from each design's own
Mimir testbench (all three print PASS on the netlists used). Descriptive only, no hypothesis.
Odin III binary `odin3/build/rel-main3/odin3` (before PR 385); the testbenches run in iverilog, so the
Odin 4-state question does not arise for the main path.

## In plain English

Each design was synthesised to LUTs (FPGA) and, from the archived silicon-flow runs, to sky130 cells
(ASIC). The testbench was run against each netlist, every net's toggling was measured, and that toggling
was fed to VPR's power model (FPGA, 45 nm) and to OpenROAD's power report (ASIC, sky130 tt 1.8 V). All
three designs are mostly idle in their testbenches, so dynamic power is small. The FPGA and ASIC numbers
are at different clock frequencies (VPR uses 1/critical path, the ASIC uses the testbench clock), so the
energy per cycle is the number to compare. Every net of the FPGA netlist took part (matched fraction 1.0);
on ASIC 96.5 to 98.5 percent of the nets carry a measured activity (the rest are tie cells and the like).

## Per design (milliwatts)

| design | cycles | FPGA total | dyn | static | clock | vectorless (ACE2) total | FPGA MHz | FPGA pJ/cycle |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mmuart | 94,433 | 1.689 | 1.011 | 0.678 | 0.267 | 2.020 | 341.7 | 4.94 |
| verilog_cordic_core | 220 | 25.44 | 20.46 | 4.984 | 0.543 | 14.15 | 188.3 | 135.1 |
| wb_lcd | 1,295,076 | 2.632 | 1.370 | 1.262 | 0.424 | 3.916 | 357.4 | 7.36 |

| design | ASIC total | dyn | static (leakage) | clock-tree cells | ASIC MHz | ASIC pJ/cycle | ASIC nets with activity | latch start |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| mmuart | 0.514 | 0.514 | 1.8e-6 | 0.112 | 100 | 5.1 | 0.985 | 0 |
| verilog_cordic_core | 7.25 | 7.25 | 2.3e-5 | 1.174 | 100 | 72.5 | 0.982 | x |
| wb_lcd | 1.79 | 1.79 | 1.2e-5 | 0.513 | 50 | 35.8 | 0.965 | 0 |

FPGA latch start: x for mmuart and cordic, 0 for wb_lcd. Testbench vs vectorless FPGA total: 0.84x, 1.80x,
0.67x of the vectorless total (mmuart, cordic, wb_lcd): the vectorless estimate is higher for the two
mostly-idle designs and lower for cordic, whose short 220-cycle testbench is busy.
cordic's 220 cycles is a short run; its activity is that of a short directed test.

## Correction (2026-11-07): ASIC activity was not applied, and why wb_lcd ASIC is 5x the FPGA

The first version of this table was wrong. The OpenROAD script used `set_power_activity -pins <driver>`;
OpenSTA's Tcl wrapper only acts on input pins and skips output pins without a message, so only the input
ports kept their measured activity and every other net took OpenSTA's propagated default. Evidence:
per-pin activity of 0, 0.1, 1 and 2 on the same flop output gave identical power; the raw
`sta::set_power_pin_activity` does act. Fixed in `sta.sta_script` (unit test
`test_driver_pins_use_the_raw_command`). Hand check with the fix, mmuart, 100 MHz, 1.8 V, net capacitance
from `report_net` (upper bound of the range OpenSTA uses), P = 0.5 C V^2 activity f:

| net | activity/cycle | C (fF) | hand (W) | OpenSTA switching (W) |
| --- | --- | --- | --- | --- |
| enable16_counter[0] | 0.973 | 10.745 | 1.694e-6 | 1.694e-6 |
| enable16_counter[3] | 0.0962 | 9.890 | 1.541e-7 | 1.542e-7 |
| csr_do[0] | 1.38e-4 | 1.055 | 2.36e-11 | 2.36e-11 |

Corrected energy per cycle (pJ), ASIC before to after: mmuart 5.67 to 5.14, cordic 65.2 to 72.5
(ASIC run only; its by_line_asic is dropped until the next full run), wb_lcd 42.4 to 35.8. The FPGA
numbers are unchanged (VPR reads the whole .act file). Activity is per testbench clock cycle for both
targets: the testbench clock is the DUT clock in all three (wb_lcd has one clock, wb_clk_i; tb period 20
ns = the 50 MHz given to OpenROAD; mmuart and cordic 10 ns = 100 MHz), VPR evaluates at 1/critical path
with the same per-cycle activity, and pJ/cycle = power x its own period in both targets, so there is no
normalisation error. Unmatched ASIC nets are 3.5% for wb_lcd and carry the default.

Why wb_lcd ASIC is still 5x its FPGA figure (35.8 vs 7.36 pJ) while mmuart is near parity: the design is
idle in its testbench, so the ASIC figure is the clock-pin floor of its 625 flip-flops. Sequential cells
are 71% of the ASIC power (1.27 mW internal, 1.1 uW switching), 41 fJ per flop per cycle; a flop with
activity 0.096 in mmuart takes 4.2 uW at 100 MHz against 6.0 uW at activity 0.97, so ~4.1 uW (41 fJ per
cycle) is paid whatever the data does. Clock-tree cells add 0.513 mW (10.3 pJ). VPR's whole dynamic budget
for wb_lcd is 3.8 pJ per cycle for 636 flip-flops (6 fJ each) at 0.9 V in a 45 nm model. mmuart's FPGA
figure is higher per flop because its testbench is busy (a counter bit toggles every cycle) and because
its static share is large for such a small design. So the pattern is technology and idleness (sky130 1.8 V
liberty charges the clock pin of every flop every cycle; VPR's PTM 45 nm model at 0.9 V does not), not a
bug. Compare trends, not absolute pJ across targets. A later Odin III (rel-main5, `sim_tb --vcd-all` with
BLIF names) could replace the iverilog gate-level path as FPGA activity source; not done here.

## Activity cross-check (Odin III replay vs iverilog RTL, same testbench)

| design | nets compared | identical activity | median / p90 / max abs activity diff |
| --- | --- | --- | --- |
| mmuart | 213 | 47.9% | 1.3e-9 / 1.1e-5 / 2.2e-5 |
| verilog_cordic_core | 4079 | 99.6% | 0 / 0 / 4.5e-3 |
| wb_lcd | 304 | 45.7% | 9.1e-7 / 2.3e-4 / 7.2e-4 |

The non-identical nets differ by tiny amounts (toggle counts differ by a few edges: the replay samples
inputs once per clock edge). Static probability differs more; measured cause below.

### Static probability gap (verified, mmuart)

Odin III is 2-state; iverilog has x until a flip-flop is first written. Dividing by known-value time only
(what `activity.csv` holds) gave a static-probability gap to Odin of up to 0.256 (p90 0.120). Counting x
time as "not 1" instead gave a maximum gap of 6.0e-5. 141 of the 213 nets have x part of the run
(csr_do bits are known 61.4% of the time). So the cause is x time, not a simulator difference. Activity
(toggles per cycle) is unaffected because x edges are not counted in either source.

## Odin III replay as the activity source

Only ports keep their HDL names in the BLIF, so replay activity reaches 28.1% (mmuart), 4.4% (cordic),
15.7% (wb_lcd) of the FPGA nets; the rest take the mean of the matched nets. FPGA total with that
activity: 1.361 mW (mmuart, vs 1.689), 21.81 (cordic, vs 25.44), 2.386 (wb_lcd, vs 2.632). The main
numbers above use the iverilog gate-level path (matched fraction 1.0). A request for an Odin III
netlist-view VCD with BLIF names is with the controller.

## Per HDL line

`power.json` holds `by_line` (FPGA, model: dynamic non-clock power split by activity x (fanout+1)) and
`by_line_asic` (exact per instance, lines of the single-file `design.v` of the silicon flow). Examples:
mmuart ASIC dynamic power is led by design.v lines 73, 170, 217; wb_lcd FPGA by delay_counter.v:62 (68%
of the dynamic share); cordic puts most logic on one generate-loop line (design.v:221), so the line
roll-up is coarse there.

## What is missing or approximate

No `read_vcd` in this OpenROAD (per-pin `set_power_activity` used); no SPEF (placement parasitics);
glitch power not counted; hard adders have no VPR power model (soft adders used); ASIC clock power is the
clock-tree cells only (lower bound); static power of sky130 is nanowatts at tt/25C so it is tiny next to
the FPGA's 45 nm static power; the FPGA and ASIC use different technologies, so compare trends, not
absolute watts. Files here: `*.power.json` per design and `mmuart.activity.csv`.
