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
| mmuart | 0.567 | 0.567 | 1.8e-6 | 0.112 | 100 | 5.7 | 0.985 | 0 |
| verilog_cordic_core | 6.52 | 6.52 | 2.3e-5 | 1.174 | 100 | 65.2 | 0.982 | x |
| wb_lcd | 2.12 | 2.12 | 1.2e-5 | 0.513 | 50 | 42.4 | 0.965 | 0 |

FPGA latch start: x for mmuart and cordic, 0 for wb_lcd. Testbench vs vectorless FPGA total: 0.84x, 1.80x,
0.67x of the vectorless total (mmuart, cordic, wb_lcd): the vectorless estimate is higher for the two
mostly-idle designs and lower for cordic, whose short 220-cycle testbench is busy.
cordic's 220 cycles is a short run; its activity is that of a short directed test.

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
