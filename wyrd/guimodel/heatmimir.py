"""Adapter: Mímir v5 ``timing_object`` rows to a ``HeatModel`` (Qt-free).

Written against ``docs/specs/2026-10-28-near-critical.md`` of the Mímir branch
``feat/near-critical``:
``kind='span'`` rows have key ``file:line``; ``kind='word'`` rows have key ``module/word``, ``bit``
(-1 for the word as a whole) and ``via``. The rows carry ``crit_max`` but no path list, so only the
near-critical scope is available and "paths through" is empty.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from wyrd.guimodel import timing
from wyrd.guimodel.heat import Fact, HeatModel, round_crit

ObjectRow = Sequence[object]
"""(kind, object_key, bit, via, crit_max)"""

NOTE = "Mímir rows hold no path list: only the near-critical scope is available."


def _num(x: object) -> float:
    return float(x) if isinstance(x, int | float) and not isinstance(x, bool) else 0.0


def _fact(row: ObjectRow) -> Fact | None:
    kind, key = str(row[0]), str(row[1])
    bit = int(_num(row[2]))
    via, crit = str(row[3]), round_crit(_num(row[4]))
    if kind == "span":
        where = timing.split_span(key)
        if where is None:
            return None
        return Fact(where[0], where[1], "", "", None, "", 0.0, crit, -1, -1)
    if kind == "word":
        module, _, word = key.rpartition("/")
        if not word:
            return None
        return Fact(None, None, module, word, bit if bit >= 0 else None, via, 0.0, crit, -1, -1)
    return None


def _drop_aggregates(facts: list[Fact]) -> list[Fact]:
    """A word row with bit -1 is the aggregate of its bit rows: drop it when bit rows exist."""
    with_bits = {(f.module, f.word) for f in facts if f.bit is not None}
    return [f for f in facts if f.bit is not None or (f.module, f.word) not in with_bits]


def model_from_objects(
    rows: Iterable[ObjectRow], origin: str = "", dmax_source: str = "", store: str = "",
    run_id: str = "",
) -> HeatModel:
    facts = _drop_aggregates([f for f in (_fact(r) for r in rows) if f is not None])
    widths: dict[tuple[str, str], int] = {}
    for f in facts:
        if f.bit_known and f.bit is not None:
            widths[(f.module, f.word)] = max(widths.get((f.module, f.word), 0), f.bit + 1)
    # Word rows carry no file: they colour only the files named by the span rows.
    span_files = {f.file for f in facts if f.file is not None} | ({origin} if origin else set())
    modules = {f.module for f in facts if f.module}
    module_files = {m: set(span_files) for m in modules}
    model = HeatModel(
        tuple(facts), {}, widths, module_files, [NOTE], has_paths=False, source="mimir",
        origin=origin, store=store, run_id=run_id,
    )
    if dmax_source == "report":
        model.notes.append("crit is a lower bound (dmax from report)")
    elif dmax_source:
        model.notes.append(f"crit is exact ({dmax_source.replace('-', ' ')})")
    if not facts:
        model.notes.append("the run has no span or word rows")
    return model
