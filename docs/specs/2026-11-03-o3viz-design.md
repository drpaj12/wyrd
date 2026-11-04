# o3viz: 3D provenance viewer for one Mimir benchmark (design, 2026-11-03)

Status: approved by Peter in conversation 2026-11-03. Part of Wyrd III (the visualization tool).

Purpose: let a person see one benchmark as a stack of planes, one per stage of the flow (HDL, graph
transformations, LUTs, clusters, placed sites), colour or size any measured parameter on any plane, switch the
layout rule (anchor), and click an object to see its column down to the placed site and up to the HDL line.
Measure of success: Peter opens one benchmark in a browser, rotates the stack, switches anchors, maps any
metric to colour, size or height, and clicks a node for its provenance column.

Peter's request, in his words: "how can I see a benchmark in some form and different parameters as measured with the
circuit? We have a graph, the graph transformations going towards the FPGA, then the physical location on the FPGA
with statistics ... I imagine a 3D model that I could rotate to see the transformation where each graph is a plane
..., at each plane being able to see different parameter as a heatmap - then planes going to a placement and
routing." Anchoring: "I do really like the anchor from the bottom going to the top, but also like the idea of AST
anchoring (tree like) to netlist anchoring via flip-flop like pipeline stages to placement, ... even logic levels
could be interesting". Joins: "I want ways of joining parameters in this visualization".

## 1. Bundle, one per benchmark (`<bench>.o3viz/`)

- `manifest.json`: benchmark, flow (`vtr` or `silicon`), tool versions, input sha256, planes in order, metric
  catalogue (name, unit, planes, source, measurer, scale), anchors available. Deterministic: sorted keys, `\n`, UTF-8.
- `planes/<stage>.json`: one row set per plane: `ids`, `kind`, `type`, `origin`, `name`, and one column per metric
  (`null` = not measured). Columns are index-aligned with `ids`.
- `links.json`: `[from_id, to_id, kind, confidence]`; `from` is on the plane nearer the HDL, `to` nearer the chip.
- `edges/<stage>.json`: netlist edges inside a plane `[driver, sink, kind]`.
- `anchors/<anchor>.json`: per plane `{id: [x, y]}` plus `bounds`; computed in Python, deterministic.
- `hdl/`: the source files; the span of an object (`file`, `line.col-line.col`) indexes into them.
- Planes follow the stages of the Odin III step files (`docs/user/provenance-files.md`). A plane is shown if present.
- Metrics are joined by id from their measurer. Never invent a value: absent = null.
- Anchors: `placement` (bottom plane is the real grid; upper planes are the centroid of their descendants through the
  links), `ast` (tidy tree of the HDL AST; lower planes the centroid of ancestors), `pipeline` (x = register stage cut
  at flip-flops), `level` (x = logic depth).
- Sets later: `<set>.o3vizset/index.json`, one row per benchmark. Not built in M1 to M3.

Format note (M1 decision): JSON, not Apache Arrow IPC. Wyrd's runtime core is standard library only and there is no
Arrow writer without `pyarrow`; the brief allows the JSON fallback for small designs. The loader in the viewer is one
function (`loadBundle`), so an Arrow reader can replace it when a large benchmark needs it (M3 decides, with numbers).

## 2. Viewer (static page, three.js, offline)

Vendored `three` and its `OrbitControls` at a pinned version with the licence file; no CDN, no network at view time.
3D stack with planes spaced on z, orbit controls, auto-rotate, per-plane toggle and opacity; channels per plane (colour,
size, height, opacity, shape); sequential and diverging scales; legend from the catalogue; expression editor (own safe
parser, no `eval`); cross-plane aggregation along links; discovery panel (Spearman and mutual information);
click = provenance core sample; lasso brush; k-hop edges on demand; grouping; 2D view; morph slider (M2, M3).

## 3. Exporter (`wyrd viz export`) and server (`wyrd viz serve`)

Inputs: an `odin3-flow --prov` run directory (after `odin3-prov-post` and `odin3-prov-steps`), the VPR files kept with
`--keep-results` (`.net`, `.place`, timing report), optionally a Mimir store. It never edits Odin III or Mimir.
`wyrd viz serve BUNDLE` starts a local `http.server` on 127.0.0.1 and prints the URL.

## 4. Testing

Exporter unit tests on a fixture run, bundle schema check, determinism (two exports byte-identical), anchor sanity
(bottom plane equals VPR coordinates; every linked object has a position), viewer headless smoke (Playwright/Chromium
when installed; otherwise skipped and documented as manual).
