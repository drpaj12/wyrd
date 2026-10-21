# W1 Experiment Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `wyrd`, a command-line runner that expands a TOML project into runs, executes them
under a memory budget, stores results in run directories plus `wyrd.db`, and prints tables that
match `odin3-flow`'s own results.

**Architecture:** a stdlib-only Python package. `project` expands the sweep, `store` keys and
records runs, `steps` turn a run into commands and read their outputs, `sched` runs steps through
a `Launcher` under the budget, `report` and `cli` sit on top. Odin III is only ever called as a
program.

**Tech Stack:** Python 3.11+ (`tomllib`, `sqlite3`, `subprocess`, `concurrent.futures`),
`unittest`, ruff, mypy `--strict`, GitHub Actions.

**Spec:** `docs/specs/2026-10-21-w1-runner-design.md` (cited as spec §N).

## Global Constraints

- Python 3.11 or later; no runtime dependencies; dev tools: ruff, mypy.
- `ruff check` and `mypy --strict` clean; tests are `unittest` under `tests/`.
- Wyrd never imports Odin III's Python; it runs `odin3`, `odin3-flow`, `vpr`, `abc` as programs.
- Exit codes: 0 every run `ok`; 1 some run not `ok`; 2 usage, config or preflight error (spec §5).
- Run statuses exactly: `ok`, `fail`, `oom`, `timeout`, `cancelled`.
- Defaults exactly: `mem_budget = "60%"`, `jobs` = CPUs // 2 (at least 1), `launcher = "systemd"`,
  `disk_min_free = "20G"`, `disk_check_path = "/mnt/c"` when `/proc/version` contains
  `microsoft`, else `"/"`, `vpr_mem = "4G"`, `other_mem = "2G"`, `history_factor = 1.25`,
  `oom_retry_factor = 2.0`, `step_timeout = 3600`.
- Machine settings path: `$WYRD_CONFIG`, else `~/.config/wyrd/machine.toml`.
- Arch name `A` resolves to `<vtr_root>/vtr_flow/arch/timing/A.xml`.
- Commit after each step that turns tests green; push the branch after each task.

## Review Focus

1. A design whose files glob matches nothing: config error naming the design, exit 2, not an
   empty run (Task 2, `test_empty_glob_is_config_error`).
2. Editing one input file after a run: that run's key changes and it re-runs; untouched runs are
   reused (Task 3, `test_key_changes_with_file_content`).
3. A tool missing from `PATH`: preflight exit 2 naming the tool, before any run directory is
   made (Task 5, `test_preflight_missing_tool`).
4. A second `wyrd run` on the same project while one is running: exit 2 "project is locked"
   (Task 5, `test_second_run_is_locked`).
5. `summary.json` with `null` metrics (VPR did not report one): those metrics are skipped, the run
   is still `ok` (Task 4, `test_flow_collect_skips_null`).

## Lanes

Task 1 first. Tasks 2, 3, 4 in parallel (disjoint files). Task 5 after 3 and 4. Task 6 after 5.
Task 7 last; it needs `odin3-flow` 1.0 and `VTR_ROOT` (local only).

---

### Task 1: Package skeleton, settings, CI

**Files:**
- Create: `pyproject.toml`, `wyrd/__init__.py`, `wyrd/units.py`, `wyrd/settings.py`,
  `wyrd/cli.py` (only `config` for now), `tests/__init__.py`, `tests/test_settings.py`,
  `.github/workflows/ci.yml`, `CLAUDE.md`, `README.md`, `.gitignore`

**Interfaces:**
- Produces:
  - `wyrd.units.parse_bytes(text: str, total: int | None = None) -> int` ("4G", "512M", "60%" of
    `total`; binary units, G = 2**30).
  - `wyrd.settings.Settings` (frozen dataclass): `tools: dict[str, str]`, `vtr_root: Path | None`,
    `mem_budget: int`, `jobs: int`, `launcher: str`, `disk_min_free: int`, `disk_check_path: Path`,
    `vpr_mem: int`, `other_mem: int`, `history_factor: float`, `oom_retry_factor: float`,
    `step_timeout: int`, and `sources: dict[str, str]` (field name to "default", "machine",
    "project" or "cli").
  - `tools` defaults: `{"odin3": "odin3", "odin3_flow": "odin3-flow"}`; `vtr_root` defaults to
    `$VTR_ROOT` when set.
  - `wyrd.settings.load(project_run: dict[str, object] | None, cli: dict[str, object]) -> Settings`.
  - `wyrd.settings.write_machine_file(path: Path) -> None` (detected values).
  - `PROJECT_KEYS = {"step_timeout"}`: the only keys a project `[run]` table may set.
  - CLI: `wyrd config init`, `wyrd config show` (one line per field: `name = value  (source)`).
