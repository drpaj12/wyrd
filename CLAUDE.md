# wyrd

W1 experiment runner and W2 GUI, part of Wyrd III. Expands a TOML project into runs, executes them under a
memory budget, stores results (run directories plus `wyrd.db`), prints tables. Depends on Odin III
only as programs (`odin3`, `odin3-flow`, `vpr`, `abc`); never imports its Python, except `wyrd.bifrost` (W3), the one exception, contained in `wyrd/bifrost/backend.py`.

Specs: `docs/specs/2026-10-21-w1-runner-design.md`, `docs/specs/2026-10-21-w2-gui-design.md`.
Plans: `docs/plans/2026-10-21-w1-runner-plan.md`, `docs/plans/2026-10-21-w2-gui-plan.md`.

## Setup

    python3 -m venv .venv && .venv/bin/pip install -e ".[gui]" ruff mypy

## Build, test, lint

    .venv/bin/python -m unittest discover -s tests -t . -v
    QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_gui_smoke -v
    QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest tests.test_gui_sim -v
    PYTHONPATH=/home/jamiespa/odin3-ws/work/odin3-s1/plugins/python ODIN3_LIB=<S1 build>/libodin3.so .venv/bin/python -m unittest tests.test_sim_odin3 -v   # real Odin III (needs cffi)
    .venv/bin/ruff check .
    .venv/bin/mypy --strict wyrd tests

## Rules

- Never commit to main. Open a PR; merge (squash) only with green CI.
- Python 3.11+ (no 3.12-only syntax). Core is standard library only at runtime; PySide6 only under `wyrd/gui/`; optional extras `gui` (PySide6), `sim` (odin3, W3) and `midgard` (pygame-ce, W4).
- ruff and `mypy --strict` clean. Tests are `unittest` under `tests/`.
- Small functions. No `# noqa`, `# type: ignore` or similar suppressions without Peter's approval.
- Exit codes: 0 all runs ok; 1 some run not ok; 2 usage, config or preflight error.
- Machine settings: `$WYRD_CONFIG`, else `~/.config/wyrd/machine.toml`.
- Commit and push often, after each green step.
