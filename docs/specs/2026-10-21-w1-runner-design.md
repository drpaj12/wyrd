# W1: the Wyrd experiment runner (design)

Status: approved in brainstorming with Peter, 2026-10-21; this file is for his review.
Wyrd-I is the GUI wrapper around Odin III; W1 is its command-line core. The GUI (W2), simulation
(W3) and Verilog Town (W4) come later and use W1. The RTL schematic viewer (W5) is not a goal.

## 1. Goal

Run CAD experiments of the VTR kind (Odin III, then ABC, then VPR, and later more tools) as
projects: say *what* (designs, archs, parameters), *where* (tools and files on this machine),
*how* (a recipe of steps) and *to where* (a results store), then get tables that read like
Odin III's own results. Peter's aim is to set up the reverse-engineering and placement
experiments quickly; W1 is kept small.

**Acceptance (Section 8):** three sample projects, run on k6 and EArch through `odin3-flow` and
VPR, give `wyrd table` rows equal to `odin3-flow` run directly on the same files.

## 2. Decisions

| # | Decision | Choice |
|---|---|---|
| 1 | How an experiment is defined | TOML project file (`wyrd.toml`); custom steps are Python plugins |
| 2 | Relation to Odin III | Wyrd calls only public commands (`odin3`, `odin3-flow`, `vpr`, `abc`) and reads their files (`summary.json`, logs). It never imports Odin III's Python; `tools/vtr-qor` stays Odin III's regression harness |
| 3 | Results | One directory per run plus one SQLite index (`wyrd.db`) per project; projects are self-contained |
| 4 | Execution | Local parallel scheduler with memory budgets; the launcher is an interface (a cluster backend can be added later) |
| 5 | Machine differences | Per-machine settings file, separate from the project |
| 6 | Acceptance | Three small samples (single file; multi-file; multi-file with multipliers, memories, flip-flops) |

## 3. Components

Python 3.11 or later (stdlib `tomllib`, `sqlite3`); no runtime dependencies.

| Module | Job |
|---|---|
| `wyrd/project.py` | Load and validate `wyrd.toml`; expand the sweep into run specs (design × arch × parameters) |
| `wyrd/steps/` | Step interface: `command(run) -> list[str]` and `collect(step_dir) -> list[Metric]`. Built in: `odin3-flow`, `odin3` (any `-p` script), `vpr`, `abc`, `shell`. Plugins register under the entry-point group `wyrd.steps` |
| `wyrd/settings.py` | Machine settings and precedence (Section 6) |
| `wyrd/store.py` | Run key, run directories, `wyrd.db` |
| `wyrd/sched.py` | Slots, smallest-first order, memory estimate and budget; `Launcher` interface with `systemd` (`systemd-run --user --scope -p MemoryMax=`) and `plain` versions |
| `wyrd/report.py` | `table` (CSV, Markdown) and `compare` (across runs or two project databases) |
| `wyrd/cli.py` | `wyrd init | run | status | table | compare | script | config` |
| `samples/` | The three acceptance projects |

Project file:

```toml
[project]
name = "samples"

[[design]]
name = "multi"
files = ["designs/multi/src/arith/adder.v", "designs/multi/src/ctrl/pick.v",
         "designs/multi/src/top.v"]
top = "top"

[recipe.vtr]
steps = [{ use = "odin3-flow", target = "vtr", vpr = true }]

[sweep]
recipe = ["vtr"]
design = ["single", "multi", "dsp"]
arch = ["k6_frac_N10_frac_chain_mem32K_40nm", "EArch"]

[run]                      # experiment settings only (Section 6)
step_timeout = 3600
```

Tool locations are machine settings (Section 6); a project names tools, never paths on one
machine.

## 4. Data flow

1. **Expand** the sweep into run specs.
2. **Key** each run: SHA-256 over the recipe steps with resolved arguments, the content hash of
   every input file, the arch XML hash, and each tool's version string (`odin3 --version`, VPR's
   build line). The run directory is `runs/<design>/<arch>/<key[:12]>/`.
3. **Skip** a run whose key is in `wyrd.db` with status `ok` (`--force` re-runs).
4. **Schedule** smallest first (total input bytes). Step *n* runs in `<run>/<n>-<step>/` and
   writes `cmd.sh` (the exact command), `stdout.log`, `stderr.log`, and `time.json` (wall time,
   peak memory).
5. **Collect** metrics through the step's `collect()`. `odin3-flow` metrics are the keys of its
   `summary.json`, flattened: `luts`, `clbs`, `hard_blocks.<type>`, `min_chan_width`,
   `crit_path_ns`, `wirelength`, `seconds.<step>`. Wyrd adds no metric that the tool does not
   report.

`wyrd.db`:

| Table | Columns |
|---|---|
| `runs` | key, design, arch, recipe, params (JSON), status (`ok`, `fail`, `oom`, `timeout`, `cancelled`), started, ended, run_dir |
| `steps` | key, n, step, argv (JSON), exit_code, wall_s, peak_mem_bytes |
| `metrics` | key, step, name, value, unit |

