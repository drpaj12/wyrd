# Running experiments

## Run

```bash
wyrd run [--project DIR] [--force] [--jobs N] [--mem-budget SIZE] [--progress]
```

`--project` (default `.`) is the directory of `wyrd.toml`. `--force` re-runs runs that already
succeeded. `--jobs` and `--mem-budget` (for example `"24G"` or `"60%"`) override the machine
settings for this run. `--progress` prints a line per finished run while it works.

What happens:

1. **Expand** the sweep into runs.
2. **Preflight.** Every tool of the recipe must resolve, `vtr_root` and the architecture files must
   exist, the disk must have `disk_min_free` free, `systemd-run --user --scope` must work when the
   launcher is `systemd`, and no other `wyrd run` may hold the project lock (`.wyrd.lock`). A
   problem is printed as `wyrd: <problem>` and nothing runs (exit code 2).
3. **Key.** Each run gets a key: a SHA-256 over the resolved commands, the content of every input
   file, the architecture file, the tool versions and the sweep parameters. A run whose key is
   already `ok` in `wyrd.db` is reused.
4. **Schedule.** Runs start smallest input first, as long as their memory estimate fits the free
   part of `mem_budget` and a job slot is free. A step is stopped after `step_timeout` seconds.
5. **Record.** After each step Wyrd stores its command, exit code, wall time, peak memory and
   metrics.

A run line is `<status> <design> <arch> <key prefix>`, for example `ok counteradd EArch 00a3cf1f1415`.
Statuses are `ok`, `fail`, `oom`, `timeout` and `cancelled`. Ctrl-C stops the running steps, marks
them `cancelled` and keeps finished runs.

Exit codes: 0 every run is `ok`; 1 some run is not `ok`; 2 usage, configuration or preflight error.

```{note}
The memory estimate of a step is the highest peak seen for the same design, architecture and step
times `history_factor`. That history includes failed runs: a first run that died early can leave a
very small peak, and the next run is then capped so low that it is killed. If a re-run fails at once
with no message in `stderr.log` after an earlier failure, delete `wyrd.db` (and `runs/`) or set
`launcher = "plain"` in `machine.toml`.
```

## Where things go

```text
myproject/
  wyrd.toml
  wyrd.db                       the index of all runs (SQLite)
  .wyrd.lock                    held while `wyrd run` works
  runs/<design>/<arch>/<key12>/
    0-odin3-flow/               one directory per step, numbered from 0
      cmd.sh                    the exact command (cd, exports, tool call)
      stdout.log, stderr.log
      time.json                 {"wall_s": ..., "peak_mem_bytes": ...}
      out/                      the tool's own output
        summary.json            what the flow measured
        odin3/                  odin3.log and the BLIF netlist
        vpr/                    vpr.log and the VPR run
```

`<key12>` is the first 12 characters of the run key. The `odin3-flow` step writes
`summary.json`; its keys, flattened, are the metrics: `luts`, `clbs`, `hard_blocks.<type>`,
`min_chan_width`, `crit_path_ns` (ns), `wirelength` and `seconds.<step>`. `luts` counts `.names` with two or
more inputs, so adders mapped to hard `adder` (carry chain) cells do not count as LUTs.

`wyrd.db` has three tables: `runs` (key, design, arch, recipe, params, status, started, ended,
run_dir), `steps` (key, n, step, argv, exit_code, wall_s, peak_mem_bytes) and `metrics` (key, step,
name, value, unit). You can query it with any SQLite tool; Wyrd reads it read-only for the commands below.

## Timing attribution

Set `timing_attr = true` on the `odin3-flow` step (needs `target = "vtr"` and `vpr = true`), or
`timing_paths = N` (VPR reports and Odin III attributes N setup paths; implies `timing_attr`):

```toml
steps = [{ use = "odin3-flow", target = "vtr", vpr = true, timing_attr = true, timing_paths = 50 }]
```

The step passes `--timing-attr` and `--timing-paths N`, and records the metrics `timing.fmax_mhz`,
`timing.cpd_ns` and `timing.attributed` (1 when `timing/attribution.json` was usable, else 0), so
`wyrd table` shows them. The file is `<step dir>/out/timing/attribution.json`.

```bash
wyrd timing KEY [--project DIR] [--top N]
```

prints Fmax and CPD, the critical path in order and the top N statements (default 10). KEY is a run
key prefix as for `wyrd script`. Exit code 2 when the run has no attribution or the file cannot be
read. The GUI shows the same in the Timing dock ({doc}`gui`).

## Status, table, compare, script

```bash
wyrd status  [--project DIR]                                  # runs per status
wyrd table   [--project DIR] [--format md|csv] [--metrics a,b]
wyrd compare A_DIR B_DIR     [--format md|csv] [--metrics a,b]
wyrd script  KEY [--project DIR]
```

`wyrd status` prints one line per status, such as `ok 2`.

`wyrd table` prints one row per design and architecture (the most recent run of each), with the
columns `design`, `arch`, `status` and then every metric in alphabetical order. A `recipe` column
appears when the project has more than one recipe, and one column per extra sweep axis.
`--metrics` keeps only the named metrics, in that order; `--format csv` prints CSV instead of a
Markdown table. A project with no `wyrd.db` exits with code 2.

`wyrd compare` takes two project directories and prints one row per matched run and metric with the
columns `A`, `B` and `B/A`; runs present in only one project are listed on stderr as
`only in A: ...` or `only in B: ...`.

`wyrd script KEY` writes `replay.sh` into the run directory and prints its path. KEY is the run key
or a prefix of at least 6 characters; an ambiguous prefix is an error. `replay.sh` runs each
step's `cmd.sh` in order, overwriting that run's outputs, and needs no Wyrd.
