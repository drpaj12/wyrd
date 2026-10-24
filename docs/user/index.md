# Wyrd III

Wyrd III is the experiment runner and workbench around Odin III, part of the Yggdrasil III suite.
It does four jobs:

- **Run experiments.** A TOML project file (`wyrd.toml`) names your designs, recipes and
  architectures. `wyrd run` expands the sweep into runs, executes them under a memory budget, keeps
  every run directory and indexes the results in `wyrd.db`. `wyrd table` and `wyrd compare` print them.
- **Show them.** `wyrd-gui` is a desktop window (PySide6) with the project tree, the sources, a
  Quartus-style report of each run, a `wyrd.toml` editor and a flow runner.
- **Simulate.** Bifrost III (`wyrd.bifrost`) compiles a design with Odin III and steps it one clock
  edge at a time. The GUI's Simulate tab and `wyrd sim` use it.
- **Play.** Midgard III (`midgard`) is Verilog Town: you write one Verilog module per traffic light
  and cars drive through the town. It runs on Bifrost III.

Wyrd calls Odin III only as programs (`odin3`, `odin3-flow`, `vpr`, `abc`). The one exception is
Bifrost III, which uses the `odin3` Python package for simulation.

This manual follows the layout of the Odin III manual: a getting-started page, then one page per part.
A step-by-step PDF tutorial that builds one project from scratch is published with this manual:
[wyrd-tutorial.pdf](https://drpaj12.github.io/wyrd/wyrd-tutorial.pdf) (source in `docs/tutorial/`).
A second PDF tutorial does everything in the graphical interface, with a figure for each step:
[wyrd-gui-tutorial.pdf](https://drpaj12.github.io/wyrd/wyrd-gui-tutorial.pdf) (source in `docs/tutorial-gui/`).

The other Yggdrasil III manuals are linked in the sidebar: the
[hub](https://drpaj12.github.io/YggdrasilIII/), [Odin III](https://drpaj12.github.io/odin3/) and
[Loki III](https://drpaj12.github.io/loki/), with [Verdandi III](https://drpaj12.github.io/verdandiIII/) beside them.
The Norns III runs its placement experiments through Wyrd III: <https://github.com/drpaj12/nornsIII>.

```{toctree}
:maxdepth: 2

getting-started
projects
running
gui
simulation
midgard
samples
```
