# Bifrost III power estimation from testbench switching activity (spec, 2026-11-06)

Purpose: a real, activity-based power estimate (FPGA and ASIC) from a design's own testbench, with the
per-net activity traceable to HDL lines. Replaces "power = area correlation" for the speed/area/power
trade-offs per HDL construct (Bifrost B Q1.2, RQ B Q1.2). Measure: per design and target, total /
dynamic / static / clock power in watts, the matched fraction of the activity, and a per-HDL-line roll-up.

Everything below was checked on this machine on 2026-11-06 (tool names, flags, numbers); anything not
checked is marked "not verified".

## 1. Findings on the tools (what exists, what is missing)

| Item | Finding |
| --- | --- |
| Odin III `sim_tb --vcd` | Writes the testbench signals and the ports of each DUT instance only (docs/user/testbench.md). No DUT internal net is in it. On mmuart: 40 variables, all testbench or port. |
| Odin III `sim --vcd` | Dumps every named net of the RTL view, one scope per instance (39 variables on mmuart), driven by random or `--vectors-in` inputs, one cycle = 10 time units. After `abc --lut 6` the netlist view dumps only 37 variables (ports and a few names): the LUT outputs are not dumped. So Odin III cannot give activity for post-synthesis nets. Request to the controller (not done): a `sim_tb --vcd-all` / netlist-view dump of every net with its BLIF name. |
| Odin III `write_blif --vtr --name-style hash --prov-map` | BLIF net names are hashes (`h2cfbu77m7m`); the sidecar `.names` file maps each hash to `module/$nNNN@file:line`, module, file, line, construct and role. This is the provenance link. |
| iverilog | 12.0 at /usr/bin/iverilog; `$dumpvars` dumps every net with the RTL names. A time step is dumped with the value at its end (glitches inside a step are not shown), the same convention as Odin III's VCD. |
| VPR (VTR build in external/vtr-verilog-to-routing, commit 3c9a4d23b2) | `build/vpr/vpr` has `--power`, `--tech_properties`, `--activity_file`. Tech files: `vtr_flow/tech/PTM_{22,45,130}nm/*.xml`. Power archs: `vtr_flow/arch/power/*` (40 files, no carry-chain `adder` model) and `vtr_flow/arch/timing/k6_frac_N10_frac_chain_mem32K_40nm.xml` (has `<power>` and `adder`; used by VTR's own `power_std` and `strong_power` tasks with `PTM_45nm`). Chosen pair: that timing arch + `PTM_45nm/45nm.xml`. Missing: none. |
| VPR `.act` format | One line per net: `<net> <static probability> <switching activity>` (toggles per clock cycle). Nets absent from the file get VPR's default; a net in the file but not in the BLIF gives a warning (this is how the matched fraction is counted). |
| ACE2 | `build/ace2/ace` exists. Needs `-c <clock>`; writes a renamed netlist, so its `.act` only works with the ACE netlist (clocks restored by `vtr_flow/scripts/restore_multiclock_latch.pl`). Used only as the vectorless comparison. |
| Carry chains | The `adder` model has no power data ("No dynamic power defined for BLIF model: .subckt adder", seen on mmuart). The power flow therefore runs Odin III without `read_techlib vtr.o3lib` / `hardmap`, so adders are soft LUTs and every cell is counted. Hard blocks (memory, multiplier) are reported by count; a design that needs them is out of the pilot. |
| OpenROAD | `work/tools/mamba/envs/orcond/bin/openroad`, version string `f12e2f4741...`. `report_power`, `set_power_activity`, `read_spef`, `estimate_parasitics`, `set_wire_rc` exist. **`read_vcd` and `read_saif` do not exist in this build** (`info commands` is empty). Workaround, no install: Bifrost parses the VCD itself and issues `set_power_activity -pins <driver pin> -activity A -duty D` per net (activity = toggles per clock cycle). Report this to the controller as the missing piece. |
| sky130 | `work/tools/pdk/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib` (the one the silicon flow uses) and the Verilog models in `.../verilog/` for gate-level simulation (`tools/silicon/gate_sim.py` already drives them). |
| Silicon flow output | The ladder run of mmuart (archive `silicon-ladder-out.tar.xz`, extracted locally, F: untouched) holds `or/final.odb`, `or/final.v`, `or/route.def`, `clean.v`, `prov.csv`, `census.json`. **No SPEF is written.** Parasitics: `estimate_parasitics -placement` on `final.odb` with `set_wire_rc -signal -layer met2 -clock -layer met5` (without `set_wire_rc` the wire capacitance is zero, OpenROAD warns RSZ-0014). |

Nothing required is missing. Two limits are stated, not hidden: no `read_vcd` (workaround above), and no
SPEF (placement-based parasitics, so the ASIC switching power is an estimate with wire load from placement).

## 2. Activity

Definition per net, over the run, from a VCD, counting only intervals where the value is 0 or 1:
- static probability P1 = (time at 1) / (time at 0 or 1);
- switching activity A = (number of 0<->1 transitions) / (number of rising edges of the clock net). This is
  toggles per clock cycle, the unit of the VPR `.act` file and of `set_power_activity -activity`.
  Transitions to or from x are not counted. A glitch inside one time step is not counted (the VCD does not
  carry it), so the power is functional-activity power; glitch power is not included. A multi-bit signal
  is split into bits named `name[i]` (the BLIF and netlist convention).
- the clock net itself is excluded from the `.act` (VPR and OpenSTA treat the clock separately).

Sources, in order of how they are used:
1. **Gate-level iverilog on the post-synthesis netlist (the main source).** Bifrost writes the BLIF as a
   Verilog netlist (`.names` as sum-of-products assigns, `.latch` as `always @(posedge clk)`, with the
   BLIF net names as escaped identifiers), wraps it in a module of the DUT's name and port widths, and
   runs the design's own Mimir testbench unchanged with `$dumpvars` on the DUT scope. Every BLIF net is in
   the VCD under its BLIF name, so the matched fraction is 1.0 by construction. For ASIC the same is done
   with the silicon flow's `or/final.v` and the sky130 models (the names are the netlist's own). A run
   whose testbench does not print PASS is not used.
