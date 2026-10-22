"""Builds a small results folder (run directory plus wyrd.db) for the GUI model tests."""

import shutil
from pathlib import Path

from wyrd.model import Design, Metric, Recipe, RunSpec, StepSpec
from wyrd.store import Store

LOGS = Path(__file__).parent / "data" / "logs"
KEY = "a" * 64


def make_results(root: Path) -> Path:
    """Write one ok run (design single, arch EArch, recipe vtr) under ``root``; return its dir."""
    run_dir = root / "runs" / "single" / "EArch" / KEY[:12]
    step = run_dir / "0-odin3-flow"
    (step / "out" / "odin3").mkdir(parents=True)
    (step / "out" / "vpr" / "run").mkdir(parents=True)
    (step / "cmd.sh").write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
    shutil.copy(LOGS / "odin3_sample.log", step / "out" / "odin3" / "odin3.log")
    shutil.copy(LOGS / "vpr_sample.log", step / "out" / "vpr" / "run" / "vpr_stdout.log")
    recipe = Recipe("vtr", (StepSpec("odin3-flow"),))
    spec = RunSpec(Design("single", (root / "a.v",), None), "EArch", recipe)
    store = Store(root / "wyrd.db")
    store.begin(KEY, spec, run_dir)
    store.add_step(KEY, 0, "odin3-flow", ["odin3-flow"], 0, 1.0, None)
    store.add_metrics(
        KEY,
        "odin3-flow",
        [
            Metric("luts", 56),
            Metric("clbs", 6),
            Metric("hard_blocks.mult_36", 1),
            Metric("min_chan_width", 32),
            Metric("crit_path_ns", 5.5),
        ],
    )
    store.finish(KEY, "ok")
    return run_dir
