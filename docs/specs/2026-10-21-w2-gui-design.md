# W2: the Wyrd-I GUI (design)

Status: decisions 1 to 6 approved by Peter, 2026-10-21; the rest is the author's resolution of
everything those decisions left open (Section 16 lists what Peter may still change). Plan:
`docs/plans/2026-10-21-w2-gui-plan.md`. Builds on W1 (`docs/specs/2026-10-21-w1-runner-design.md`).

## 1. Goal

A desktop window over a W1 project: browse designs, files, recipes and archs; read Verilog;
edit `wyrd.toml` with live validation; run the flow and watch it; read results as a
Quartus-style report tree; see Odin III and VPR errors and warnings with click-through to the
source line; open VPR's own floorplan graphics; edit the machine settings. The GUI adds no
analysis of its own. It reads what W1 wrote (`wyrd.db`, run directories) and starts what W1
provides (`wyrd run`).

## 2. Decisions (approved, encoded verbatim)

| # | Decision | Choice |
|---|---|---|
| 1 | Packaging | `wyrd[gui]` extra (PySide6), command `wyrd-gui`. Core `wyrd` stays standard-library-only at runtime |
| 2 | Main window | Left project tree (designs, files, recipes, archs from `wyrd.toml`). Centre tabs: source viewer (read-only, simple Verilog highlighting) and the report. Bottom Messages pane: errors and warnings parsed from Odin III and VPR step logs; clicking one opens `file:line`. Flow panel: runs `wyrd run` as a subprocess (`QProcess`), per-run progress from its stdout lines, cancel is SIGINT. Settings dialog edits `machine.toml` (`settings.write_machine_file` / `settings.load`). About has a citations table (VTR, Odin II, Odin, Odin III, ABC, Yosys/Parmys, slang, PySide6/Qt, pygame-ce, Verilog Town, GraphCrunch, theryx, Gate-Breaker) from one data file shared with the docs |
| 3 | Project editing | `wyrd.toml` text editor with live validation through `project.load_project` (errors shown with line), plus an "Add design" dialog |
| 4 | Report | Quartus-style tree: Summary (status, LUTs, CLBs, hard blocks, Fmax = 1000 / crit_path_ns MHz, min channel width), per-step logs, Compare view (`report.compare`). Per-module resource use is W2.1 (out of scope) |
| 5 | Floorplan | A button that launches VPR's own graphics on the run (`vpr ... --disp on`, replaying the run's net, place and route files) |
| 6 | Tests | Logic in Qt-free modules (models, parsers) under `unittest`; one offscreen smoke test (`QT_QPA_PLATFORM=offscreen`) that opens the main window on the samples project; CI installs PySide6 for that job |

Also decided here (author):

| # | Decision | Choice |
|---|---|---|
| 7 | Windows | Run under WSL with WSLg. No Windows-specific code, no `sys.platform == "win32"` branch, no Windows packaging |
| 8 | Windows of the app | One main window. Dialogs are modal. No MDI, no second project window (File > Open replaces the open project) |
| 9 | State | `QSettings("wyrd", "wyrd-gui")`: `lastProject`, `recentProjects` (at most 8), `geometry`, `windowState`. The last project reopens at start if its `wyrd.toml` still exists |
| 10 | Finding a project | `wyrd-gui [PROJECT_DIR]`, else File > Open Project (a directory that contains `wyrd.toml`), else File > Recent, else the last project. File > New Project runs `wyrd.cli.main(["init", DIR])` |
| 11 | Qt distribution | Extra pins `PySide6-Essentials>=6.6,<7` (QtCore, QtGui, QtWidgets only; no WebEngine or 3D, a far smaller download). It provides the same `PySide6` import. All PySide6 names used in the plan were checked to exist in 6.12.0 |
| 12 | Where logic lives | Qt-free: `wyrd/guimodel/` and `wyrd/citations.py`. Qt: `wyrd/gui/`. Nothing outside `wyrd/gui/` may import PySide6 (a test enforces it) |

