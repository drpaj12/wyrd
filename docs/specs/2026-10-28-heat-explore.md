# Hot/cold HDL view and Mímir exploration views

Date 2026-10-28. Branch `feat/heat-explore`. Part of Wyrd III (the visualization tool of the suite).

## 1. Purpose, questions, measures

Purpose (Peter 2026-10-28): let a user see, in the HDL, which constructs are hot (critical, red) and
which are cold (non-critical, blue), and for a bus word see each bit separately: `RBR` for the word
SIGNAL means bit 2 is critical, bit 1 is not, bit 0 is critical. Also let a user browse the Mímir
structure and near-critical tables in Wyrd.

Research questions (hub `docs/purpose.md`; this spec cites the IDs, it adds none):

- **W Q2.1**: which source lines set the critical path. Part 1 extends the per-line margin to
  per-token and per-bit colour and from one path to the near-critical set. Speed.
- **W Q3.3**: browse and compare Mímir data with how each value was obtained. Part 2. Speed and area
  (crit, near-critical counts against LUTs and CLBs).

Measures: speed = criticality, slack, near-critical counts; area = LUTs and CLBs (Mímir
`structure_mapping`, `record`). Power is not measured.

## 2. Criticality (one definition, the same as Mímir)

Mímir `docs/specs/2026-10-28-near-critical.md` section 2.1 (branch `feat/near-critical`): VPR 9
relaxed criticality (Wainberg and Betz 2015, `calc_relaxed_criticality`), per clock domain pair:

    shift = -worst_slack if worst_slack < 0 else 0
    crit  = 1 - (slack + shift) / (max_req + shift)       clamped to [0, 1]

`worst_slack` and `max_req` are taken over the attributed paths that share the (launch clock,
capture clock) pair read from the `clocked by` text of the start and end point. When
`max_req + shift == 0` every path of the pair gets crit 1; when it is negative the pair is skipped
and counted. Wyrd computes this itself from `attribution.json` (`slack_ns`, `required_ns`) so the
numbers equal Mímir's. The case `worst_slack >= 0` is `1 - slack / max_req`, the "1 - slack / CPD" of
the brief. Approximation: `max_req` is over the paths in the attribution, not over all endpoints
(as Mímir states). The criticality of a construct (line, word, bit) is the **maximum** crit of the
in-scope paths through it.

