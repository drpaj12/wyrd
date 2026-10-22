# wyrd

Experiment runner for Odin III flows (W1 of Wyrd III). Python 3.11+, no runtime dependencies.

Wyrd III is part of **Yggdrasil III** (the project / world tree), the suite of Odin III
(<https://github.com/drpaj12/odin3>), Wyrd III, Loki III (<https://github.com/drpaj12/loki>) and Midgard III. Midgard III,
also known as Verilog Town, is the game Wyrd III will host (W4), after the original verilogTown (Jamieson, Grace,
Mizuno, Zhang, ASEE 2017).

    pip install -e .
    wyrd config init     # write ~/.config/wyrd/machine.toml with detected values
    wyrd config show     # effective settings and where each came from

Settings precedence, lowest first: built-in defaults, `machine.toml`, the project's `[run]`
table (`step_timeout` only), command-line flags. Design: `docs/specs/`.

## Samples

`samples/` holds three projects (`single`, `multi`, `dsp`) swept over two architectures. They need
Odin III 1.0 (`odin3`, `odin3-flow` on PATH) and `VTR_ROOT`.

    wyrd config init                          # then check vtr_root in machine.toml
    wyrd run --project samples
    wyrd table --project samples

`samples/expected/<arch>.json` holds the results of `odin3-flow` run directly
(`samples/make-expected` rewrites them). `tests/test_samples.py` runs the samples into a temporary
copy and checks that `wyrd table` equals them (skipped when `odin3-flow` or `VTR_ROOT` is missing).
Copied sample files are listed in `NOTICE`.
