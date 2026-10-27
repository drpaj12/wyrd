# Placement atlas: viewing the Norns round-7 corpus

Purpose: Wyrd W Q3.1 (what a person needs to see at each step), serving Norns N Q2.4 (which HDL
relations predict which atoms sit together) and N Q1.7 (stock versus hindsight clustering).
Measure: a person can open any round-7 run and see, on the device grid, which CLBs hold which HDL
words, constructs, instances and N17 classes and how criticality falls, and can compare stock with
a hindsight arm; load and draw time and peak memory on the largest design are measured.

## Data source

Norns round 7: placements from VPR runs (VTR; Rose et al., "The VTR project", FPGA 2012, and
Elgammal et al., "VTR 9", ACM TRETS 18(3), 2025, DOI 10.1145/3734798; VTR commit 3c9a4d23b2,
9.0.0-dev). Format, from the "Atlas export" section of the Norns round-7 plan: one JSON per run,
`runs/r7/<design>/atlas/<arm>.s<seed>.json.gz`, with `design`, `arm`, `seed`, `grid`, `cpd_ns`,
`wirelength`, `chan_width`, `clbs` (id, type, x, y, atoms) and `atoms` (name, kind, class,
construct, inst, word, bit, crit, pcrit). `crit` is the pack-time criticality (stock arm only,
else null); `pcrit` the path-based post-route criticality, an under-approximation (atoms on none
of the 200 reported paths get 0). Samples are under `tests/data/atlas/` (MIT, with provenance).

## Model (`wyrd/atlas.py`, standard library)

- `load_atlas` reads `.json` or `.json.gz` and validates: grid is two positive integers, CLB types
  are clb/io/mem/mult, atom indices are in range, CLB ids and coordinates are unique and inside the
  grid, no atom is in two CLBs. Any failure is an `AtlasError` naming the file. Atoms held by no
  CLB are allowed (the round-7 files have one).
- `find_runs` lists design, arm and seed from the file names, under a runs root or in a flat folder
  of `<design>.<arm>.s<seed>.json.gz`. Arms sort stock, other, then h1, h2, ... numerically.
- Summaries: CLB counts by type, atoms per CLB (min/mean/max), per-construct and per-word CLB
  spread, class shares.
- Colour keys: categorical (`construct`, `word`, `inst`, `class`): a CLB takes its most common
  value (ties alphabetical), colours are by rank of the value's CLB spread; numeric (`crit`,
  `pcrit`): the maximum over the CLB's atoms on a light-yellow to dark-red ramp. Grey = no label.
- Difference: atoms are matched by name; one counts as moved when the (x, y) of its CLB differs
  between the two runs (CLB ids are not comparable across runs). B's CLBs are shaded by the share
  of their atoms that moved.

## Panel (`wyrd/gui/atlaspanel.py`)

QGraphicsView, no new dependency. y = 0 is the bottom row. Loading runs on a worker thread (the
schematic panel's pattern) with a token for stale results and a small cache of loaded atlases.
Views: A only, A | B side by side, Difference. Value list: click to outline that value's CLBs and
fade the others (categorical keys). Hover text: CLB type, id, position, and for each atom (first 12)
name, kind, class, word and bit, construct, instance, crit, pcrit. Selecting a different arm toggles
stock against hindsight for the same design and seed (B falls back to its first seed when it has
none for A's seed; hindsight rounds are run from a chosen source seed).

## Measured (2026-10-26, WSL2, PySide6 6.12.0, offscreen, `tools/atlas_bench.py`)

| File | CLBs | Atoms | Load + validate | Draw (6 keys, ms) | Peak RSS |
|---|---|---|---|---|---|
| or1200 stock s4 | 252 | 3585 | 11 ms | 4 to 11 | 68 MB |
| raygentop stock s1 | 143 | 2439 | 8 ms | 2 to 9 | 66 MB |
| n5_mesh_dp_256 stock s8 (largest file in runs/r7) | 294 | 5120 | 15 ms | 4 to 11 | 69 MB |

Draw = rebuild the scene and force a full paint (first key, which builds the colour order, is the
slowest). Peak RSS is the whole process including Qt (about 65 MB baseline). All files are far
below one frame at 60 Hz; the grid is at most about 30 x 30 so scale is not a limit.

## Limits

- `crit` is null in hindsight arms; the key greys those CLBs.
- Only logic-CLB atlases exist so far (io/mem/mult types are drawn but not yet seen in data).
- No VPR or network is used; the panel only reads files.
