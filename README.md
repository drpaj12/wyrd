# wyrd

Experiment runner for Odin III flows (W1 of Wyrd III). Python 3.11+, no runtime dependencies.

Wyrd III is part of **Yggdrasil III** (the project / world tree), the suite of Odin III
(<https://github.com/drpaj12/odin3>), Wyrd III, Loki III (<https://github.com/drpaj12/loki>) and Midgard III. Midgard III,
also known as Verilog Town, is the game Wyrd III will host (W4), after the original verilogTown (Jamieson, Grace,
Mizuno, Zhang, ASEE 2017).

    pip install -e .
    wyrd config init     # write ~/.config/wyrd/machine.toml with detected values
    wyrd config show     # effective settings and where each came from

Settings precedence, lowest first: built-in defaults, `machine.toml`, the project's `[run]`
table (`step_timeout` only), command-line flags. Design: `docs/specs/`.

## GUI

    pip install -e ".[gui]"
    wyrd-gui [PROJECT_DIR]

The GUI (PySide6) shows the project tree, source files, the Quartus-style report, parsed
warnings and errors, and a `wyrd.toml` editor with live validation. It runs the flow as a
`wyrd run` subprocess. Run it inside WSL (WSLg shows the window); Windows needs no extra code.

The Floorplan button re-runs VPR with its graphics enabled for the selected run, so it needs a VPR
built with Qt6 graphics; when VPR exits early the Flow log says so. Credits for the tools and
papers Wyrd builds on are in `docs/CITATIONS.md` and the About dialog.

## Simulation (`wyrd[sim]`)

    pip install -e ".[sim]"      # Odin III 1.0.3 or later; odin3 is not on PyPI, install its release wheel

`wyrd.bifrost` (Bifrost III) wraps Odin III's per-cycle simulator: it compiles Verilog with
`read_verilog; proc; opt; lower`, then exposes named inputs and outputs, step, reset, recording and VCD output.

    from wyrd.bifrost import BifrostSession

    with BifrostSession.from_verilog(["traffic.v"]) as sim:
        sim.set("rst", 1)
        sim.step()
        sim.set("rst", 0)
        sim.step(4)
        print(sim.get("light_ns"), sim.get("light_ew"))

The command line runs vector files or random inputs:

    wyrd sim traffic.v --random 100 --seed 3 --vcd traffic.vcd
    wyrd sim traffic.v --vectors in.txt --save-vectors out.txt

A vector line is `CYCLE INPUTS [OUTPUTS]` with ports written MSB first. The GUI has a Simulate tab
(Tools menu, Ctrl+T): compile a project design, edit inputs, step or run, run random inputs or a vector
file, view the built-in waveform and open the recording in GTKWave (`WYRD_GTKWAVE` or `gtkwave` on PATH).

Limits of the S1 simulator: clocks must be top-level inputs (a clock is stepped, not set), a signal that
passes remove must be marked `(* keep *)` in the HDL to stay visible, and a port that mixes clock and data
use is not supported. The VCD is written by Wyrd from the recording: one cycle is 10 time units (timescale 1ns) and values are
sampled once per step, so a combinational output shows as changing at the rising edge, not at the input change.

## Samples

`samples/` holds three projects (`single`, `multi`, `dsp`) swept over two architectures. They need
Odin III 1.0 (`odin3`, `odin3-flow` on PATH) and `VTR_ROOT`.

    wyrd config init                          # then check vtr_root in machine.toml
    wyrd run --project samples
    wyrd table --project samples

`samples/expected/<arch>.json` holds the results of `odin3-flow` run directly
(`samples/make-expected` rewrites them). `tests/test_samples.py` runs the samples into a temporary
copy and checks that `wyrd table` equals them (skipped when `odin3-flow` or `VTR_ROOT` is missing).
Copied sample files are listed in `NOTICE`.