- `pyproject.toml`: name `wyrd`, version `0.1.0`, `requires-python = ">=3.11"`, console script
  `wyrd = "wyrd.cli:main"`, build backend `setuptools`.
- CI: ruff, mypy `--strict wyrd tests`, `python -m unittest discover -s tests -t .`, matrix 3.11
  and 3.12.

- [ ] **Step 1: Failing tests** in `tests/test_settings.py`:
  `test_parse_bytes` (`parse_bytes("4G") == 4 * 2**30`, `parse_bytes("60%", 100) == 60`,
  `ValueError` on `"4X"`); `test_defaults` (no files: every Global Constraints default, every
  source `"default"`); `test_machine_overrides_default`; `test_project_run_only_step_timeout`
  (`[run] jobs = 3` raises `ValueError` naming `jobs`); `test_cli_wins`
  (`cli={"jobs": 2}` over machine `jobs = 8` gives 2, source `"cli"`); `test_config_init_roundtrip`
  (write, then load, gives the same values).
- [ ] **Step 2:** `python -m unittest tests.test_settings` fails (no module).
- [ ] **Step 3:** Implement `units.py`, `settings.py`, `cli.py` (`argparse`, sub-command `config`).
- [ ] **Step 4:** Tests pass; `ruff check .` and `mypy --strict wyrd tests` clean.
- [ ] **Step 5:** Commit "settings, config command, CI"; push.

### Task 2: Project file and sweep

**Files:**
- Create: `wyrd/project.py`, `tests/test_project.py`, `tests/data/proj_ok/wyrd.toml` and its tiny
  `.v` files

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `class ConfigError(Exception)` with `path: Path`, `line: int | None`; `str()` is
    `"<path>:<line>: <msg>"` or `"<path>: <msg>"`.
  - `Design(name: str, files: tuple[Path, ...], top: str | None)`;
    `StepSpec(use: str, args: dict[str, object])`; `Recipe(name: str, steps: tuple[StepSpec, ...])`;
    `RunSpec(design: Design, arch: str, recipe: Recipe, params: dict[str, object])`;
    `Project(root: Path, name: str, designs: dict[str, Design], recipes: dict[str, Recipe],
    run: dict[str, object], runs: tuple[RunSpec, ...])` (all frozen dataclasses).
  - `load_project(path: Path) -> Project`.
- Sweep: the product of `[sweep]` lists `recipe`, `design`, `arch`; any other `[sweep]` key is a
  parameter list, also in the product, stored in `params`. Order: recipe, design, arch, then
  parameters in file order.
- Line numbers: a `tomllib.TOMLDecodeError` keeps its own line; a semantic error uses the first
  line matching `^\s*(\[+[^\]]*<key>|<key>\s*=)` in the raw text, else no line.

- [ ] **Step 1: Failing tests:** `test_load_ok` (2 designs × 2 archs × 1 recipe = 4 runs, in the
  order above); `test_files_glob_sorted` (glob patterns are relative to the project root;
  `Design.files` holds the absolute paths, sorted); `test_empty_glob_is_config_error` (Review Focus 1; message names the design);
  `test_unknown_design_in_sweep` (ConfigError with the `design =` line); `test_syntax_error_line`
  (bad TOML at line 4 gives `line == 4`); `test_param_sweep` (`[sweep] seed = [1, 2]` doubles the
  runs; `params == {"seed": 1}` on the first).
- [ ] **Step 2:** Run, expect failures.
- [ ] **Step 3:** Implement `project.py`.
- [ ] **Step 4:** Tests pass; lint clean.
- [ ] **Step 5:** Commit; push.

### Task 3: Run keys and the store

