# Mimir browser: browsing the Mimir dataset in Wyrd III

Purpose: Wyrd W Q3.3 (proposed for hub docs/purpose.md under Wyrd III): what does a person need to
see to browse the Mimir dataset and compare designs, flows and experiment arms, with how each value
was obtained? Measures: the area and speed metrics already in the store (LUTs, CLBs, wire length,
CPD, structural and Rent metrics), each shown with its run provenance. No new metric.

Wyrd is the suite's visualization tool; Mimir (github.com/drpaj12/mimirIII) is the dataset: data,
metrics, and how each value was obtained. Runs in the store used VTR (Rose et al., "The VTR
project", FPGA 2012; Elgammal et al., "VTR 9", ACM TRETS 18(3), 2025, DOI 10.1145/3734798; commit
3c9a4d23b2).

## Data access (`wyrd/mimirview.py`, standard library only)

- Opens the SQLite store read only: `sqlite3.connect("file:<path>?mode=ro", uri=True)`. Never
  writes, never creates an index, never imports the `mimir` package for data. A fresh connection
  per query, so a worker thread can use the model and a writer in another process (e10.db) is fine.
- Version check: `meta.schema_version`. Version 4 (mimir `SCHEMA_VERSION`, mimir main
  b8b4118) is supported. Any other version, a missing `meta` table, a file that is not SQLite:
  `MimirError` with a clear message ("schema version 3; this Wyrd reads version 4").
- Tables read (mimir `mimir/schema.py`): `records` (one row per measured value: design, source,
  level, arch, seed, arm, family, metric, bin, value, unit, measurer, origin, tool_commit),
  `design`, `design_source`, `design_meta`, `design_lineage`, `run`, `flow_config`, `flow_param`
  (conf: given, default, default-unrecorded, unknown), `run_artifact` (kind, blob sha; the store
  holds no size, so none is shown), `structure` (counts by kind).
- Metric registry: not in the store. Used only if `mimir.registry` is importable (looked up with
  importlib, optional); otherwise metric names and the units stored in the records.
- Limits: every list query takes `limit` and `offset` (default 500 rows; "more" flag when cut).
  Queries use the existing indexes: records primary key (leads with design), `records_source_origin`
  (a source prefix is a range, not LIKE, so the index is used), `run_key`.

## Queries (all return plain dataclasses or row tuples)

1. `summary()`: schema version, file size, row counts of every table, sources with record and run
   counts, designs, levels, metrics (count of distinct, top by rows).
2. `designs(source, text, limit, offset)`: rows (source, name, slug, suite, n_runs) from
   `design_source` joined to `design`; designs seen only in `run` are added. Text filter matches
   name or slug (case-insensitive substring).
3. `design(name, source)`: metric records (level, metric, value, unit, measurer, origin, arch,
   arm, seed, bin; limited), runs (run_id, source, arch, arm, seed, family, tool commits, time_s,
   peak RSS, host as stored), `design_meta` (field, value, source, conf), `design_lineage`,
   structure counts by kind. A name found in several sources lists them all unless `source` is given.
4. `run(run_id)`: the run row, its `flow_config` (name, status, text kind), `flow_param` rows
   (step, key, value, conf, source), artifacts (kind, sha256).
5. `compare(prefix, base, metric, level)`: configuration label = `source/arm` (just `source` when
   the arm is empty). Per (label, design) the mean of the metric over seeds and archs; per label
   the geometric mean of value / base value over designs present in both with both values > 0,
   with n shown. Sources are chosen by prefix (range query).
6. `scatter(x_metric, y_metric, source)`: per (source, design) the mean of each metric; points
   where both exist (limit 20000).
7. `fetch_argv(run_id, db, out)`: the argument list for `mimir fetch --run RUN_ID --db DB --out
   DIR`; `mimir_on_path()`. The GUI runs it with `subprocess`, no shell.

## CLI (`wyrd mimir`, in `wyrd/cli.py`)

    wyrd mimir summary DB
    wyrd mimir designs DB [--source S] [--filter T] [--limit N] [--csv]
    wyrd mimir design DB NAME [--source S] [--limit N] [--csv]
    wyrd mimir run DB RUN_ID [--csv]
    wyrd mimir compare DB --prefix P --base CFG --metric M [--level L] [--csv]

Plain text tables; `--csv` writes the main table as CSV. Exit 0 ok, 2 for a usage error, an
unreadable store or an unsupported version, as the other commands.