2. **Odin III replay (the brief's source), RTL names.** The DUT port waveform from `sim_tb --vcd` is
   sampled at each rising clock edge into an `odin3-sim-vectors` file and replayed with
   `sim --vectors-in --vcd`, giving the RTL view activity under HDL names. Valid only for a single-clock
   DUT whose inputs change between edges (checked per design; otherwise the design is reported as not
   replayable). Mapped to BLIF nets through the `.names` file where a hash entry has an HDL name; the
   rest take the default (mean activity of the matched nets). The matched fraction is reported. This path
   exists because it uses only Odin III; its power is reported next to the main one.
3. **iverilog RTL dump** (`$dumpvars(0, tb)` on the unchanged testbench): the cross-check for source 2.
4. **ACE2 vectorless**: comparison only.

Cross-check (descriptive, no hypothesis): for each net name present in both the Odin III replay VCD and the
iverilog RTL VCD, the pair (A_odin, A_iverilog) and (P1, P1); report the count of matched nets, the
fraction with identical A, and the distribution of |A_odin - A_iverilog| (min, median, p90, max). Then the
total power of the testbench `.act` against the ACE2 `.act` on the same design, arch and tech file.

## 3. Name mapping

- FPGA: source 1 needs none (names are the BLIF's). Source 2 maps HDL name -> hash through the `.names`
  file (`net` rows whose provenance name is a plain HDL net name). Unmatched nets: default activity,
  counted; `matched_fraction = matched BLIF nets / BLIF nets with a driver`.
- ASIC: names are the OpenROAD/final.v net and instance names. HDL line for an instance: `prov.csv` of the
  silicon flow (instance -> Odin cell -> HDL file:line; the ladder reports `join_rate 1.0` for mmuart).
  Inserted cells (tap, fill, cts buffers, resized) have no HDL line and roll up to `<physical>`.

## 4. Power

FPGA: `vpr <arch> <blif> --circuit_file <blif> --route_chan_width 100 --power --tech_properties
PTM_45nm/45nm.xml --activity_file tb.act` (the packer and placer are VPR defaults; fixed channel width keeps
the runs comparable). Totals from `<blif>.power` (Total, Routing, PB Types, Clock; dynamic fraction from the
%-Dynamic column; static = total - dynamic). Warnings in that file are copied into the report. VPR runs
through `tools/heavy-run` (ODIN3_HEAVY_OK=1).

ASIC: OpenROAD: `read_liberty` tt_025C_1v80, `read_db final.odb`, `create_clock` at the period used by the
flow (10 ns), `set_wire_rc`, `estimate_parasitics -placement`, `set_propagated_clock`, then
`set_power_activity` per driver pin and per input port, `report_power` (Internal + Switching = dynamic,
Leakage = static, Sequential/Combinational groups; the clock network is the clock-buffer share) and
`report_power -instances` for the per-instance table. Dynamic = Internal + Switching.

Per-HDL-line roll-up (the construct link):
- ASIC: per-instance power from OpenSTA summed by the instance's HDL file:line (exact apportionment).
- FPGA: VPR reports per block type, not per net. The roll-up is a model, labelled so in the report:
  the dynamic non-clock power is apportioned over nets by activity x (fanout + 1), then summed per
  provenance file:line. The total is exact (VPR's); the split is the model. Static and clock power are
  not apportioned.

## 5. Output schema (JSON, `power.json`, version 1)

    {"version": 1, "design": "mmuart", "testbench": "tb_mmuart.v", "tb_pass": true,
     "clock": "sys_clk", "cycles": 94432,
     "activity": {"source": "iverilog-gate|odin3-replay|ace2", "nets": N, "matched": M,
                  "matched_fraction": 1.0, "default_activity": null, "mode": "2state|4state"},
     "targets": {"fpga": {"arch": "...", "tech": "PTM_45nm", "method": "vpr --power",
                          "total_w": 0, "dynamic_w": 0, "static_w": 0, "clock_w": 0,
                          "warnings": [...], "vectorless_total_w": 0},
                 "asic": {"pdk": "sky130_fd_sc_hd tt_025C_1v80", "parasitics": "placement",
                          "total_w": 0, "dynamic_w": 0, "static_w": 0, "clock_w": 0,
                          "switching_w": 0, "internal_w": 0}},
     "crosscheck": {"nets_compared": 0, "identical_fraction": 0,
                    "abs_diff": {"min": 0, "median": 0, "p90": 0, "max": 0}},
     "by_line": [{"file": "uart.v", "line": 66, "fpga_dyn_w": 0, "asic_dyn_w": 0,
                  "asic_static_w": 0, "nets": 0}]}

and a per-net CSV `activity.csv` (`net,hdl_name,file,line,p1,activity,source`). Written by
`wyrd power report`; the same dict is returned by `wyrd.bifrost.power.run_power(...)`.

Mimir measure columns (proposed only, a mimirIII PR after the controller reviews the pilot numbers):
`pw_fpga_total_w`, `pw_fpga_dyn_w`, `pw_fpga_static_w`, `pw_fpga_clock_w`, `pw_asic_total_w`,
`pw_asic_dyn_w`, `pw_asic_static_w`, `pw_asic_clock_w` (watts), `pw_act_matched` (fraction),
`pw_act_source` (text), `pw_tb_cycles` (count).

## 5a. Decisions made while building (2026-11-06)

- The VCD is read through a named pipe while `vvp` runs, so a long testbench (wb_lcd: 26 ms) never writes a
  large file. Only the DUT instance and the testbench clock are dumped.
- Latch start state: a netlist has lost the RTL `initial` values. The gate-level run starts the latches at
  x, then 0, then 1; the first run whose testbench prints PASS is used and `start_state` says which.
- Frequency: VPR evaluates power at 1/(critical path) of the placed design; the ASIC run uses the clock
  period given (`--period-ns`, the testbench clock). Totals are therefore at different frequencies. The
  report adds `freq_mhz` and `energy_per_cycle_pj` (total power x period) per target as the comparable
  number. Activity is per cycle, so it does not depend on the frequency.
- VPR needs the clock net in the `.act` file; it is written with probability 0.5 and activity 2.
- ASIC clock power is the power of the clock-tree cells (`clkbuf_*`, `clkload*`); the clock-pin power
  inside the flip-flops is in their own (internal) power, so `clock_w` is a lower bound.
- The silicon flow works on a single-file `design.v`; its HDL lines (ASIC by_line) are lines of that file,
  the FPGA by_line uses the original files.
- Odin III replay is optional (a failure is recorded as `odin_replay_error`); it is the weaker source
  because only ports keep their HDL names in the BLIF (matched fraction about 28% on mmuart).

## 6. Code (stdlib only, in `wyrd/bifrost/power/`)

`vcdact.py` (streaming VCD reader -> per-bit P1 and A, edge sampler), `sim.py` (iverilog runs), `tools.py`, `flow.py`, `blifnet.py` (BLIF reader, Verilog netlist writer,
`.names` provenance reader), `actfile.py` (write `.act`, read `.power`), `sta.py` (OpenROAD script and
report parser), `crosscheck.py`, CLI `wyrd power run` (`wyrd/powercli.py`). Odin III is used as a
program (`odin3` binary), per wyrd/CLAUDE.md. Unit tests use small fixtures and fakes; the pilot is run by
hand and its reports kept in `docs/power/`.

## 7. Limits (stated up front)

Glitch power is not counted. Activity from a testbench is the activity of that testbench (a short
directed test, not a workload). The FPGA roll-up per line is a model; the ASIC one is not. ASIC wire load is
placement-based. Cordic and other DUTs Odin III cannot read yet have no netlist and are not pilots.