`wyrd table` prints one row per design and arch by default, with the metric names above as
columns. `wyrd script <key>` writes `replay.sh` chaining each step's `cmd.sh`; it runs without
Wyrd.

## 5. Scheduling, memory and errors

- **Budget:** `mem_budget` (default 60% of `MemTotal`; WSL dies when memory runs out). Slots:
  `jobs` (default CPUs / 2).
- **Estimate:** with history, `history_factor` (1.25) × the highest peak seen for the same design,
  arch and step; without, `vpr_mem` (4 GB) for a VPR step and `other_mem` (2 GB) otherwise
  (Odin III's sweeps: gate designs under 0.2 GB on k6, the largest about 2.2 GB). A run starts only
  when its estimate fits the free budget.
- **Cap:** the systemd launcher sets `MemoryMax` to the estimate. An oom kill marks the run `oom`
  and records the peak; the next attempt gets `oom_retry_factor` (2.0) × the cap, once, if it fits
  the budget.
- **Preflight** (exit 2 on failure, before any run): every recipe tool resolves; `vtr_root` and
  the arch files exist; at least `disk_min_free` (20 GiB) on `disk_check_path` (`/mnt/c` on WSL);
  no other `wyrd run` holds the project lock (`.wyrd.lock`).
- **Errors:** config error `wyrd.toml:<line>: <message>`, exit 2. A step exiting non-zero marks
  its run `fail` and skips that run's later steps; other runs continue. `step_timeout` (3600 s)
  marks `timeout`. Ctrl-C stops running jobs, records them `cancelled`, and keeps finished runs.
- **Exit codes:** 0 every run `ok`; 1 some run not `ok`; 2 usage, config or preflight error.

## 6. Settings

Per machine: `~/.config/wyrd/machine.toml` (`$WYRD_CONFIG` overrides the path). `wyrd config
init` writes it with values detected on this machine; the W2 GUI's Settings dialog edits the same
file.

```toml
[tools]
odin3 = "odin3"
odin3_flow = "odin3-flow"
vtr_root = "/home/me/vtr-verilog-to-routing"

[resources]
mem_budget = "60%"           # or "24G"
jobs = 8
launcher = "systemd"         # systemd | plain
disk_min_free = "20G"
disk_check_path = "/mnt/c"   # "/" off WSL

[defaults]
vpr_mem = "4G"
other_mem = "2G"
history_factor = 1.25
oom_retry_factor = 2.0
step_timeout = 3600
```

Precedence, lowest first: built-in defaults; `machine.toml`; the project's `[run]` table
(experiment settings only, such as `step_timeout`; never `[tools]` or `[resources]`); command-line
flags. `wyrd config show` prints each effective value and its source.

## 7. Repository

- `pyproject.toml` (no runtime dependencies; console command `wyrd`), MIT (`LICENSE`).
- GitHub Actions: `ruff check`, `mypy --strict`, unit tests on Python 3.11 and 3.12.
- `main` protected: PRs and green CI only, as in Odin III. `CLAUDE.md` holds the repo rules.

## 8. Samples and tests

| Sample | Files | Exercises |
|---|---|---|
| `single` | `bm_DL_2_4_encoder.v` (Odin III `tests/micro`) | one file, pure logic |
| `multi` | Odin III `tests/golden/projects/multi_dir` (`src/arith/adder.v`, `src/ctrl/pick.v`, `src/top.v`) | several files in subdirectories, hierarchy |
| `dsp` | new for Wyrd (MIT): `top.v`, `mac.v` (multiply-accumulate), `buf_ram.v` (single-port RAM), registers with synchronous reset | multipliers, memories, flip-flops; hard blocks on k6 and EArch |

Each sample commits `expected/<arch>.json`: the `summary.json` metrics of `odin3-flow` run
directly on the same files (with the `odin3 --version` that produced them).

- **Unit tests** (`unittest`, no Odin III): fake `odin3-flow` and `vpr` scripts that write canned
  `summary.json` and logs. Cover sweep expansion, run keys, skip and reuse, settings precedence,
  preflight, the memory budget, and the `fail`, `oom`, `timeout` and `cancelled` paths.
- **Acceptance** `samples_match` (local only; skips without `odin3-flow` and `vtr_root`): runs the
  three samples on k6 and EArch; `wyrd table` must equal `expected/` (`seconds.*` excluded).

## 9. Not in W1

Include paths and defines: `odin3-flow` 1.0 takes only a file list (no `+incdir+`, `+define+`),
so W1 designs are plain file lists; project files (`.o3proj`, `.f`) need an `odin3-flow` option
first (an Odin III change, out of W1). GUI (W2), simulation (W3), cluster launcher, plugins beyond the built-in steps, the placement
experiment (P1, its own spec), any change to Odin III.