## GUI dock (`wyrd/gui/mimirpanel.py`)

Bottom dock "Mimir" next to Atlas; File > Open Mimir store... (the last path is remembered in the
window settings and offered again). Left: design list, filter box, source combo. Right tabs:

- Summary: counts, sources.
- Design: metrics table (level, metric, value, unit, measurer, origin), runs table, provenance
  (meta with conf, lineage, structure counts). Double click a run row opens the Run tab.
- Run: flow parameters coloured by conf (given green, default grey, default-unrecorded amber,
  unknown red), artifacts, and a "Fetch artifacts" button (runs `mimir fetch`, disabled with a
  tooltip when `mimir` is not on PATH).
- Compare: prefix, base config, metric, level; table of label, n, geomean ratio; a dot chart with
  a line at ratio 1 (QPainter, same style as the atlas, no new dependency).
- Plot: scatter of two metrics across designs, optional log axes, hover text names the design.

Every table has Copy (tab separated, to the clipboard) and Export CSV. Queries for the Summary and
Compare tabs run on a worker thread (stale results dropped); the others are indexed and run inline.

## Out of scope

Writing or editing a store; building indexes; the `mimir` package as a data dependency; fetching
without the `mimir` command; schema versions other than 4; new metrics; the Leman Russ checks;
fetching blobs by URL (that is `mimir fetch`).

## Tests

- Fixture: `tests/data/mimir/schema_v4.sql`, a dump of the mimir v4 DDL (header cites mimir
  b8b4118, `mimir/schema.py` and `mimir/store.py`), plus a test helper that builds a tiny synthetic
  store from it in a temp dir. No real Mimir data is committed (real stores hold host and path
  fields).
- `tests/test_mimirview.py`: every query; unsupported version; not a store; read-only (the store's
  bytes and mtime unchanged after a session; a write through the model's connection fails).
- `tests/test_cli_mimir.py`: every subcommand, `--csv`, exit codes.
- `tests/test_gui_mimir.py` (offscreen): open, filter, design, run, compare, plot, export CSV.
- Manual, read only, on mimir-main.db, structures.db, e10.db: timings and a screenshot per tab.

## As built (2026-10-28)

- Model `wyrd/mimirview.py`, CLI `wyrd/mimircli.py` (wired in `wyrd/cli.py`), dock
  `wyrd/gui/mimirpanel.py` with charts in `wyrd/gui/mimircharts.py`. Table rendering (text, CSV,
  TSV) is shared by CLI and GUI in `mimirview.py`.
- The design list is keyed by (source, name); selecting a row shows that source only; the CLI
  `design NAME` without `--source` shows all sources.
- Metric tables stop at 500 rows (the note says so); a design with 50 runs has more.
- Worker thread: opening (summary, metric and source lists), configs, compare, plot. Design list,
  design and run views are inline (indexed queries).
- `cited` in the brief is not a `conf` value in schema v4; the colours are given, default,
  default-unrecorded, unknown. `run_artifact` holds no size.
- Fetch hook: button runs `mimir fetch --run ID --db DB --out DIR` through `subprocess` (no
  shell) after a directory dialog; disabled with a tooltip when `mimir` is not on PATH.

## Fix round (2026-10-28, PR review of f20ced6a)

- `compare`: dedup, two-stage mean (seeds per arch, then archs, per design), per-level rows, per
  config `dropped`, duplicates merged, distinct tool_commit and config_hash counts with a MIXED
  flag; `run.time_s` / `run.peak_rss_mib` as metrics (runs-only stores). `scatter` averages each
  (source, design) over the arms that have both metrics and returns the 20000 cap in a note.
- Truncation: CSV from the CLI ends with `# truncated at N rows` and warns on stderr; GUI Export
  CSV re-queries without the cap; the Design tab has a level filter for the metrics table.
- GUI: all store queries (list, design, run, compare, plot, open) run on the worker pool; opening
  a store drops in-flight results and clears the previous store's views, and the previous store
  stays until the new one is read; `mimir fetch` runs in a QProcess with output and Cancel;
  metric tooltips come from the Mimir registry (when importable) and the `run.*` descriptions.
- The store is opened with `Path.resolve().as_uri() + "?mode=ro"`; a `-wal` file beside the store
  is mentioned in the status line (a read-only session creates no file).
- The design filter is a literal, ASCII case-insensitive substring (LIKE wildcards escaped).
