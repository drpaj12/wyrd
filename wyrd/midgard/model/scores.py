"""High-score table (spec 5.8): ten `cars ticks` rows, best first."""

from __future__ import annotations

from collections.abc import Sequence

from wyrd.midgard.model.clock import TICKS_PER_SECOND

ScoreEntry = tuple[int, int]
SIZE = 10
_EMPTY: ScoreEntry = (0, 0)


def _key(e: ScoreEntry) -> tuple[int, int]:
    return (-e[0], e[1])


def _normalise(entries: Sequence[ScoreEntry]) -> list[ScoreEntry]:
    good = sorted((e for e in entries if e[0] >= 1), key=_key)[:SIZE]
    return good + [_EMPTY] * (SIZE - len(good))


def format_time(ticks: int) -> str:
    m, s = divmod(ticks // TICKS_PER_SECOND, 60)
    return f"{m:02d}:{s:02d}"


def _parse_line(line: str) -> ScoreEntry:
    parts = line.split()
    if len(parts) != 2:
        return _EMPTY
    try:
        return (max(0, int(parts[0])), max(0, int(parts[1])))
    except ValueError:
        return _EMPTY


class ScoreTable:
    def __init__(self, entries: Sequence[ScoreEntry] = ()) -> None:
        self.entries: list[ScoreEntry] = _normalise(entries)

    def insert(self, cars: int, ticks: int) -> int | None:
        """Insert a result; return its 0-based rank, or None when it is not kept."""
        new = (cars, ticks)
        if cars < 1 or new in self.entries:
            return None
        for rank, entry in enumerate(self.entries):
            if _key(new) < _key(entry):
                self.entries.insert(rank, new)
                del self.entries[SIZE:]
                return rank
        return None

    def to_text(self) -> str:
        return "".join(f"{c} {t}\n" for c, t in self.entries)

    @classmethod
    def from_text(cls, text: str) -> ScoreTable:
        rows = [_parse_line(line) for line in text.splitlines()[:SIZE]]
        return cls(rows)
