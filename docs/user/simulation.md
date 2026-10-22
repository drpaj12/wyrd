# Simulation (Bifrost III)

Bifrost III (`wyrd.bifrost`) wraps Odin III's cycle-by-cycle simulator. It compiles Verilog with
`read_verilog; proc; opt; lower`, then gives you named inputs and outputs, a step, a reset,
recording and VCD output. It needs the `sim` extra (the `odin3` Python package, 1.0.3 or later).
One step is one rising edge of the clock.

Limits of the simulator: clocks must be top-level inputs (a clock is stepped, not set); a signal
removed by optimisation must be marked `(* keep *)` in the HDL to stay visible; a port that mixes
clock and data use is not supported. A VCD written by Wyrd has one cycle of 10 time units
(timescale 1 ns) and values are sampled once per step, so a combinational output changes at the rising edge,
not at the input change.

## The Simulate tab

Tools > Simulate (Ctrl+T) opens it for the open project.

1. Pick the **Design** (and optionally a **Top** module; the design's `top` is the default) and press
   **Compile**. The status line shows `Compiled: N signals`; diagnostics are listed in the
   *Diagnostics* tab (double-click one to open its line).
2. The table on the left lists every signal with its width, kind (clock, input, output) and
   value. Type a value into an **input** cell: decimal, or with a prefix `0x` hex, `0b` binary or `0o` octal. A bad value
   marks the cell red.
3. Drive the clock: **Step** (one cycle), **Step N** with a count, **Run** (checkable; steps at the
   chosen **speed** until you press Pause), **Reset**.
4. The *Waveform* tab draws the recorded signals (the **Radix** box picks hex, dec or bin; *Show
   internal signals* records internal nets too; *Record* is on by default).
5. **Run random** (cycles and a seed) or **Run vectors** (a file, edited in the *Vectors* tab, with
   Open..., Save... and *Generate template*) apply many cycles at once.
6. **Save VCD...** writes the recording as a VCD, **Save vectors...** writes the inputs and outputs
   as a vector file, **Open in GTKWave** opens the VCD (`$WYRD_GTKWAVE`, else `gtkwave` on PATH).

## `wyrd sim`

```bash
wyrd sim FILES... [--top TOP] (--vectors FILE | --random N) [--seed S] [--vcd OUT]
         [--save-vectors FILE] [--csv]
```

`--vectors` and `--random` are exclusive and one is required. Exit codes: 0 done; 2 a compile error
(diagnostics are printed as `file:line:col: severity: message` on stderr), a bad vector file or any
other error. Each cycle prints `CYCLE: input=value ... | output=value ...`; `--csv` prints
`cycle,<inputs>,<outputs>` instead.

A **vector file** is text. Comment lines start with `#`; the header comments `# clock NAME 0`,
`# input NAME WIDTH` and `# output NAME WIDTH` name the ports. Each other line is
`CYCLE INPUTS [OUTPUTS]` with the ports written as binary digits, most significant bit first, in
header order (`-` stands for no ports). `--save-vectors` writes a file in this form, with the outputs of
the run.

## From Python

```python
from wyrd.bifrost import BifrostSession

with BifrostSession.from_verilog(["src/top.v"], top="top") as sim:
    sim.set("rst", 1)
    sim.step()
    sim.set("rst", 0)
    sim.step(4)
    print(sim.get("total"))
```

`from_verilog(files, *, top=None, backend=None)` compiles; `set(name, value)`, `get(name)`, `step(cycles=1)`
and `reset()` work on named signals, and `sim.signals` lists them. `sim.start_recording()` returns a
`Recording` that fills as you step; `from wyrd.bifrost import write_vcd` then writes it with
`write_vcd(recording, Path("out.vcd"))`.
