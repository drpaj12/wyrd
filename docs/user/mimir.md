# Browsing a Mímir store (`wyrd mimir`)

Mímir III is the circuit dataset of the Yggdrasil III suite: measured values (area, speed, structure)
with how each was obtained. `wyrd mimir` reads a store (a SQLite file, schema versions 4 and 5) read only:
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

<!-- guide:begin -->
## Mímir guide: from a store to a coloured source file

Mímir is a database of measured values of circuits: how big they are, how fast, how their HDL
turned into logic. Wyrd shows it read only: it never changes the file.

### 1. Open a store

File > Open Mímir store... and choose a `.db` file. The Summary tab says what is in it: records
(measured values), runs (executions of the flow) and sources (experiments).

### 2. Pick a design

Choose a source and type in the filter box, then click a circuit. The Design tab fills in. Double
click a run in its Runs table to see exactly how the run was made (Run tab).

The same circuit can be listed once per source. Only the entries that carry timing end in the word
"timing" (for example `mkPktMerge [mimir-structures]`). The line above the list says "Current
design" and always names the highlighted entry. Typing in the filter box or changing the source
never changes the current design; only your click (or the arrow keys on the list) does. When you
pick an entry without timing, the Timing and Structures tabs use the timing of the same circuit
from another source and say so. "Reopen last" opens the last store with the last design selected.

### 3. The Timing tab

Pick a run. The summary line gives the clock period (CPD), the worst slack and how many of the
reported paths were used. Criticality (crit) is how close a path is to being the slowest one: 1.0
is the slowest, 0 has plenty of spare time. It is 1 - slack / (the largest required time of the
clock pair of the path); when the worst slack is negative, all slacks are shifted so that the
worst is 0. A path is near-critical when its crit is at least
theta (0.90, 0.95 or 0.99). The histogram shows how many paths fall in each crit range; the
table lists the most critical HDL objects, with a bit strip for buses.

Exact or lower bound: when the summary says "crit is exact", the clock period was found from all
paths. When it says "crit is a lower bound (dmax from report)", it came from a cut report and the
true crit can only be higher.

### 4. See the HDL heat: Show HDL heat (hot/cold)

Press "Show HDL heat (hot/cold)", the button beside the Current design line (it is always there;
the "Open in source view" button of the Timing tab does the same). It is grey when the current
design has no timing; hover over it to see why. Wyrd finds the design's source from the store
(the design's origin, for example `$VTR_ROOT/vtr_flow/benchmarks/verilog/mkPktMerge.v`;
`$VTR_ROOT` comes from your environment or the machine settings), opens it read only, switches the
Timing panel to near-critical, and selects the hottest token. When the file cannot be found the
status line says exactly what is missing and a file dialog lets you pick it.

### 5. What red and blue mean

Red is critical (crit near 1), blue is not critical, light yellow is in between. A faint tint
on a whole line says the line is on a near-critical path. For a bus such as `D_OUT[141:0]` the
name is split into one coloured piece per bit, most significant bit first: a name of 6 letters
for 3 bits gives 2 letters per bit. When the name is shorter than the number of bits, a bit
strip under the name shows each bit and the name keeps the highest crit. A dotted underline
marks a bit whose index is unknown; such a bit is grey. Hover a token to see its crit and every
bit.

The token columns are always found by matching the name of the word on the line (the store
links a word to a line, not to a column). The Timing panel setting "MSB first" chooses whether
the bits run from the most or the least significant bit.

### 6. Example: mkPktMerge

Open `lane3-structures.db`, click `mkPktMerge` (either entry; the one marked "timing" owns the
data), choose a run in the Timing tab if you want another one, and press Show HDL heat. The word
`fi1__D_OUT` is a bus of at least 142 bits. Bits 134 and 141 have crit 1.0 and bit 132 has 0.995:
those bits set the speed of the chip, while many others sit near 0.93. Click the token to list the
paths through it in the Timing panel.

### 7. Structures tab

A structure is a piece of HDL that looks like a known building block (an adder, a multiplexer).
Each row says how many LUTs and CLBs it became, where it was placed (bbox), its spread (how far
apart its parts are) and crit_share (how much of the critical path it accounts for).
<!-- guide:end -->