## 3. Facts about W1 output that the design rests on

Read from a real run directory (`wyrd run` on `samples/`, 2026-10-21) and from the sources.

Run directory `runs/<design>/<arch>/<key12>/`, per step `<n>-<step>/` holding `cmd.sh`,
`stdout.log`, `stderr.log`, `time.json`, and for the `odin3-flow` step:

| File | Content |
|---|---|
| `out/summary.json` | `luts`, `clbs`, `hard_blocks` (object), `min_chan_width`, `crit_path_ns`, `wirelength`, `seconds` |
| `out/odin3/odin3.log` | first line `$ <command>`, then `odin3: info: ...`, `odin3: warning: ...`, `odin3: error: ...` |
| `out/vpr/vpr.log` | the `run_vtr_flow.py` command and its result line |
| `out/vpr/run/vpr_stdout.log` | VPR's own log (`Warning N: ...`, `Error N: ...`) and its final command line |
| `out/vpr/run/top.pre-vpr.blif` | the circuit VPR read |
| `out/vpr/run/top.net.post_routing` | the only packed-netlist file kept |

**Finding that shapes decision 5.** `odin3-flow` calls `run_vtr_flow.py` with
`-delete_intermediate_files -delete_result_files`, so the run directory holds no `.net`,
`.place` or `.route` file. A pure replay of stored files is not possible today. Section 11 says
what the Floorplan button does instead (it re-runs VPR with the same inputs; VPR is
deterministic for a given seed and options) and uses stored files automatically if a future
Odin III option keeps them.

Other facts:

