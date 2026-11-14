# wyrd

Wyrd III is the canopy of Yggdrasil III: the experiment runner and workbench around Odin III. Python 3.11+, no runtime
dependencies for the runner. It does four jobs:

- **Run experiments** (W1, always available): a `wyrd.toml` project of designs, recipes and architectures expands to runs under a
  memory budget; every run directory is kept and indexed in `wyrd.db`; `wyrd table`, `compare` and `timing` read them.
- **Show them** (extra `[gui]`): `wyrd-gui` with the project tree, source, Quartus-style report, `wyrd.toml` editor and flow runner,
  plus the visualizations: schematic and cone views, the Norns placement atlas, the Mimir browser with HDL heat, path view and
  Structures and Timing tabs, and a Floorplan button.
- **Simulate** (Bifrost III, extra `[sim]`): `wyrd.bifrost` compiles a design with Odin III and steps it one clock edge at a time;
  `wyrd sim`, the Simulate tab, VCD, and testbench mode `wyrd tb run|convert`.
- **Play** (Midgard III, extra `[midgard]`): Verilog Town, where you write one Verilog module per traffic light.

Wyrd III has no paper of its own; it is the tool the experiments of the other pieces run through, and it has two PDF tutorials
([command line](https://drpaj12.github.io/wyrd/wyrd-tutorial.pdf), [GUI](https://drpaj12.github.io/wyrd/wyrd-gui-tutorial.pdf)).
Manual: <https://drpaj12.github.io/wyrd/>. Hub: <https://github.com/drpaj12/YggdrasilIII>.

Wyrd III is part of **Yggdrasil III**, the suite of Odin III (<https://github.com/drpaj12/odin3>, the trunk), Wyrd III (<https://github.com/drpaj12/wyrd>, the canopy, with Bifrost III and Midgard III) and Heimdall III (<https://github.com/drpaj12/heimdallIII>, the canopy viewer), Loki III (<https://github.com/drpaj12/loki>), The Norns III (<https://github.com/drpaj12/nornsIII>), Verdandi III (<https://github.com/drpaj12/verdandiIII>) and Leman Russ III (<https://github.com/drpaj12/lemanrussIII>) on side branches, and Mímir III (<https://github.com/drpaj12/mimirIII>, the fruit). Wyrd III is the canopy, with Bifrost III (the simulation bridge) and Midgard III (Verilog Town, W4, after the original verilogTown: Jamieson, Grace, Mizuno, Zhang, ASEE 2017). Version 0.1.0 (`pyproject.toml`; hub snapshot [v1.6.0](https://github.com/drpaj12/YggdrasilIII/blob/v1.6.0/docs/versions.md)); tested with Odin III 1.6.0 (C ABI 7): the `sim` extra needs the `odin3` package 1.0.3 or later, testbench mode 1.3.0 or later. The hub is <https://github.com/drpaj12/YggdrasilIII> (documentation: <https://drpaj12.github.io/YggdrasilIII/>, versions of every piece: <https://drpaj12.github.io/YggdrasilIII/versions.html>) and its picture of the tree is <https://github.com/drpaj12/YggdrasilIII/blob/main/images/yggdrasil-tree.png>.

    pip install -e .
    wyrd config init     # write ~/.config/wyrd/machine.toml with detected values
    wyrd config show     # effective settings and where each came from

Settings precedence, lowest first: built-in defaults, `machine.toml`, the project's `[run]`
table (`step_timeout` only), command-line flags. Design: `docs/specs/`.

## Features

Status: **works** = on `main` with tests; **optional** = needs an extra (`[gui]`, `[sim]`, `[midgard]`) or an external program.

| Feature | Status | Where |
|---|---|---|
| Experiment runner: a `wyrd.toml` project (designs, recipes, architectures) expands to runs under a memory budget, every run directory is kept and indexed in `wyrd.db` | works | `wyrd init`, `run`, `status`, `table`, `compare`, `script`; [projects](docs/user/projects.md), [running](docs/user/running.md) |
| Machine settings with a clear precedence (defaults, `machine.toml`, project, flags) | works | `wyrd config init\|show` |
| Critical-path attribution of a run | works | `wyrd timing`; GUI Timing panel |
| Sample project with expected results | works | `samples/`, [samples](docs/user/samples.md) |
| Desktop GUI: project tree, source, Quartus-style report, parsed warnings and errors, `wyrd.toml` editor with live validation, flow runner, docked and zoomable panels | optional (`[gui]`) | `wyrd-gui`; [gui](docs/user/gui.md) |
| Visualization: schematic of a module or a fan-in cone of a net or HDL line (netlistsvg, optional Node.js program) | optional | Schematic panel; [gui](docs/user/gui.md) |
| Visualization: placement atlas of a Norns round-7 placement on the device grid, side by side and difference views | optional | Atlas panel; `docs/specs/2026-10-26-placement-atlas.md` |
| Visualization: Mimir browser (designs, metric records with run provenance, flow parameters, config comparisons; schema 6 per-path tables), HDL hot/cold colouring per bit, Structures and Timing tabs, path view, fan-in and fan-out cones from a clicked token | optional (`[gui]`) | `wyrd mimir summary\|designs\|design\|run\|compare`, Mimir and Paths panels; [mimir](docs/user/mimir.md) |
| Floorplan: re-run VPR with its graphics for a run | optional (VPR built with Qt6 graphics) | GUI Floorplan button |
| Bifrost III simulation: compile Verilog with Odin III, set inputs, step, reset, record, VCD; `wyrd sim` with random or vector-file inputs; GUI Simulate tab with waveform and GTKWave | optional (`[sim]`) | `wyrd.bifrost`, `wyrd sim`; [simulation](docs/user/simulation.md) |
| Testbench mode: run Verilog testbenches on RTL, netlist or both, and convert between vector files and testbenches (needs an Odin III with `run_testbenches`) | optional (`[sim]`) | `wyrd tb run\|convert`; [testbench](docs/user/testbench.md) |
| Power pilot: FPGA (VPR) and ASIC (OpenROAD) power from a design's testbench switching activity; results of three designs in `docs/power/` | optional (pilot; needs iverilog, VTR with power data, ACE 2.0, OpenROAD) | `wyrd power run`; [power](docs/user/power.md) |
| Mux cost report: mux bits, LUTs and select lateness per HDL construct, from Odin III provenance; plain table or JSON, usable by a person or an AI agent | works (needs Odin III 1.6.1 or later; select lateness needs a routed VPR run) | `wyrd mux-cost`; [mux-cost](docs/user/mux-cost.md) |
| 3D provenance viewer: `wyrd viz export\|serve\|site` forwards to Heimdall III, which has its own repository | optional (`[viz]`) | `wyrd viz`; [viz](docs/user/viz.md) |
| Midgard III (Verilog Town): replication of the verilogTown game with a Verilog editor and a level editor | optional (`[midgard]`) | `midgard`; [midgard](docs/user/midgard.md) |
| Step types: `odin3`, `vpr`, `abc`, `shell`, `odin3-flow`, and Python plugins registered as entry points (Loki III registers step plugins) | works | `wyrd/steps/`; [projects](docs/user/projects.md) |

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
- [Verdandi III manual](https://drpaj12.github.io/verdandiIII/).
- [The Norns III](https://github.com/drpaj12/nornsIII) (repository; plan under `docs/`; its paper is kept locally by the author).
- [Set up the whole suite](https://drpaj12.github.io/YggdrasilIII/getting-started.html) on a clean Linux or
  Windows machine, and [drive it with Claude Code](https://drpaj12.github.io/YggdrasilIII/ai-agent.html).

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

### Schematic panel (optional)

The Schematic dock (next to Timing) draws a module, or the fan-in cone of a net or of an HDL
line (`file.v:LINE`, through the `src` attributes Odin III writes), from a Yosys-schema JSON
netlist: `odin3 -p "read_verilog top.v; proc; write_json top.json"`. Odin III's `write_json` output
feeds netlistsvg directly. Drawing is done by [netlistsvg](https://github.com/nturley/netlistsvg)
(N. Turley, MIT licence, version 1.0.2 tested), an optional Node.js program run as a subprocess;
it is not bundled or vendored. Without it Wyrd works as before and the panel shows how to install:

    npm install --ignore-scripts netlistsvg      # in any directory
    export WYRD_NETLISTSVG=<dir>/node_modules/.bin/netlistsvg   # and WYRD_NODE if node is not on PATH

A module with more than `max cells` (default 300) cells is not drawn; pick a smaller module or a
cone. Measured limits are in `docs/specs/2026-10-26-schematic-view.md`.

### Atlas panel (placement atlas)

The Atlas dock (next to Schematic) draws a Norns round-7 placement on the device grid, one square
per CLB, with the HDL labels carried by the VPR atoms. Open an atlas file (the
*Open atlas file...* button in the dock, `<arm>.s<seed>.json.gz`), or type the Norns run dir (`runs/r7`) and press Scan;
the Design, A, Seed and B boxes list what the file names offer. Colour by `construct`, `word`,
`inst` or the N17 `class` (each CLB takes its most common value) or by `crit` / `pcrit` (the
largest value in the CLB). Click a value in the list to outline the CLBs that hold it and fade the
rest. Hover a CLB for its atoms and labels. View `A | B side by side` shows two arms of one design
(B uses A's seed, else its first seed); `Difference (B vs A)` shades B's CLBs by the share of atoms
that sat in a different CLB in A, and the hover text names where they came from. Data source: Norns
round 7, VPR runs with VTR (Rose et al., FPGA 2012) and VTR 9 (Elgammal et al., TRETS 2025), commit
3c9a4d23b2. Spec and measured load/draw time: `docs/specs/2026-10-26-placement-atlas.md`.

### Mímir browser

`wyrd mimir summary|designs|design|run|compare DB` and the Mímir dock browse a Mímir store (schema
version 4) read only: designs, metric records with their run provenance, flow parameters, and
config-versus-base comparisons. See `docs/user/gui.md`.

## Simulation (`wyrd[sim]`)

    pip install -e ".[sim]"      # the odin3 package, 1.0.3 or later (1.6.0 tested); odin3 is not on PyPI, install its release wheel

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

Testbench mode (needs Odin III 1.3.0 or later, for `run_testbenches`): `wyrd tb run --project p.o3proj`
or `wyrd tb run --tb tb.v --dut dut.v` runs Verilog testbenches (RTL, netlist or both); `wyrd tb convert --to tb|vectors`
converts between vector files and testbenches. See `docs/user/testbench.md`.

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
Odin III 1.6.0 (`odin3`, `odin3-flow` on PATH), VTR (see the hub's [tools page](https://github.com/drpaj12/YggdrasilIII/blob/main/docs/tools.md)) and `VTR_ROOT`.

    wyrd config init                          # then check vtr_root in machine.toml
    wyrd run --project samples
    wyrd table --project samples

`samples/expected/<arch>.json` holds the results of `odin3-flow` run directly
(`samples/make-expected` rewrites them). `tests/test_samples.py` runs the samples into a temporary
copy and checks that `wyrd table` equals them (skipped when `odin3-flow` or `VTR_ROOT` is missing).
Copied sample files are listed in `NOTICE`.
