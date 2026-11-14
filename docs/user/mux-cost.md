# mux-cost: what the muxes of a design cost, line by line

`wyrd mux-cost` tells a designer what each multiplexer in a design costs and which HDL line made it:
"this `case` costs 12 mux bits, its arms are these, its select decode shares four LUTs with it". It reports;
it does not change the design and it adds no language feature. It is a command line tool that a person or an AI
agent can call: one command, a plain table by default and stable JSON with `--json`.

Purpose: Wyrd III purpose W2 (show the provenance answers to a person), answering Odin III question O Q2.3
(which constructs drive area) with mux bits and LUTs, and W Q2.1 (which lines set the speed) with the optional
select lateness. The hub's [purpose page](https://drpaj12.github.io/YggdrasilIII/purpose.html) lists both.

It works because Odin III ties every word-level cell, and every LUT it maps to, back to the HDL span that made it
([provenance](https://drpaj12.github.io/odin3/provenance.html)). Wyrd runs Odin III as a program and reads the
files it writes; it never changes the Odin III core.

## Run it

```bash
wyrd mux-cost design.v other.v --top top --out OUT_DIR           # plain table
wyrd mux-cost design.v --top top --out OUT_DIR --json            # the same as JSON (schema 1)
wyrd mux-cost --project DIR --run KEY                             # a design and run of a Wyrd project
wyrd mux-cost --from OUT_DIR --sort luts --limit 5                # re-read a finished run, no Odin III
```

| Option | Meaning |
|---|---|
| `FILES`, `--top TOP` | the design; the top defaults to the one uninstantiated module (as `odin3-flow`) |
| `--project DIR --run KEY` | the design of a run of a Wyrd project (key prefix of 6 or more characters, as `wyrd timing`); the output goes to `<run dir>/mux-cost` |
| `--from DIR` | read the `words/` files an earlier call wrote to `--out DIR`; Odin III does not run |
| `--out DIR` | output directory (default `mux-cost-out`) |
| `--json` | print the report as JSON instead of the table |
| `--sort bits\|luts\|crit` | row order: mux bits (default), LUTs, or select lateness (`crit` needs `--net-timing`) |
| `--limit N` | the first N rows of each table |
| `--net-timing FILE` | a VPR `report_net_timing.csv` of a routed run of this report's BLIF (see below) |
| `--odin3 PATH`, `--odin3-flow PATH` | the programs; default the `odin3` and `odin3_flow` of the machine settings |
| `--timeout S` | seconds each Odin III run may take (default 3600) |

Exit codes: 0 ok, 1 Odin III or the analysis failed, 2 usage or settings error.

Needs Odin III 1.6.1 or later (the name map with `uid=` flags, `abc --prov-cut on`). `odin3-flow --prov --prov-cut
--no-vpr` runs first, because it is the one definition of the Odin III script. The same `odin3` command, which the flow
logs on the first line of `odin3/odin3.log`, then runs again with one more pass, `write_json --odin3 --name-style hash
--prov-map` before `lower`, and `ODIN3_PROV_UID=1`, so the word-level muxes and the mapped BLIF come from one run with
one set of record ids. The files are kept in `OUT_DIR/flow/` and `OUT_DIR/words/` (`snapshot.json`, `<top>.blif` and
their `.names` maps). Run large designs through your usual memory limit (for example `systemd-run` or the heavy-run
wrapper of your machine): `wyrd mux-cost` runs Odin III as one plain process.

## What is counted

The mux cells are the ones Odin III has before `lower`: `$mux`, `$pmux` and `$shiftx` (its registry has no `$bmux` or
`$demux`). One row is one **logical mux**: a chain of `$mux` and `$pmux` cells that one construct made, such as an
`if` / `else if` chain, is joined when each cell's whole output feeds one data port of the next, with equal width and
no other reader. Constants that Odin III folded before the snapshot are not muxes any more; the report shows what
reached `lower`.

| Column | Meaning |
|---|---|
| `where`, `construct` | the HDL span and its kind: `case`, `if`, `?:`, `index` (a variable bit select, a `$shiftx`), or `other` (the span of the cell). The construct is the outermost one above the cell in the provenance chain |
| `kind`, `width`, `cells` | the cell type of the root cell; the output width in bits; the number of cells in the logical mux |
| `arms` | leaf arms: the data inputs no cell of the logical mux drives. A `$pmux` has its select count plus the default; a `$shiftx` has one arm per offset the select can reach |
| `const`, `dup`, `rel` | arms that are constants; arms identical to another arm (the count of extras); arms that differ from another arm in constant bits only (the same signals in the same positions, not identical, not constants) |
| `sel` | the distinct non-constant select bits of the logical mux (for a `$pmux`, the decoded one-hot lines) |
| `mux_bits` | 2:1 equivalents: width x (arms - 1), summed over the cells; `share` is its part of all mux bits of the design |
| `luts`, `shared` | LUTs the provenance map attributes to the mux (below), and how many of them also cover some other word cell (a select decode, a compare, a neighbouring mux) |
| `lut_lb` | the textbook lower bound of LUTs for a K-input fabric (below) |
| `sel_crit`, `data_crit`, `late` | only with a routed timing report (below) |

The second table rolls the rows up per HDL construct (the same span): the sum of mux bits and arms, the union of
the LUTs, and the worst `late`.

### LUTs attributed to a mux

A LUT made with `abc --prov-cut on` has an exact cut when Odin III can prove which old gates its function covers
(`cut=exact`); the record then lists the word cells the LUT covers. The report counts a LUT for a mux when its exact cut
contains that mux cell. A LUT with an approximate cut (ABC rebuilt its function) or no cut is not attributed to any
cell; the header line counts them, so a design with many approximate LUTs shows `luts 0` for rows that do cost LUTs.
Two limits of the name map apply (see the Odin III provenance page): a LUT that drives a net that keeps its name, such
as an output port, shows that net's older record and is not found; register the outputs of a small sample, as
`tests/data/muxcost/src/` does. A LUT that covers two cells is counted in both rows and listed as shared.

### The lower bound

A cone of L LUTs of at most K inputs has at most L(K - 1) + 1 distinct leaf signals: each of the L LUTs has at
most K input edges, and at least L - 1 of the edges join two LUTs of the cone. A function that depends on n
signals therefore needs L >= (n - 1) / (K - 1), rounded up. The report applies it to each output bit of the logical mux
with n = the distinct non-constant data bits of that bit position plus the distinct select bits, and sums over the bits
(0 when n < 2). It is a counting argument, derived here; no paper is cited for it. It ignores everything the mux's
neighbours let ABC share, so the attributed LUTs can be fewer than the bound when a LUT also carries logic of the
select decode; compare it with `luts` and `shared`, not as a target.

## Select lateness (optional, needs a routed run)

Without a routed timing report the three timing columns are absent from the table and the JSON, not zero. To get
them, route the BLIF this report wrote (`OUT_DIR/words/<top>.blif`, hash names) with VPR and
`--generate_net_timing_report on`, then pass the `report_net_timing.csv`:

```bash
wyrd mux-cost --from OUT_DIR --net-timing report_net_timing.csv --sort crit
```

With `--project DIR --run KEY`, a `report_net_timing.csv` found in the run directory is used when its pins join the
BLIF (a flow run with short net names does not join; the report then says so in `notes` and goes on).

A pin's criticality is `(s_max - slack) / (s_max - s_min)` over the finite pin slacks of the report: 1 is the worst
pin of the design, 0 the most relaxed. A mux takes the worst criticality over its **select pins** and over its **data
pins** (greedy worst over pins), and `late` is their difference: positive when the select is later than the data, which
is when the mux costs speed beyond its data path. A LUT pin is a select pin when its net is in the fan-in cone of the
mux's select bits (up to the first net that exists in the mapped netlist) and is not itself an arm of the mux; every
other input pin of the mux's LUTs is a data pin. `witness` is one of the tied worst select pins, picked at random with
a fixed seed (20261114), so the same inputs give the same witness. A mux whose select logic Odin III absorbed into a
LUT with no separate select pin, or with no data pin, shows `-` (JSON `null`).

## JSON

`--json` prints one object: `schema` (`wyrd-mux-cost`), `schema_version` (1), `design` (`top`, `lut_k`), `totals`
(`logical_muxes`, `mux_cells`, `mux_bits`, `luts`, `luts_attributed`, `cuts` with `exact`, `approx`, `none`), `sort`,
`timing` (true when a routed report was used), `muxes` (one object per logical mux with the columns above and `id`,
the root cell's hash name) and `constructs`. With a routed report each mux also has `sel_crit`, `data_crit`, `late` and
`witness`, each construct has `late`, and `timing_note` states the criticality formula. The keys of a version do not
change; a new key means a new `schema_version`. `file` is the HDL path as Odin III saw it (relative to the common
directory of the design files).

## Example

`tests/data/muxcost/src/case_tern.v` has a 4-bit `case` over three words and a constant default, and a 4-bit `?:`:

```text
Mux cost of case_tern (K=6): 2 logical muxes, 2 mux cells, 16 mux bits (2:1 equivalents)
LUTs 8; with an exact cut 8, approximate 0, no cut 0; attributed to a word cell 8
Sorted by bits.

Per HDL construct
where           construct  muxes  arms  mux_bits  share  luts  shared  lut_lb
case_tern.v:5   case       1      4     12        75.0%  4     4       4
case_tern.v:14  ?:         1      2     4         25.0%  4     0       4

Per logical mux
where           construct  kind   width  arms  const  dup  rel  sel  mux_bits  share  luts  shared  lut_lb
case_tern.v:5   case       $pmux  4      4     1      0    0    3    12        75.0%  4     4       4
case_tern.v:14  ?:         $mux   4      2     0      0    0    1    4         25.0%  4     0       4
```

The `case` costs 12 of 16 mux bits (4 bits x 3 arms beyond the first). Its four LUTs also cover the select decode
(`$eq` and `$logic_not` cells), hence `shared 4`; the lower bound is one LUT per bit (six signals fit one 6-input LUT).
The numbers are hand-checked in `tests/test_muxcost.py`, which runs on committed Odin III outputs; with
`WYRD_TEST_ODIN3` and `WYRD_TEST_ODIN3_FLOW` set to the programs, the same test runs a real Odin III on the samples.
