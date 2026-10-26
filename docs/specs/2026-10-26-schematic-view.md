# Schematic view (netlistsvg): feasibility and measured limits

Purpose: Wyrd W Q3.1 and W Q3.2 (what a person needs to see at each step). Measure: does the view
render the micros, and how large a design does it scale to. Measured 2026-10-26 with netlistsvg
1.0.2 (MIT, N. Turley), Node v22, Odin III main build 2d521f09 (ABI 7), on WSL2.

## Feasibility

`odin3 -p "read_verilog F.v; proc; write_json OUT.json"` feeds netlistsvg directly, with or without
`--odin3`. Two points: `proc` must run first (Odin III refuses `write_json` on a module with
processes); and the module marked `top` is the one drawn, so Wyrd rewrites the JSON to draw another
module or a cone (`wyrd/schematic.py`). No converter is needed.

Micros (`tests/micro/verilog/micro`, 68 designs): 65 render (0.35 to 0.40 s each, SVG 2 to 51 KB);
3 fail in Odin III before `write_json` (adder_hard_block, hard_adder_cin_propagation,
multiply_hard_block: hard-block modules unresolved without the VTR technology library).

## View selection

- A module, whole, up to `max cells` (default 300).
- A fan-in cone of a net, or of an HDL line (cells whose `src` attribute covers `file:line`), cut at
  `max cells`; bits made outside the cone become input ports.

## Scale (one netlistsvg run, single module)

| Cells | Wall time | SVG size | Source |
|---|---|---|---|
| 3 | 0.3 s | 14 KB | mac1 cla_csa70 |
| 78 | 0.8 s | 212 KB | mac1 add_csa70 |
| 164 | 2 s | 284 KB | iir (top) |
| 1011 | 4.8 s | 1.9 MB | mac1 mult_ |

Time grows roughly linearly here; 1011 cells draws but is not readable at screen size, so the
default limit is 300. Failure seen: bgm `b_right_shifter` (149 cells, 48-bit buses) makes
netlistsvg die with "RangeError: Maximum call stack size exceeded" in FlatModule.gather (its
bus split/join recursion), even with a larger Node stack; Wyrd shows that message. Large flattened
designs (single_port_ram and dual_port_ram designs) were not drawn: Odin III needs the VTR library
for them.

## Credit

netlistsvg: MIT, not bundled; `wyrd/data/citations.toml`, `docs/CITATIONS.md`, `NOTICE`, README,
`docs/paper/joined.bib` (key turley2020netlistsvg, `% Checked:` line).
