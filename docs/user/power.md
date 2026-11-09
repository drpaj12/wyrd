# power: power estimate from testbench switching activity (pilot)

`wyrd power run` estimates the power of one design from the switching activity of its own testbench
(or, without a testbench, a vectorless estimate), for an FPGA target (VPR's power model) and, when given a
silicon flow output, for sky130 (OpenROAD). It is the Bifrost III power pilot: descriptive numbers, not a
supported flow. The method and its limits are in `docs/specs/2026-11-06-bifrost-power-design.md` and the
results of three designs in `docs/power/2026-11-06-pilot-results.md`.

```bash
wyrd power run --design NAME --src dut.v --top TOP --tb tb.v --tb-top TB_TOP --out OUT_DIR
wyrd power run --design NAME --src dut.v --top TOP --out OUT_DIR      # no testbench: vectorless (ACE 2.0)
```

`--activity` picks the source: `iverilog` (the testbench run on the synthesised netlist; the default with `--tb`),
`odin3` (`sim_tb --vcd-all`, Odin III 1.5.0 or later) or `ace2` (vectorless; the default without `--tb`).
`--blif FILE` runs on an Odin III flow BLIF with hash names instead of synthesising, so the net names join
the BLIF a Heimdall III page was built from. `--silicon DIR` adds the ASIC estimate from a silicon flow output.
`--mem-cap SIZE` caps VPR, ACE 2.0, OpenROAD and Odin III with `systemd-run`. `wyrd power run --help` lists
every option. The run writes `power.json`, `activity.csv`, `asic_nets.csv` and `asic_inst.csv` into `--out`.

Needs, besides Odin III 1.6.0 and Wyrd III: iverilog for the `iverilog` source, a VTR build with power data and
ACE 2.0 for the FPGA numbers, and OpenROAD with the sky130 PDK for the ASIC numbers. Versions and install
steps are on the hub's [tools page](https://github.com/drpaj12/YggdrasilIII/blob/main/docs/tools.md). The
outputs of the pilot are in `docs/power/` (`*.power.json`, `mmuart.activity.csv`).