Near-critical at theta: `crit >= theta`, theta in {0.90, 0.95, 0.99} (Mímir's choice).

## 3. Part 1: hot/cold source view

### 3.1 Inputs and one adapter

The view works on **facts**, a source-neutral list. One fact is one node of one path: file, line
(or none for an I/O pad), module, word, bit, via, delay, and the path: index, slack, crit, endpoint.

- Adapter A (now): `attribution.json` schema 1 (`wyrd/guimodel/heat.py`). Every path node becomes a
  fact; crit comes from section 2.
- Adapter B (Mímir v5 `timing_object`, `wyrd/guimodel/heatmimir.py`): `kind='span'` rows (key
  `file:line`) become line facts; `kind='word'` rows (key `module/word`, `bit`, `via`) become word
  facts, with `crit = crit_max`. These rows have no path list, so only the near-critical scope
  (crit >= theta) is available and "paths through" is empty. Written against the spec on the Mímir
  branch `feat/near-critical`; tested on a synthetic SQLite with that DDL.

Both produce `HeatModel(facts, widths, notes)`; nothing downstream knows the adapter.

### 3.2 Scope

Critical path only (path index of the worst path), top N paths (by report order), or near-critical
(crit >= theta, theta 0.90, 0.95 or 0.99). A fact outside the scope is dropped before any colour is
built. Adapter B supports near-critical only.

### 3.3 Ranges and columns

Provenance spans are line-level (no columns; v1.1.1 limit), so the builder works on the source
text of a file:

1. Every line holding an in-scope fact gets a faint line tint of its max crit.
2. For a fact with a word, the whole-token matches of the word (identifier boundaries, comments and
   strings skipped by the existing tokenizer) on that line get a coloured range. Columns are thus
   **derived by name match**; the legend says so.
3. A fact with a word but no line (an I/O pad has no span) is placed on the declaration line of the
   word: the first line of the file where the word follows `input`, `output`, `inout`, `wire`,
   `reg` or `logic` (with an optional `[hi:lo]` before it). It is limited to the files of its
   module when the module is known from other facts, else any file. A word not found is counted
   as unplaced and listed in the notes.
4. Facts without a word colour the line tint only.

A range is `(line, col_start, col_end, crit, tooltip)` plus its bit segments.

### 3.4 Per-bit split of a bus word

Declared width: from the declaration `[hi:lo]` in the source when it is literal digits, else
`max(bit seen in the attribution) + 1`, else unknown. Bit `b` has crit = max crit of in-scope
facts of that word with `bit == b` (bits are used only when `via` is `name` or `pad`, as in Mímir);
a declared bit with no in-scope fact is **cold** (crit 0, blue). On a use line the bits come from
the facts of that line; on the declaration line they come from all facts of the word.

- Width n >= 2 and the identifier has at least n characters: the identifier is cut into n contiguous
  segments of near-equal length (the first `len mod n` segments get one more character), **MSB
  first** (segment 1 is bit hi). The setting "MSB first" turns this off (LSB first). Example:
  SIGNAL, bits [2]=hot, [1]=cold, [0]=hot gives `SI`=red `GN`=blue `AL`=red.
- n greater than the identifier length: the token takes the max crit, the tooltip lists every bit,
  and a small bar of n cells (MSB first) is drawn under the token.
- No bit information for the word (bit is none, or `json-id`/`declarator` via): the whole token takes
  the max crit and carries a marker (a dotted underline) and a tooltip line "bit unknown".
- n == 1: whole token.

### 3.5 Colour and legend

Scale: ColorBrewer RdYlBu (diverging, listed as colour-blind safe), linear in crit: 0 = blue
`#2c7bb6`, 0.25 `#abd9e9`, 0.5 `#ffffbf`, 0.75 `#fdae61`, 1 = red `#d7191c`. The line tint is the
same colour at low alpha. A legend bar shows the scale with crit ticks (0, 0.5, theta, 1) and the
theta line, and the text "token columns derived by name match; bit order MSB first".

### 3.6 Source view and Timing panel

`SourceView` gets a mode: hot/cold tokens (default), the old share margin, or both. Timing panel
controls: mode, scope (critical path, top N, near-critical), N, theta, MSB-first. A click on a
coloured token lists the paths through it (index, slack, crit, endpoint) in a table of the Timing
panel (adapter A only). Tooltips on hover show crit, paths, word, bits.

## 4. Part 2: exploration over Mímir (dock tabs)

Read-only, worker threads, copy and CSV export as the existing tabs (#34).

1. **Structures** tab: for a design, the `structure_mapping` rows (structure id, kind, level, n_luts,
   n_clbs, bbox, spread, crit_share, joined_with, lost_at_pass) with level and kind filters, and a
   scatter of spread against crit_share (existing `ScatterChart`).
2. **Timing** tab (shown only when the store has the v5 tables, else a note): per run the slack
   (crit) histogram from `timing_path_hist`; a scatter of near-critical path count (`timing_run`
   `n_paths_090` is not stored there: counts come from `records` `timing.nc_paths_*`) against area
   (`n_luts`, `n_clbs` records) across runs; the top near-critical HDL objects of a run (`timing_object`
   by `crit_max`, with the bit strip of word rows); "Open in source view" when the attribution of
   the run is reachable (a run directory of the open project).
3. Store schema version: Wyrd reads 4 and 5 (5 is additive on 4).

## 5. Limits

- Columns are derived by name; two identifiers named alike on one line colour together.
- Declared width needs literal `[hi:lo]`; a parameter width falls back to bits seen.
- Bit rows exist only where the attribution knows the bit (`name`, `pad`).
- The attribution holds N paths (default 100); a truncated set means counts are lower bounds.

## 6. Tests

Headless (no PySide6): crit definition against hand-computed values and the odin3 fixtures, scope
and theta filtering, range building, bit split (n equals, below and above the identifier length,
MSB/LSB, unknown bits, declaration placement, widths), colour map, the Mímir adapter on a
synthetic store. Offscreen GUI tests for the view, the panel and the Mímir tabs. Fixtures: odin3
`tests/tools/data/timing_attr_v1` (MIT, same author; copied with a note) and a synthetic bus case.