**Files:**
- Create: `wyrd/store.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: `RunSpec` (Task 2) field names only; tests build `RunSpec` directly.
- Produces:
  - `run_key(spec: RunSpec, arch_xml: Path | None, tool_versions: dict[str, str],
    resolved_argv: list[list[str]]) -> str`: SHA-256 hex of a canonical JSON
    (`sort_keys=True`) of: the resolved argv of every step, `{path: sha256(content)}` of every
    design file, the arch XML's sha256 (or `null`), `tool_versions`, `params`.
  - `run_dir(root: Path, spec: RunSpec, key: str) -> Path` =
    `root / "runs" / design / arch / key[:12]`.
  - `class Store(path: Path)`: `begin(key, spec, run_dir) -> None` (status `running`),
    `finish(key, status: str) -> None`, `add_step(key, n, step, argv, exit_code, wall_s,
    peak_mem_bytes) -> None`, `add_metrics(key, step, metrics: list[Metric]) -> None`,
    `status(key) -> str | None`, `peak_mem(design, arch, step) -> int | None` (max over rows),
    `rows() -> list[dict[str, object]]` (one per run with its metrics).
  - `Metric(name: str, value: float, unit: str)` lives here.
- Schema exactly as spec §4 (tables `runs`, `steps`, `metrics`), plus `PRAGMA user_version = 1`.

- [ ] **Step 1: Failing tests:** `test_key_stable` (same inputs, same key);
  `test_key_changes_with_file_content` (Review Focus 2); `test_key_changes_with_tool_version`;
  `test_run_dir_layout`; `test_store_roundtrip` (begin, add_step, add_metrics, finish `ok`;
  `status == "ok"`; `rows()[0]["luts"] == 12.0`); `test_peak_mem_max`.
- [ ] **Step 2:** Run, expect failures.
- [ ] **Step 3:** Implement `store.py`.
- [ ] **Step 4:** Tests pass; lint clean.
- [ ] **Step 5:** Commit; push.

### Task 4: Steps

**Files:**
- Create: `wyrd/steps/__init__.py`, `wyrd/steps/flow.py`, `wyrd/steps/command.py`,
  `tests/test_steps.py`, `tests/fakes/odin3-flow` (Python script, executable)

**Interfaces:**
- Consumes: `Metric` (Task 3), `RunSpec`/`StepSpec` (Task 2), `Settings` (Task 1).
- Produces:
  - `class Step(Protocol)`: `name: str`; `tools: tuple[str, ...]` (names looked up in
    `Settings.tools`); `is_vpr: bool`; `command(run: RunSpec, step_dir: Path, settings: Settings)
    -> tuple[list[str], dict[str, str]]` (argv, extra environment); `collect(step_dir: Path) ->
    list[Metric]`.
  - `get_step(spec: StepSpec) -> Step`: built-ins by `use`, then entry-point group `wyrd.steps`
    (`importlib.metadata.entry_points(group="wyrd.steps")`); unknown name raises `KeyError`.
  - `arch_xml(settings: Settings, arch: str) -> Path` (Global Constraints rule).
  - `tool_path(settings: Settings, name: str) -> str`: `vpr` is `<vtr_root>/vpr/vpr`, `abc` is
    `<vtr_root>/build/abc/abc`, any other name is `settings.tools[name]`.
  - `tool_versions(settings: Settings, names: Iterable[str]) -> dict[str, str]`: stdout of
    `[tool_path, "--version"]` (10 s timeout), or `"unknown"` when that fails.
- `odin3-flow` step `tools` = `("odin3_flow", "odin3")`, plus `"vpr"` when `is_vpr`.
- `odin3-flow` step (`flow.py`): argv = `[tools["odin3_flow"], *files, "--top", top (if set),
  "--target", args.get("target", "vtr"), "--arch", arch_xml, "--vpr" or "--no-vpr", "--out",
  step_dir / "out"]`; env `VTR_ROOT`; `is_vpr` = the `vpr` arg (default True). `collect` reads
  `out/summary.json`: numbers kept, dicts flattened with `.` (`hard_blocks.multiply`,
  `seconds.vpr`), strings and `null` skipped; unit `"s"` for `seconds.*` and `crit_path_ns` gets
  `"ns"`, else `""`.
- `odin3`, `vpr`, `abc`, `shell` (`command.py`): one generic class; `args["argv"]` is a list of
  strings with placeholders `{files}` (expands to several words), `{top}`, `{arch_xml}`,
  `{step_dir}`, `{vtr_root}`; the first word is replaced by the tool path for `odin3`, `vpr`
  (`<vtr_root>/vpr/vpr`), `abc` (`<vtr_root>/build/abc/abc`). `collect` reads
  `step_dir/metrics.json` (flat `{name: number}`) if it exists, else nothing.

- [ ] **Step 1: Failing tests:** `test_flow_argv` (exact list for a 2-file design with top);
  `test_flow_collect_flattens` (`hard_blocks.multiply == 2.0`, `luts_note` absent);
  `test_flow_collect_skips_null` (Review Focus 5); `test_command_placeholders`
  (`{files}` expands to two words); `test_get_step_unknown` (`KeyError`);
  `test_fake_flow_end_to_end` (run `tests/fakes/odin3-flow` via the argv; it writes a canned
  `summary.json`; `collect` reads it).
- [ ] **Step 2:** Run, expect failures.
- [ ] **Step 3:** Implement the package and the fake.
- [ ] **Step 4:** Tests pass; lint clean.
- [ ] **Step 5:** Commit; push.

### Task 5: Scheduler, launchers, preflight

**Files:**
- Create: `wyrd/sched.py`, `wyrd/launch.py`, `wyrd/preflight.py`, `tests/test_sched.py`,
  `tests/test_preflight.py`, `tests/fakes/sleepy` (sleeps N s, allocates M MB, exits E)

**Interfaces:**
- Consumes: Tasks 1 to 4.
- Produces:
  - `class Launcher(Protocol)`: `start(argv, env, cwd, mem_cap: int, log_out: Path,
    log_err: Path) -> subprocess.Popen[bytes]`. `SystemdLauncher` prefixes
    `["systemd-run", "--user", "--scope", "--quiet", "-p", f"MemoryMax={mem_cap}",
    "-p", "MemorySwapMax=0"]`; `PlainLauncher` runs argv as is. Both start a new process group.
  - `wait_step(proc, timeout: int) -> StepResult(exit_code: int, wall_s: float,
    peak_mem_bytes: int, outcome: str)` using `os.wait4` for the child's `ru_maxrss` (KiB to
    bytes). On timeout: `SIGTERM` to the group, `SIGKILL` after 10 s, outcome `timeout`. Outcome
    `oom` when the systemd launcher's child ends by `SIGKILL` and no timeout fired; else `ok` for
    exit 0, `fail` otherwise.
  - `estimate(store, design, arch, step, is_vpr, settings) -> int`: history ×
    `history_factor`, else `vpr_mem` or `other_mem`.
  - `run_all(project, settings, store, force: bool) -> dict[str, str]` (key to status). The key
    of each run comes from `run_key` with `tool_versions` of its steps' tools, computed once per
    tool per call;
    smallest first by total input bytes; `ThreadPoolExecutor(max_workers=settings.jobs)`; a
    `threading.Condition` guards the free budget; a step waits until its estimate fits; a run
    whose estimate exceeds the whole budget fails at once with status `oom` and a message.
    One `oom` retry at `oom_retry_factor` × cap if that fits the budget. `SIGINT`: kill every
    running group, mark those runs `cancelled`, return.
  - Each step writes `cmd.sh` (`#!/bin/sh`, `cd`, env exports, `shlex.join(argv)`),
    `stdout.log`, `stderr.log`, `time.json` (`wall_s`, `peak_mem_bytes`).
  - `preflight(project, settings) -> list[str]` (empty means ok): each recipe tool resolves
    (`shutil.which` or an existing path); `vtr_root` exists and every arch XML exists when a
    step needs them; `shutil.disk_usage(disk_check_path).free >= disk_min_free`; and
    `acquire_lock(root) -> int` (fd, `fcntl.flock` `LOCK_EX | LOCK_NB` on `.wyrd.lock`, error
    "project is locked" when held).

