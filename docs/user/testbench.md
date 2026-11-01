# Testbenches (Bifrost III)

Besides driving a design with a vector file (`wyrd sim`), Wyrd runs a design's own Verilog testbench
through Odin III and converts between vector files and testbenches. It uses Odin III's `sim_tb` and
`run_testbenches` passes through the `odin3` Python package, so Wyrd never changes the core.

Needs an Odin III main after PR 310 (planned v1.2.0; the latest tag v1.1.1 does not have
`run_testbenches`). Run against a checkout with `ODIN3_LIB=<build>/libodin3.so` and
`PYTHONPATH=<odin3>/plugins/python`. Without it the commands say so and exit 2. The `sim` extra stays
`odin3>=1.0.3`: cycle simulation does not need the newer pass.

## `wyrd tb run`

```bash
wyrd tb run --project FILE.o3proj [--only NAME] [--seed N] [--json OUT]
wyrd tb run --tb TB.v --dut FILES... [--dut-top M] [--tb-top M] [--dut-inst NAME]
            [--max-time T] [--expect FILE] [--on rtl|netlist|both]
            [--seed N] [--json OUT] [--out TEXT] [--vcd OUT]
```

`--project` runs the `testbench` lines of an Odin III project (or a Quartus `.qsf` import). `--tb` runs
one testbench file against DUT files; Wyrd wraps it in a temporary project so Odin III's rules apply.
`--on` picks the design the testbench drives: `rtl` (default), `netlist` (after `abc --lut 6`) or `both`
(the two compared line by line). `--expect` is a golden text of the `$display` output.

Each testbench prints `name status on wall_ms`. Status is `pass`, `fail`, `error` or `timeout` (no
`$finish` by the time limit; `--max-time` sets it). A failed comparison adds the first mismatch (line,
leading number of the line, field, wanted and got text); an error names the step. The last line counts
each status. Exit codes: 0 all pass; 1 a testbench failed, errored or timed out; 2 usage, compile or
backend error. `--json` writes the typed results. `--out` writes the `$display` text.

`--vcd` writes a waveform. Odin III does not implement `sim_tb --vcd` yet, so Wyrd replays the input
columns of the printed vector lines (see below) through the simulator; it works for testbenches that print
Wyrd's format and stops with an error for others.

## `wyrd tb convert`

```bash
wyrd tb convert --to tb      --dut FILES... --vectors V.txt --out TB.v [--dut-top M]
wyrd tb convert --to vectors --dut FILES... --tb TB.v       --out V.txt [--dut-top M]
```

`--to tb` writes a self-contained, port-only testbench `wyrd_tb`: one line per cycle sets every input,
raises the clock, and 1 time unit after the edge prints `CYCLE INPUTBITS OUTPUTBITS`, which is a vector
line. It uses only constructs Odin III's `sim_tb` supports, and iverilog (`iverilog -g2005; vvp`)
prints the same text. The DUT top is the one module no other module instantiates, or `--dut-top`.
Ports wider than 64 bits are refused.

`--to vectors` runs the testbench on Odin III and writes the printed vector lines as a Bifrost vector
file (with the output column). A testbench that prints other text cannot be converted. Vectors to
testbench to vectors gives back the same file, byte for byte (the first header line is kept in a
`// wyrd-vectors-header:` comment of the testbench).

The simulator is 2-state and powers on with state 0, iverilog with x: begin a vector file with a reset.

## From Python

```python
from pathlib import Path
from wyrd.bifrost import TbSpec, run_project_testbenches, run_testbench_file

report = run_project_testbenches("project.o3proj")          # TbReport of TbResult
result = run_testbench_file(TbSpec(Path("tb.v"), [Path("dut.v")], on="both"))
print(result.status, result.mismatch, result.output)
```

`vectors_file_to_testbench`, `testbench_file_to_vectors` and `testbench_file_to_vcd` convert files;
`vectors_to_testbench` and `testbench_to_vectors` convert text. Tests inject a fake `ScriptRunner`.

The GUI has no testbench panel yet. It would need a testbench list (name, `on`, status), a Run button
that calls `run_project_testbenches` in a worker thread, a result pane for the first mismatch, an Open VCD
button and the two conversions on the Vectors tab.
