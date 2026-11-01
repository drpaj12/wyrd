# Bifrost III testbench mode (spec, 2026-10-31)

Purpose: Wyrd III is the visualization tool and experiment runner. A user can already drive a design
with an input-vector file (`wyrd sim`). This adds the other half: run the design's own Verilog
testbench through Odin III and see the result, and convert between vector files and testbenches.
RQ: tool usability for the reverse-engineering and experiment flows (no new research question).
Measure: none (a feature); correctness is judged against iverilog.

Odin III provides (read only, never changed by Wyrd): `sim_tb`, `testbench_gen`, `tb-compare`
(docs/user/testbench.md) and `run_testbenches` for `.o3proj` projects (spec
`docs/specs/2026-10-31-project-testbench-design.md` in the Odin III repo). Wyrd uses them through the
`odin3` Python package, in `wyrd/bifrost/backend.py` only.

## 1. Backend

`ScriptRunner` (Protocol) with `run(script, cwd) -> ScriptOutcome(ok, error, log)`. `Odin3Runner`
creates a `Design`, runs the script under `capture_log`, returns the log records and the last error
level message. A fake runner serves the unit tests.

## 2. Running testbenches (`wyrd.bifrost.testbench`)

Typed result: `TbResult(name, status, on, wall_ms, end_time, lines, mismatch, timeout, error, output)`
with `status` in `pass|fail|error|timeout` and `TbMismatch(compared, line, time, field, want, got)`.
`timeout` is a Wyrd status: Odin III reports `status fail` with `timeout true`; Wyrd maps that pair
to `timeout`. `TbReport(results, passed, failed, errors, timeouts)`.

- `run_project_testbenches(project, only=None, seed=0, runner=None)`: script
  `read_project P; read_verilog; proc; opt; lower; [abc --lut 6;] run_testbenches --json J [--only N] [--seed S]`.
  The `abc` step is added when a selected testbench has `on netlist|both` (found by reading the
  project's `testbench` lines; when that is unknown, `abc` is added). A nonzero pass status is
  normal (a failing testbench); the JSON is the answer. No JSON written: `TbError` with the log.
- `run_testbench_file(dut_files, tb, ...)`: a temporary project is written
  (`file verilog ...`, `top`, `testbench t file tb top dut max-time expect on`) and run as above,
  so status, timeout, expect and rtl/netlist/both come from Odin III's own rules. In addition the
  `$display` text is captured with `sim_tb --out` (rtl: before `abc`; netlist: after) and returned in
  `output`. The temporary project lives under a `TemporaryDirectory`.
- VCD: `sim_tb --vcd` is refused by Odin III ("not implemented yet", spec section 8 deviation 2).
  Wyrd therefore derives a VCD from the vector lines in the output text (section 3) by replaying the
  input columns through `BifrostSession` and `write_vcd`, which feeds the existing record/vcd viewers.
  Works for testbenches that print Wyrd vector lines; otherwise an error says so.

## 3. Conversion (`wyrd.bifrost.tbconvert`)

Vector line format: the Bifrost file (`<cycle> <input bits> [<output bits>]`, `# input|clock|output` port
lines). Semantics: row c sets all data inputs, applies one rising edge, outputs are read after it.

`vectors_to_testbench(module, ports, outputs, vf, header)` writes a self-contained, port-only testbench
`wyrd_tb` (unrolled, one line per cycle, no data files, only constructs `sim_tb` supports):

    reg clk; reg [7:0] a; wire [3:0] q;
    top u_dut(.clk(clk), .a(a), .q(q));
    initial begin
      clk = 0; a = 0;
      a = 8'b00000101; #5 clk = 1; #1 $display("0 00000101 %b", q); #4 clk = 0;
      ...
      $finish;
    end

It prints `<cycle> <input bits> <output bits>` per cycle, i.e. exactly a vector line. The first line is a
comment `// wyrd-vectors-header: <original header>` so the round trip restores the header.
`testbench_to_vectors(output_text, ports, outputs, header)` reads those lines back (lines that do not look
like a vector line are ignored), checks cycle numbers and widths, and writes the vector file (with the
output column, as `wyrd sim --save-vectors` does). Round trip test: a vector file saved by
`wyrd sim --save-vectors` -> testbench -> sim_tb output -> vector file is byte-identical.
Checked in iverilog: the generated testbench, run with `iverilog -g2005; vvp`, prints the same lines as
`sim_tb`. A foreign testbench whose output is not in this format cannot be converted (error names the
format). Ports wider than 64 bits are refused (sim_tb limit).

## 4. CLI (wyrd/tbcli.py, registered in wyrd/cli.py)

    wyrd tb run (--project FILE.o3proj [--only NAME] | --tb FILE --dut FILES... [--dut-top TOP]
                 [--tb-top MOD] [--dut-inst NAME] [--max-time T] [--expect FILE]
                 [--on rtl|netlist|both]) [--seed N] [--json OUT] [--out TEXT] [--vcd OUT]
    wyrd tb convert --to tb      --dut FILES... --vectors FILE --out FILE [--dut-top TOP]
    wyrd tb convert --to vectors --dut FILES... --tb FILE --out FILE [--dut-top TOP]

Exit: 0 all pass; 1 a testbench failed, errored or timed out; 2 usage, compile or backend error.
Output: one line per testbench `name status on wall_ms`, a mismatch or error line, a total line.

## 5. API (wyrd.bifrost)

`TbResult, TbMismatch, TbReport, TbError, run_project_testbenches, run_testbench_file, vectors_to_testbench,
testbench_to_vectors, ScriptRunner, Odin3Runner`.

## 6. GUI

The Simulate tab (Bifrost panel) exists. This round adds no panel. A panel would need: a project
testbench list (name, on, status), a Run button calling `run_project_testbenches` in a worker thread,
a result pane with the first mismatch (want/got), "Open VCD" from the derived VCD, and the two
conversion actions on the Vectors tab. The typed API above is the whole model.

## 7. Odin III version

Needs a libodin3 with `run_testbenches` and `sim_tb` (Odin III main after #310, 645aad16). Latest tag is
v1.1.1, which does not have them: the `sim` extra floor stays `odin3>=1.0.3` (cycle simulation still
works); testbench mode raises `SimUnavailable` ("needs an Odin III with run_testbenches") when the pass is
missing (checked by `odin3.passes()` or the first failure message). Run against a checkout with
`ODIN3_LIB=<build>/libodin3.so PYTHONPATH=<odin3>/plugins/python`.

## 8. Agent defaults

D-1 single-file runs go through a temporary project so Odin III's timeout/expect/on rules apply.
D-2 `timeout` is a separate status. D-3 netlist = `abc --lut 6` after `lower`. D-4 conversion uses the
Bifrost line format as the testbench's print format (foreign testbenches are not converted). D-5 unrolled
testbench, no stimulus files. D-6 VCD is derived from vector lines because `sim_tb --vcd` is unimplemented.
D-7 DUT top is detected by a regex over the sources when `--dut-top` is absent; ambiguity is an error.
D-8 paths containing whitespace, `"`, `;` are refused (the project syntax is word-based).