- `wyrd run` prints nothing per run until it finishes (the CLI drops the scheduler's log). The
  GUI needs progress, so Section 9 adds a `--progress` flag.
- `load_project` takes a path and reads the file; the editor needs to validate unsaved text.
  Section 9 adds a `text` argument.
- `settings.load` reads the machine file from `machine_path()` only; the dialog needs to validate
  an unsaved file. Section 9 adds a `machine_file` argument.

## 4. Modules

Qt-free (`unittest` covers all of it):

| Module | Job |
|---|---|
| `wyrd/citations.py` | `Citation` dataclass, `load()`, `render_markdown()`; reads `wyrd/data/citations.toml`; `python -m wyrd.citations` prints `docs/CITATIONS.md` |
| `wyrd/guimodel/logparse.py` | Odin III and VPR log lines to `Message`; `step_messages(step_dir)`; `resolve_location` |
| `wyrd/guimodel/projmodel.py` | `project_tree(project)` to `TreeNode`s |
| `wyrd/guimodel/runs.py` | rows from `wyrd.db` to `RunInfo`; summary rows; Fmax; step directories and their logs |
| `wyrd/guimodel/verilog_lex.py` | line tokenizer for highlighting |
| `wyrd/guimodel/tomledit.py` | `validate_text`, `add_design`, `relative_files` |
| `wyrd/guimodel/machine.py` | machine-settings form fields, read, validate, render, save |
| `wyrd/guimodel/flowcmd.py` | `wyrd run` argv, progress line parser, `FlowProgress` |
| `wyrd/guimodel/floorplan.py` | `plan_floorplan(run_dir)` to a VPR command |

Qt (`wyrd/gui/`, needs `wyrd[gui]`):

| Module | Class | Job |
|---|---|---|
| `app.py` | `main()` | argument parsing, `QApplication`, window |
| `mainwindow.py` | `MainWindow` | menus, docks, tabs, `open_project`, state |
| `projecttree.py` | `ProjectTree(QTreeWidget)` | shows `TreeNode`s; emits `file_activated(Path)` on double-click of a file |
| `sourceview.py` | `SourceView(QWidget)` | read-only text, `open_file(path, line=None)` |
| `highlighter.py` | `VerilogHighlighter(QSyntaxHighlighter)` | maps `verilog_lex` spans to formats |
| `messages.py` | `MessagesPane(QWidget)` | table of `Message`; emits `location_activated(Path, int)` |
| `reportview.py` | `ReportView(QWidget)` | run tree on the left, pages on the right, Compare, Floorplan button |
| `flowpanel.py` | `FlowPanel(QWidget)` | Run, Cancel, progress, process log, floorplan process |
| `editor.py` | `TomlEditor(QWidget)` | `wyrd.toml` text, Save, live validation, Add design |
| `adddesign.py` | `AddDesignDialog(QDialog)` | name, files, top, add-to-sweep |
| `settingsdialog.py` | `SettingsDialog(QDialog)` | machine.toml form |
| `about.py` | `AboutDialog(QDialog)` | version, licence, citations table |

## 5. Main window

    +---------------------------------------------------------------+
    | File  Project  View  Help                                     |
    +-----------------+---------------------------------------------+
    | Project tree    |  [ Source | Report | wyrd.toml ]  (tabs)    |
    |  Designs        |                                             |
    |   single        |                                             |
    |    file.v       |                                             |
    |  Recipes        |                                             |
    |  Archs          |                                             |
    +-----------------+---------------------------------------------+
    | [ Messages | Flow ]  (bottom dock, tabbed)                    |
    +---------------------------------------------------------------+

- **Menus.** File: New Project, Open Project (Ctrl+O), Recent, Save wyrd.toml (Ctrl+S), Quit
  (Ctrl+Q). Project: Run flow (Ctrl+R), Cancel (Ctrl+.), Refresh results
  (F5), Add design, Settings. View: the two docks. Help: About.
- **Project tree.** Top level `Designs`, `Recipes`, `Archs`. A design node has its name (and
  `top` in the label when set) and one child per file (path relative to the project root).
  Recipe nodes list their step `use` names as children. Arch nodes are the distinct `arch`
  values of `project.runs`, sorted. Double-click a file: open it in the Source tab.
- **Source tab.** Read only. Label with the path, then the text. Verilog highlighting for
  `.v .sv .vh .svh`; other files are plain. Files over 2,000,000 bytes are not loaded (a
  message in the view). Undecodable bytes are replaced.
- **Report tab and Messages pane.** Sections 6 and 7.
- **wyrd.toml tab.** Section 10.
- **Errors in the GUI itself.** A project that fails to load keeps the window open: the status
  bar and the editor tab show the `ConfigError` (`wyrd.toml:LINE: message`). The editor tab is
  then the only enabled tab, so the user can fix it.

State persistence (decision 9): saved in `closeEvent`; `restoreGeometry` and `restoreState` at
start. The `QSettings` object is passed into `MainWindow`, so tests use a temporary file.

## 6. Messages pane: log parsing

The pane shows the messages of the run selected in the Report tab (empty with the hint "Select
a run in the Report tab" otherwise). Sources, per step directory of the run: every `*.log`
found under it (`rglob`), i.e. `stdout.log`, `stderr.log`, `out/odin3/odin3.log`,
`out/vpr/vpr.log`, `out/vpr/run/vpr_stdout.log`. Duplicates (same severity, tool, text, file,
line) are shown once.

Patterns, from real lines. Odin III prints `odin3: <level>: <message>` for levels `error`,
`warning`, `info`, `debug` (`odin3/src/util/log.c`: `level_names`, format `"odin3: %s: %s\n"`).
VPR prints `Warning <N>: <text>` on stdout and `Error <N>: <text>` on stderr
(`libs/liblog/src/log.cpp`), and an error carries `Type:`, `File:`, `Line:`, `Message:` lines
(`vpr_print_error` in `vpr/src/base/vpr_api.cpp`).

| Source | Real line | Result |
|---|---|---|
| Odin III, located | `odin3: error: neg_e8_mixed.in.blif:7: cover mixes on-set and off-set rows (output 0 after 1)` | error, file `neg_e8_mixed.in.blif`, line 7 |
| Odin III, located, column, inline severity | `odin3: warning: tri_out.v:5:10: warning: tri-state driver of output port 'q': --vtr-compat drops the enable` | warning, file `tri_out.v`, line 5, col 10, text without the inline `warning: ` |
| Odin III, located after a prefix | `odin3: error: write_blif: --vtr: neg_e1_fe.in.blif:5: $_DFF_N_ '$c4': falling-edge flip-flop; VPR accepts only rising-edge latches (lower inverts the clock)` | error, file `neg_e1_fe.in.blif`, line 5, text keeps the prefix |
| Odin III, tool prefix | `odin3: error: abc: script.abc:3: command 'foo' failed` | error, file `script.abc`, line 3 |
| Odin III, unlocated | `odin3: warning: flatten: 2 modules are no longer instantiated` | warning, no file |
| Odin III, `info`/`debug` | `odin3: info: pass proc: 0.310 ms` | ignored |
| VPR warning | `Warning 1: Treated 1 constant nets as global which will not be routed (to see net names increase packer verbosity).` | warning, tool vpr, no file |
| VPR error | `Error 1: ` then `Type: Packing`, `File: vpr/src/pack/x.cpp`, `Line: 120`, `Message: text` | error, tool vpr, text `Packing: text (vpr/src/pack/x.cpp:120)`, no user file (the click opens the log at the `Error` line) |
| Upper-case | `WARNING: something` | warning, tool odin3, no file |

Rules, exact:

- Odin III line regex: `^odin3: (?P<level>error|warning): (?P<rest>.*)$`.
- Location regex, applied with `re.search` to `rest`:
  `(?P<file>[^\s:'"]+\.[A-Za-z0-9_]+):(?P<line>\d+)(?::(?P<col>\d+))?: (?:(?:error|warning): )?`.
  The text is `rest` with the matched location removed when it is at the start of `rest`,
  otherwise `rest` unchanged. (`--vtr:` does not match because a digit must follow the colon.)
- VPR warning regex: `^Warning (?P<n>\d+): (?P<text>.*)$`. VPR error header:
  `^Error (?P<n>\d+): ?(?P<text>.*)$`; the following lines `Type: `, `File: `, `Line: `,
  `Message: ` (any subset, in that order, directly after the header or after one blank line)
  are folded into the one message.
- Upper-case fallback regex: `^(?P<level>WARNING|ERROR)[: ] ?(?P<text>.*)$`, tool odin3.
- Message fields: `severity` (`error` or `warning`), `tool` (`odin3` or `vpr`), `text`, `file`
  (string as printed, or `None`), `line`, `col`, `log` (the log path), `log_line` (1-based).
- Click target: `resolve_location(msg, search_dirs)` returns `(path, line)`. Try the file as
  absolute, then `search_dir / file` for each search dir (the project root, the directories of
  the run's design files, the step directory, its `out` directory), then a unique design file
  with the same basename. If none exists, the target is `(msg.log, msg.log_line)`. The source
  viewer opens the target and highlights the line.

## 7. Report tab

Left, a `QTreeWidget` (the run tree); right, a `QStackedWidget` page for the selected node.

    All runs                 table of every run (report.table)
    <design> / <arch>        one node per run (latest per identity)
        Summary              key/value table
        Step 0: odin3-flow   children: one node per log file of the step
        ...
    Compare                  Compare view

- **Run label.** `design / arch`; the recipe is added when the project has more than one recipe
  (`recipe`), and the params JSON when non-empty, as `report.table` does (same `latest_per_run`
  identity).
- **Summary rows**, in this order: `Status`; `LUTs` (`luts`); `CLBs` (`clbs`); `Hard blocks`
  (one row per `hard_blocks.<type>` metric, label `<type>`; one row `Hard blocks` = `none` if there are none);
  `Fmax (MHz)` = `1000 / crit_path_ns` (`n/a` when the metric is missing or not positive);
  `Min channel width` (`min_chan_width`); `Critical path (ns)` (`crit_path_ns`); `Run
  directory`; `Run key`. Numbers are formatted with `report.number`; a missing metric shows
  `n/a`.
- **Log node.** The file in a read-only text view (same size limit as the source viewer).
- **Selecting a run node** (or any child) sets the Messages pane to that run.
- **Compare.** A button "Choose other project..." (a directory with `wyrd.db`) fills a table
  from `report.compare(a_rows, b_rows, None)` (a is the open project, b the chosen one) and a
  label from `report.unmatched`. Without a chosen project the page says so.
- **Floorplan button** above the pages, enabled when a run node is selected and
  `plan_floorplan` accepts it (the tooltip shows the reason when not).
- **Refresh.** F5 and after each flow run: re-read `wyrd.db` with `Store.open_readonly`
  (no db file: the tree shows only "No results yet. Run the flow.").
- Per-module resource use is W2.1 and is not built.

## 8. Flow panel

- Controls: Run, Cancel, "Force" check box (`--force`), "Jobs" spin box (0 = machine setting),
  "Memory budget" line edit (empty = machine setting), a progress bar, a status label, a text
  log.
- Run: `QProcess` with program `sys.executable` and arguments `-m wyrd.cli run --project DIR
  --progress [--force] [--jobs N] [--mem-budget X]` (built by `flowcmd.run_argv`). Stdout and
  stderr are read separately; stdout lines are parsed, stderr lines are shown in the log
  prefixed `stderr: `.
- Progress lines (added to W1 by Section 9): `plan: <N> to run, <M> reused` once, then one line
  per finished run `<design>/<arch> [<key12>] <status>` with an optional `: <message>`.
  `FlowProgress` sets the bar to `done / N`; with no plan line yet it is busy (range 0, 0).
- The CLI's final lines (`ok single EArch 746b2e6ac981`) and any other line go to the log
  unparsed.
- Cancel: send SIGINT with `os.kill(pid, signal.SIGINT)` (pid from `QProcess.processId()`);
  W1 stops the steps and records `cancelled`. If the process is still running 30 s later, call
  `QProcess.terminate()`. Cancel is enabled only while running.
- End: exit code 0 "all runs ok", 1 "some runs not ok", 2 "configuration error (see log)"; the
  panel then asks the window to refresh results. Run is disabled while a process runs and while
  the open project has a configuration error. The window refuses to quit while a flow runs
  unless the user confirms; confirming sends SIGINT and waits for the process.
- The bottom dock tabs are Messages and Flow. Flow also hosts the floorplan process output.

## 9. Changes to W1 (core stays stdlib only)

Small, backward compatible, each with a test:

1. `project.load_project(path, text=None)`: when `text` is given it is parsed instead of reading
   the file; globs still resolve against `path`'s directory; `ConfigError.path` is `path`.
2. `settings.load(project_run, cli, machine_file=None)`: when given it replaces
   `machine_path()` as the machine file. New public `settings.default_values()` (returns the
   built-in defaults dict) and `settings.machine_layout()` (returns `{table: keys}` for
   `resources` and `defaults`, as the machine file is laid out; tools are `odin3`,
   `odin3_flow`, `vtr_root`).
3. `wyrd run --progress`: prints the scheduler's log to stdout, flushed, line by line.
4. `sched.run_all` logs `plan: <N> to run, <M> reused` once, after deciding which runs to do and
   before starting any.

## 10. Editing

**wyrd.toml tab.** A `QPlainTextEdit` (monospace) with the file's text. Typing restarts a 400
ms `QTimer`; on timeout `tomledit.validate_text(path, text)` runs `load_project(path, text=...)`.
No error: a green "Valid: N runs" label. Error: the message (without the path prefix) and the
line; the line is highlighted (`QTextEdit.ExtraSelection` through
`QPlainTextEdit.setExtraSelections`) and a click on the label moves the cursor there. Save
(Ctrl+S) writes the text if it validates (UTF-8, same path); if it does not validate, a
confirmation asks whether to save anyway. After a save with a valid file the project reloads
(tree, runs, report). The editor warns before a reload or quit that would drop unsaved text.

**Add design dialog.** Fields: Name (required, must not already be a design name), Files (a
list filled by a multi-select file dialog; shown as paths relative to the project root, with
`/` separators; at least one), Top (optional), check box "Add to [sweep] design". OK calls
`tomledit.add_design(text, name, files, top, add_to_sweep)` on the editor text and puts the
result in the editor (unsaved), so the live validation reports problems. `add_design` appends,
after a blank line, `[[design]]`, `name = "NAME"`, `files = ["a.v", "b.v"]` and `top = "TOP"` when
given; with the check box it also appends `, "NAME"` before the closing bracket of the
`design = [...]` list that follows the `[sweep]` header. If that list cannot be found it raises
`ValueError` and the dialog shows "Cannot edit [sweep] design automatically; add the name by
hand" while still adding the block. Strings are written with `json.dumps`, which gives valid TOML
basic strings for these values.

## 11. Floorplan, Settings, About

**Floorplan.** `floorplan.plan_floorplan(run_dir: Path) -> FloorplanPlan | str` (a string is the
reason it is not possible). Inputs found in the run: the step directory with
`out/vpr/run/vpr_stdout.log`; from it the line matching
`^(?P<vpr>\S*/vpr)\s+(?P<arch>\S+\.xml)\s+(?P<circuit>\S+)\s+(?P<opts>.*)$` (VPR's own echo of
its final command, e.g. `/.../vpr k6_frac_N10_frac_chain_mem32K_40nm.xml top --circuit_file
top.pre-vpr.blif --max_router_iterations 100 --route --analysis --route_chan_width 42`); the full
arch path from `--arch PATH` in that step's `cmd.sh` (the log shows only the file name); the
channel width from `--route_chan_width N` in `opts`. The VPR binary must exist.

- **Replay** (when `top.net`, `top.place` and `top.route` all exist next to
  `top.pre-vpr.blif`): `VPR ARCH CIRCUIT --circuit_file BLIF --net_file top.net --place_file
  top.place --route_file top.route --route --analysis --route_chan_width W --disp on
  --graphics_pause final_stage`. VPR documents that a stage that is not requested is loaded from
  its file (`vpr --route` reads `.place`; `command_line_usage.rst`, options `--net_file`,
  `--place_file`, `--route_file`, `--disp`, `--graphics_pause`).
- **Re-run** (today's case, the files were deleted): `VPR ARCH CIRCUIT --circuit_file BLIF
  --max_router_iterations N --pack --place --route --route_chan_width W --disp on
  --graphics_pause final_stage`, where `N` is copied from `opts` if present (default omitted).
  Same inputs, default seed and options give the same result as the stored run.
- Working directory: `<run_dir>/floorplan/` (created; VPR writes its files there, nothing in
  the run's own step directories changes). All input paths are absolute.
- Started with `QProcess` from the Flow panel; output goes to the Flow log. If the process exits
  with a non-zero code in under 5 s the panel reports "VPR exited early; is this VPR built with
  graphics (Qt6)? See the Flow log." The GUI never inspects the VPR build.
- Supported runs: those with an `odin3-flow` step with `vpr = true`. Otherwise the button is
  disabled with the reason from `plan_floorplan`.
- Follow-up outside W2 (not blocking): an Odin III `odin3-flow --keep-vpr-files` option would
  make Replay the normal path.

**Settings dialog.** A form generated from `machine.FIELDS`: group boxes `tools`, `resources`,
`defaults`; line edits for strings and sizes (`60%`, `24G`), spin boxes for integers, a
`QComboBox` for `launcher` (`systemd`, `plain`), line edits for floats. Values start from
`default_values()` overlaid by the existing machine file. OK validates (`machine.validate` writes
a temporary file and calls `settings.load(None, {}, machine_file=tmp)`; an error stays in the
dialog), then writes `machine_path()` (creating the directory). Unknown tool keys already in the
file are kept. The dialog shows the file path. Settings take effect for the next flow run
(the subprocess reads the file).

**About.** Text: Wyrd-I, version (`importlib.metadata.version("wyrd")`), MIT licence, a one-line
description, and a table of the citations (columns Name, Kind, Role, Reference, Link). Rows come
from `citations.load()`. `docs/CITATIONS.md` is generated from the same file by
`python -m wyrd.citations`, and a test fails when the committed file differs.

## 12. Citations data

`wyrd/data/citations.toml`, array of tables `[[citation]]`, keys `id`, `name`, `kind` (`paper`,
`software` or `project`) required; `role`, `authors`, `year` (integer), `title`, `venue`, `url`,
`license` optional. Entries (ids): `vtr`, `odin2`, `odin`, `odin3`, `abc`, `yosys`, `parmys`,
`slang`, `qt`, `pygame-ce`, `verilog-town`, `graphcrunch`, `theryx`, `gate-breaker`. The plan
gives the content of each entry the author could state with confidence; entries with no
verified detail carry `id`, `name`, `kind` only. Peter fills the rest (open question 1).

## 13. Packaging and CI

- `pyproject.toml`: `[project.optional-dependencies] gui = ["PySide6-Essentials>=6.6,<7"]`;
  `[project.gui-scripts] wyrd-gui = "wyrd.gui.app:main"`; `[tool.setuptools.package-data]
  wyrd = ["data/*.toml"]`. `dependencies` stays `[]`.
- CI (`.github/workflows/ci.yml`): `lint` job (Python 3.11 and 3.12): `pip install ".[gui]" ruff
  mypy`, `ruff check .`, `mypy --strict wyrd tests`. `test` job (3.11 and 3.12): no PySide6;
  `python -m unittest discover -s tests -t . -v` (GUI tests skip themselves). `gui` job
  (3.12): `sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libdbus-1-3 libfontconfig1`,
  `pip install ".[gui]"`, `QT_QPA_PLATFORM=offscreen python -m unittest tests.test_gui_smoke
  -v`.
- If `mypy --strict` rejects PySide6 usage that cannot be fixed by correct typing, stop and ask
  Peter; no suppressions (repo rule).

## 14. Tests

- Qt-free `unittest` modules: `test_citations`, `test_logparse`, `test_projmodel`, `test_runs`,
  `test_verilog_lex`, `test_tomledit`, `test_machine`, `test_flowcmd`, `test_floorplan`, plus
  W1 additions in `test_project`, `test_settings`, `test_cli`, `test_sched`, `test_packaging`,
  and `test_qt_free` (no import of PySide6 outside `wyrd/gui/`).
- Log fixtures: `tests/data/logs/odin3_sample.log` and `vpr_sample.log` hold the real lines of
  Section 6.
- `tests/test_gui_smoke.py` (skips without PySide6): sets `QT_QPA_PLATFORM=offscreen`, builds a
  `QApplication`, a `MainWindow` with a temporary-file `QSettings`, calls
  `open_project(samples)`, asserts the tree (3 top-level items, 3 designs with 1, 3, 3 files),
  the editor shows "Valid: 6 runs", opens a result fixture and asserts the report tree and the
  Messages pane count, then closes. No tools, no network, no real VPR.
- No GUI test drives `QProcess` against real tools. The Flow panel is covered by `flowcmd` unit
  tests plus one smoke assertion that `Run` is enabled for a valid project.

## 15. Not in W2

Per-module resource use (W2.1), schematic viewer, waveform or simulation views (W3),
Verilog Town (W4), editing Verilog, editing recipes other than as text, multi-project windows,
Windows-native builds, running steps without `wyrd run`, any change to Odin III or VPR.

## 16. Open questions (with recommendation)

1. Citation detail for `verilog-town`, `theryx`, `gate-breaker`, and a check of the others:
   recommend Peter supplies title, year, URL, role in one message; W2 ships them blank until then.
2. `PySide6-Essentials` instead of the full `PySide6` wheel: recommend yes (same import, smaller).
3. Keep the floorplan re-run fallback until Odin III can keep the VPR result files: recommend yes.
