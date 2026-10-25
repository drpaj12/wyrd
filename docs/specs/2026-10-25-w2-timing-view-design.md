# W2 timing view (design and plan)

Purpose: Wyrd W2, question W Q2.1 (how a designer sees which lines set the critical path). Measure:
speed (critical path delay, Fmax). Input: `timing/attribution.json` (`schema_version` 1) of
`odin3-flow --timing-attr`, read as a file; no odin3 import.

1. Step: `odin3-flow` args `timing_attr` (bool) and `timing_paths` (int >= 1, implies timing_attr);
   needs target vtr and vpr. Metrics `timing.fmax_mhz`, `timing.cpd_ns`, `timing.attributed`.
2. Model `wyrd/guimodel/timing.py` (stdlib): load, validate, statements, modules, words, critical
   path, per-line shares (critical path; worst N paths), source resolution under search roots.
3. GUI `wyrd/gui/timingpanel.py` (Timing dock) and a heat margin in `SourceView`.
4. CLI `wyrd timing KEY [--project DIR] [--top N]`.
5. Docs: gui.md, running.md, projects.md. Fixture `tests/data/timing` from a real run.