- [ ] **Step 1: Failing tests** (plain launcher; fakes; no systemd needed):
  `test_smallest_first`; `test_budget_serialises` (budget 1 GB, two steps estimated 0.8 GB each,
  start times do not overlap); `test_fail_skips_later_steps`; `test_timeout_status`
  (`step_timeout = 1`, fake sleeps 5 s); `test_reuse_ok_run` (second `run_all` starts nothing);
  `test_force_reruns`; `test_cmd_sh_replays` (running `cmd.sh` gives the same exit code);
  `test_preflight_missing_tool` (Review Focus 3); `test_second_run_is_locked` (Review Focus 4);
  `test_disk_check` (`disk_min_free` above free space gives one message).
  Systemd-only (skip unless `systemd-run --user --scope true` works): `test_oom_status` (fake
  allocates 300 MB under a 100 MB cap).
- [ ] **Step 2:** Run, expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Tests pass; lint clean.
- [ ] **Step 5:** Commit; push.

### Task 6: Reports and the command line

**Files:**
- Create: `wyrd/report.py`, `tests/test_cli.py`
- Modify: `wyrd/cli.py`

**Interfaces:**
- Consumes: Tasks 1 to 5.
- Produces commands (spec §3): `wyrd init [DIR]` (writes a commented `wyrd.toml`),
  `wyrd run [--project DIR] [--force] [--jobs N] [--mem-budget X]` (preflight, lock, `run_all`;
  prints one line per finished run: status, design, arch, key[:12]), `wyrd status` (counts per
  status), `wyrd table [--format md|csv] [--metrics a,b]` (one row per design × arch from
  `Store.rows()`; columns `design`, `arch`, `status`, then metric names sorted),
  `wyrd compare A B` (two project dirs; rows matched on design × arch; per metric `A`, `B`,
  `B/A`), `wyrd script KEY` (writes `replay.sh` chaining each step's `cmd.sh`, prints its path).
  Exit codes per Global Constraints.

- [ ] **Step 1: Failing tests** (fake tools, `PlainLauncher`, temp project):
  `test_init_then_run_ok` (exit 0); `test_run_exit_1_on_fail`; `test_run_exit_2_on_config_error`;
  `test_table_md` (exact header line `| design | arch | status | luts | ...`);
  `test_table_csv`; `test_compare_ratio` (`B/A` of 10 and 12 is `1.2`);
  `test_script_replays` (`replay.sh` exits 0 and rewrites `summary.json`).
- [ ] **Step 2:** Run, expect failures.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Tests pass; lint clean.
- [ ] **Step 5:** Commit; push.

### Task 7: Samples and acceptance

**Files:**
- Create: `samples/wyrd.toml`, `samples/designs/single/bm_DL_2_4_encoder.v` (from Odin III
  `tests/micro/verilog/micro/`), `samples/designs/multi/src/{arith/adder.v,ctrl/pick.v,top.v}`
  (from Odin III `tests/golden/projects/multi_dir`), `samples/designs/dsp/{top.v,mac.v,buf_ram.v}`
  (new), `samples/make-expected` (script), `samples/expected/<arch>.json`,
  `tests/test_samples.py`, `NOTICE` (where the copied files come from; Odin III is MIT)

**Interfaces:**
- Consumes: the `wyrd` command (Task 6).
- `dsp` design: `top` instantiates `mac` (8×8 signed multiply, 20-bit accumulator, synchronous
  reset, enable) and `buf_ram` (single-port RAM, 32 words × 16 bits, registered read), with
  registered outputs. It must map at least one multiplier and one memory hard block on both k6
  and EArch (checked by `make-expected`).
- `make-expected`: runs `odin3-flow` directly (same argv as the `odin3-flow` step) for each
  sample and arch, writes `expected/<arch>.json` as `{design: {metric: value}}` using the same
  flattening as Task 4, plus `"odin3_version"`; it fails if `dsp` has no `hard_blocks.multiply`
  or no memory block.
- `test_samples.py::samples_match`: skips (with the reason) unless `odin3-flow` and `VTR_ROOT`
  exist; runs `wyrd run --project samples` into a temp copy; for each design × arch compares
  `wyrd table` values with `expected/`, ignoring `seconds.*`; also checks `odin3 --version`
  matches `odin3_version` and skips with a message if not.

- [ ] **Step 1:** Write the samples and `make-expected`; run it on k6 and EArch; commit the
  expected files.
- [ ] **Step 2:** Write `samples_match`; run it: PASS (quote the summary line in the PR).
- [ ] **Step 3:** README: install (`pip install -e .`), `wyrd config init`, run the samples.
- [ ] **Step 4:** Lint clean; commit; push.
