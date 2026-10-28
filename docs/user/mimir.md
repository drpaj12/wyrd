# Browsing a Mímir store (`wyrd mimir`)

Mímir III is the circuit dataset of the Yggdrasil III suite: measured values (area, speed, structure)
with how each was obtained. `wyrd mimir` reads a store (a SQLite file, schema version 4) read only:
it never writes the file or adds an index, and it works while another process is writing the store.
A store of another schema version is refused with a message naming both versions.

    wyrd mimir summary DB
    wyrd mimir designs DB [--source S] [--filter TEXT] [--limit N] [--csv]
    wyrd mimir design DB NAME [--source S] [--level L] [--limit N] [--csv]
    wyrd mimir run DB RUN_ID [--csv]
    wyrd mimir compare DB --prefix P --base CONFIG --metric M [--level L] [--csv]

- `summary`: row counts, sources (records and runs each), levels, number of distinct metrics.
- `designs`: source, name, slug, suite and run count; `--limit` defaults to 500 (0 means no cap) and
  a last line says when rows were cut off. With `--csv` a cut table gets a final line
  `# truncated at N rows` and a warning on stderr; use `--limit 0` for every row.
- `design`: metric records (level, metric, value, unit, measurer, origin, arch, arm, seed), the
  design's runs (arch, arm, seed, family, tool commits, time, peak RSS, host as stored), its
  meta fields and lineage with their `conf`, and structure counts. A name that exists in several
  sources lists them all unless `--source` is given. `--level` keeps one level of the metric records.
  `--csv` writes the metric table.
- `run`: the run row, its flow configuration, every flow parameter with `conf` (`given`,
  `default`, `default-unrecorded`, `unknown`) and source, and the artifact hashes (the store holds
  no size). `--csv` writes the parameters. `mimir fetch --run RUN_ID --db DB --out DIR` (the Mímir
  command) fetches the artifacts.
- `compare`: a configuration is `source/arm` (`source` when the arm is empty). The sources are
  those that start with `--prefix`. Repeated records (same source, arm, design, arch, seed, level,
  metric) are merged first and counted. Then the metric is averaged over seeds per architecture,
  then over architectures, per design. Each row is the geometric mean of value / base value over the
  designs both have (both values above 0), per level; without `--level` every level gets its own
  rows. Columns: `n designs`; `dropped` (non-numeric rows plus shared designs with a value <= 0);
  duplicate rows merged; distinct `tool_commit` values among the rows; distinct run `config_hash`
  values for the configuration; and `MIXED` when either is above 1 (the row mixes tool versions or
  flow configurations, so read it with care). `--base` must be a configuration under the prefix.
  The metrics `run.time_s` and `run.peak_rss_mib` read the run table, so a store with runs but no
  metric records can still be compared (and `summary` says "this store has runs but no metric
  records"). Example: `--prefix norns-r7 --base norns-r7/net0 --metric vpr.cpd`.

Exit codes: 0 ok; 2 for a usage error, an unreadable store, an unsupported schema version or an
unknown design, run or base configuration.

The Mímir dock in `wyrd-gui` shows the same data; see the GUI page.
