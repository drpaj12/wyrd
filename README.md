# wyrd

Experiment runner for Odin III flows (W1 of Wyrd III). Python 3.11+, no runtime dependencies.

Wyrd III is part of **Yggdrasil III** (the project / world tree), the suite of Odin III
(<https://github.com/drpaj12/odin3>), Wyrd III, Loki III (<https://github.com/drpaj12/loki>) and Midgard III. Midgard III,
also known as Verilog Town, is the game Wyrd III hosts (W4), after the original verilogTown (Jamieson, Grace,
Mizuno, Zhang, ASEE 2017).

    pip install -e .
    wyrd config init     # write ~/.config/wyrd/machine.toml with detected values
    wyrd config show     # effective settings and where each came from

Settings precedence, lowest first: built-in defaults, `machine.toml`, the project's `[run]`
table (`step_timeout` only), command-line flags. Design: `docs/specs/`.

## Documentation

Start at the Yggdrasil III hub; every manual links to the others.

- [Yggdrasil III hub](https://drpaj12.github.io/YggdrasilIII/): the suite, how the pieces connect, getting started.
- [Odin III manual](https://drpaj12.github.io/odin3/).
- [Wyrd III manual](https://drpaj12.github.io/wyrd/), with
  [simulation (Bifrost III)](https://drpaj12.github.io/wyrd/simulation.html) and
  [Midgard III (Verilog Town)](https://drpaj12.github.io/wyrd/midgard.html).
- Tutorials (PDF): [command line](https://drpaj12.github.io/wyrd/wyrd-tutorial.pdf) and
  [GUI](https://drpaj12.github.io/wyrd/wyrd-gui-tutorial.pdf).
- [Loki III manual](https://drpaj12.github.io/loki/).

Sources: manual `docs/user/` (`pip install -r requirements-docs.txt`, then
`sphinx-build -W -b html docs/user build/docs`); tutorials `docs/tutorial/` and `docs/tutorial-gui/`
(LaTeX, with the scripts that regenerate the screenshots from real runs).

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

## Midgard III (Verilog Town)

A close replication of the verilogTown game: you write one Verilog module per traffic light and cars drive
through the town. Where a choice differs from the original, the original wins; the deviations are listed in
section 13 of `docs/specs/2026-10-21-w4-verilog-town-design.md`.

    pip install "wyrd[midgard]"      # pygame-ce, PySide6 and Odin III 1.0.3 (odin3 is not on PyPI, install its release wheel)
    midgard                          # or: python -m wyrd.midgard, or Wyrd III GUI > Tools > Midgard III (Verilog Town)

Time: **1 game tick = 1 rising clock edge of your module**, 60 ticks per second at speed 1x. Scores are counted in
ticks. Keys in a level: `S` start, `P` or `X` pause, `.` single step, `1` `2` `4` speed, `H` help, `R` restart,
`M` menu, `C` clear sensors, `V` record, `E` export VCD, `Q`/`A` or `=`/`-` zoom, arrow keys pan. A click on an
intersection opens the Verilog editor window for its file (only in the edit phase); the mouse places the seven
sensors.

Each light is a file `Traffic_signal_set_I.v` under `$MIDGARD_HOME/Lv<N>/VerilogFiles/` (default
`~/.local/share/midgard`); the game copies the starter file there on first use. Ports (spec 7.1):

| Port | Direction | Width | Meaning |
|---|---|---|---|
| `clk` | input | 1 | clock, stepped by the game |
| `rst` | input | 1 | active low: 0 during start-up, 1 while playing |
| `sensor_light` | input | 8 | sensors at the intersection |
| `general_sensors` | input | 30 | the sensors you placed |
| `outN` `outS` `outE` `outW` | output | 3 | signal for cars heading N, S, E, W |
| `debug_port` | output | 30 | optional |

Output codes: `0` Stop, `1` Forward only, `2` Left only, `3` Right only, `4` Go. Codes 5 to 7 act as Stop.
A file that does not compile or lacks a port keeps the level in the edit phase and shows the error with `file:line`.

The **Verilog editor window** (PySide6) saves, verifies (compiles with Odin III), simulates one clock cycle at a
time from the sensor fields and shows the four lights; it offers the combinational and sequential templates.
A set `MIDGARD_EDITOR` (a command, split like a shell line, plus the file path) wins over the window: the game
opens your editor instead. Start the game with `--no-editor` to open neither (the status line shows the path).
`midgard-editor [LEVEL.xml]` is the **level editor**: create a level (even map sizes) or update a level file,
edit cars, export the XML and the map image. `Create` writes to `$MIDGARD_HOME/levels/Lv<N>/map/lvNN.xml` (the
original wrote under its install folder); `Export As...` picks another file, and the done message shows the paths.

Credit: the game, levels and artwork come from verilogTown (Jamieson, Grace, Mizuno, Zhang, ASEE 2017; MIT
License), see `NOTICE` and `docs/CITATIONS.md`. The font is Creepster (Font Diner, SIL OFL 1.1).

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
