# The samples

`samples/` is a ready-made project: three small designs swept over two architectures. Use it to
check your installation and as a model for your own `wyrd.toml`.

| Design | Files | What it exercises |
|---|---|---|
| `single` | `designs/single/bm_DL_2_4_encoder.v` | one file, no `top` given (a 2-to-4 encoder) |
| `multi` | `designs/multi/src/{arith,ctrl}/*.v`, `top.v`, `top = "top"` | several files in folders |
| `dsp` | `designs/dsp/{buf_ram,mac,top}.v`, `top = "top"` | a multiplier and a memory, which map to hard blocks |

The sweep is `recipe = ["vtr"]`, the three designs and the architectures
`k6_frac_N10_frac_chain_mem32K_40nm` and `EArch`: six runs. The recipe is the usual
`odin3-flow` step with `vpr = true`.

## Run them

You need Odin III (`odin3`, `odin3-flow` on `PATH`) and VTR (`vtr_root` in `machine.toml`).

```bash
wyrd config init                          # then check vtr_root in the file
cp -r samples ~/wyrd-samples              # run in a copy: runs/ and wyrd.db go into the project
wyrd run --project ~/wyrd-samples
wyrd table --project ~/wyrd-samples --metrics luts,clbs,hard_blocks.memory,hard_blocks.mult_36
```

Expected (the `dsp` design uses one multiplier and one memory on both architectures):

```text
| design | arch | status | luts | clbs | hard_blocks.memory | hard_blocks.mult_36 |
|---|---|---|---|---|---|---|
| dsp | EArch | ok | 56 | 6 | 1 | 1 |
| dsp | k6_frac_N10_frac_chain_mem32K_40nm | ok | 56 | 6 | 1 | 1 |
| multi | EArch | ok | 5 | 1 | 0 | 0 |
| multi | k6_frac_N10_frac_chain_mem32K_40nm | ok | 5 | 1 | 0 | 0 |
| single | EArch | ok | 4 | 1 | 0 | 0 |
| single | k6_frac_N10_frac_chain_mem32K_40nm | ok | 4 | 1 | 0 | 0 |
```

Open the same folder in the GUI with `wyrd-gui ~/wyrd-samples` and press Run; the Report tab shows
the same table and a Summary per run.

## Reference results

`samples/expected/<arch>.json` holds the results of `odin3-flow` run directly on each design
(`samples/make-expected` rewrites them). The test `tests/test_samples.py` runs the samples into a
temporary copy and checks that `wyrd table` equals them; it is skipped when `odin3-flow` or `VTR_ROOT`
is missing. The files of `single` and `multi` are copied from Odin III and listed in `NOTICE`; `dsp` is new for Wyrd.

## Make your own from a sample

Copy a sample's design folder next to your own `wyrd.toml`, change the `files` and `top`, and add
or remove architectures in `[sweep]`. For a design of your own, start from `wyrd init` (see
{doc}`projects`) and for a worked example from an empty folder to the results table, read the PDF
tutorial `docs/tutorial/wyrd-tutorial.pdf`.

## Midgard III levels

The twelve levels and the tutorial level of Midgard III are the populated content for the game
(see {doc}`midgard`): `midgard --level 1` opens level 1 with a starter Verilog file for each of its
intersections.
