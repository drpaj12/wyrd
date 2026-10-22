# The GUI

```bash
wyrd-gui [PROJECT_DIR]
```

A step-by-step PDF tutorial does everything below in the interface, with a figure for each step:
[wyrd-gui-tutorial.pdf](https://drpaj12.github.io/wyrd/wyrd-gui-tutorial.pdf).

`wyrd-gui` needs the `gui` extra (PySide6). Without an argument it opens the last project (if its
`wyrd.toml` still exists). Run it inside WSL: WSLg shows the window.

## The window

- **Project** (left dock): the project as a tree of Designs (with their files), Recipes (with their
  steps) and Archs. Double-click a file to open it in the Source tab.
- **Tabs** (centre): *Source*, *Report*, *wyrd.toml* and *Simulate*. When `wyrd.toml` has an error only the
  *wyrd.toml* tab is enabled.
- **Messages** and **Flow** (bottom docks, tabbed; View menu shows or hides them).

### Source

A read-only view of a Verilog file with syntax colours. Double-clicking a message or a diagnostic
that names a file and line opens the file there.

### wyrd.toml

An editor for the project file with live validation. After you stop typing it parses the text as
`wyrd run` would: a valid file shows how many runs it expands to, an error shows the message and
highlights the line (click the message to jump to it). Ctrl+S saves; a file that does not validate
asks before saving. After a valid save the project reloads. **Project > Add design...** opens a
dialog (name, files, top module, "Add to [sweep] design") that appends a `[[design]]` block to the
editor text; it stays unsaved until you save.

### Flow

The Flow dock runs `wyrd run` as a subprocess, so the GUI and the command line behave the same:

- **Run** (Ctrl+R) and **Cancel** (Ctrl+.). Cancel stops the running steps; finished runs stay.
- **Force** re-runs runs that are already `ok` (`--force`).
- **Jobs** and **Memory budget** override the machine settings for this run (empty or 0 keeps them).
- A progress bar counts finished runs and the log shows the command's output.

Run is disabled while the project has a configuration error. The window asks before quitting
during a run.

### Report

When a run exists the Report tab shows a tree of results: *All runs* (the table `wyrd table` prints),
and for every run a *Summary*, one node per *Step n: tool* with its log files, and *Compare*.

- **Summary** is a Quartus-style table: Status, LUTs, CLBs, the hard blocks, Fmax (MHz) (computed
  as 1000 / critical path in ns), minimum channel width, critical path (ns), run directory and run key.
- A **log** node shows the file (`odin3.log`, `vpr.log`, `stdout.log`, ...). The Messages dock lists
  the warnings and errors parsed from the selected run's logs; filter All, Errors or Warnings, and
  double-click a row to open its location.
- **Compare** with another project directory fills a table like `wyrd compare` and lists runs found
  in only one project.
- **Floorplan** re-runs VPR with its graphics for the selected run, using the VPR set as
  `tools.vpr_gui` in the machine settings, else the VPR named in the run's log. It needs a VPR built
  with Qt6 graphics; set one up as in [Floorplan viewer (VPR graphics)](getting-started.md). When VPR
  exits early the Flow log says so and names the setting. The button is disabled, with the reason
  as its tooltip, when `vpr_gui` is set to a file that does not exist.

Project > Refresh results (F5) re-reads `wyrd.db`; it also happens after each flow run.

## Menus

| Menu | Items |
|---|---|
| File | New Project... (runs `wyrd init` in a folder you choose), Open Project... (Ctrl+O), Recent, Save wyrd.toml (Ctrl+S), Quit (Ctrl+Q) |
| Project | Run flow (Ctrl+R), Cancel (Ctrl+.), Refresh results (F5), Add design..., Settings... |
| Tools | Simulate (Ctrl+T), Midgard III (Verilog Town), Midgard III Level Editor |
| View | show or hide the docks |
| Help | About (credits of the tools and papers Wyrd builds on) |

**Settings...** edits `machine.toml` (the table of {doc}`getting-started`) with one field per key.
The Simulate and Midgard entries are covered in {doc}`simulation` and {doc}`midgard`.
