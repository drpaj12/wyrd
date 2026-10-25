"""Critical-path attribution (``attribution.json`` of ``odin3-flow --timing-attr``), Qt-free.

Reads the file only; never imports odin3. Supports ``schema_version`` 1.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
FILE_NAME = "attribution.json"
INPUTS_NAME = "inputs.json"
LOG_NAME = "timing.log"
MAX_ATTRIBUTION_BYTES = 64 * 1024 * 1024
MAX_SMALL_BYTES = 1024 * 1024
STEP_GLOB = "*-odin3-flow"


class TimingError(Exception):
    """The attribution cannot be used; the message says why, in one line."""


@dataclass(frozen=True)
class Statement:
    """One source line that is on an attributed path (an entry of ``spans``)."""

    file: str
    line: int
    text: str | None
    module: str
    word: str
    delay_ns: float
    share: float
    paths_through: int
    worst_slack_ns: float | None

    @property
    def id(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass(frozen=True)
class PathEntry:
    """One entry of the critical path, in path order."""

    kind: str
    file: str | None
    line: int | None
    module: str
    word: str
    delay_ns: float
    share: float


@dataclass(frozen=True)
class Ranked:
    """A module or a word with its delay on the critical path."""

    name: str
    delay_ns: float
    share: float
    paths_through: int


@dataclass(frozen=True)
class Attribution:
    top: str
    fmax_mhz: float | None
    cpd_ns: float | None
    worst_slack_ns: float | None
    paths_kept: int
    matched_delay_share: float | None
    statements: tuple[Statement, ...]
    modules: tuple[Ranked, ...]
    words: tuple[Ranked, ...]
    critical_path: tuple[PathEntry, ...]
    path_lines: tuple[tuple[tuple[str, int, float], ...], ...]
    """Per attributed path (worst first): its matched (file, line, delay_ns) nodes."""


def _obj(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TimingError(f"attribution.json: {what} is not an object")
    return value


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise TimingError(f"attribution.json: {what} is not a list")
    return value


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _num0(value: object) -> float:
    return _num(value) or 0.0


def _int0(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _first(value: object) -> str:
    items = value if isinstance(value, list) else []
    return ", ".join(str(x) for x in items)


def _statement(raw: object) -> Statement | None:
    if not isinstance(raw, dict):
        return None
    item = raw
    line = item.get("line")
    file = item.get("file")
    if not isinstance(file, str) or not isinstance(line, int) or isinstance(line, bool):
        return None
    words = _first(item.get("words")) or _str(item.get("assigned_word"))
    text = item.get("text")
    return Statement(
        file,
        line,
        text if isinstance(text, str) else None,
        _first(item.get("modules")),
        words,
        _num0(item.get("critical_delay_ns")),
        _num0(item.get("critical_share")),
        _int0(item.get("paths_through")),
        _num(item.get("worst_slack_ns")),
    )


def _ranked(raw: object, key: str) -> Ranked | None:
    if not isinstance(raw, dict):
        return None
    item = raw
    name = _str(item.get(key))
    if key == "word":
        name = f"{_str(item.get('module'))}.{name}" + (" (port)" if item.get("port") else "")
    return Ranked(
        name,
        _num0(item.get("critical_delay_ns")),
        _num0(item.get("critical_share")),
        _int0(item.get("paths_through")),
    )


def _entry(raw: object) -> PathEntry | None:
    if not isinstance(raw, dict):
        return None
    item = raw
    line = item.get("line")
    file = item.get("file")
    return PathEntry(
        _str(item.get("kind")),
        file if isinstance(file, str) else None,
        line if isinstance(line, int) and not isinstance(line, bool) else None,
        _str(item.get("module")),
        _first(item.get("words")),
        _num0(item.get("delay_ns")),
        _num0(item.get("share")),
    )


def split_span(span: object) -> tuple[str, int] | None:
    """``file:line`` to (file, line); the file may itself contain colons."""
    if not isinstance(span, str) or ":" not in span:
        return None
    file, _, tail = span.rpartition(":")
    return (file, int(tail)) if tail.isdigit() and file else None


def _path_lines(raw: object) -> tuple[tuple[str, int, float], ...] | None:
    if not isinstance(raw, dict):
        return None
    nodes = _list(raw.get("nodes"), "path nodes")
    out: list[tuple[str, int, float]] = []
    for item in nodes:
        if not isinstance(item, dict):
            continue
        where = split_span(item.get("span"))
        if where is not None:
            out.append((where[0], where[1], _num0(item.get("delay_ns"))))
    return tuple(out)


def parse(data: object) -> Attribution:
    """Validate the decoded JSON and build the model; raise ``TimingError``."""
    top = _obj(data, "the top level")
    version = top.get("schema_version")
    if type(version) is not int or version != SCHEMA_VERSION:
        raise TimingError(
            f"attribution.json has schema_version {version!r}; "
            f"this Wyrd reads schema_version {SCHEMA_VERSION} only"
        )
    timing = _obj(top.get("timing"), "timing")
    cover = _obj(top.get("coverage"), "coverage")
    critical = _obj(top.get("critical_path"), "critical_path")
    design = _obj(top.get("design"), "design")
    statements = [_statement(s) for s in _list(top.get("spans"), "spans")]
    paths = [_path_lines(p) for p in _list(top.get("paths"), "paths")]
    modules = [_ranked(m, "module") for m in _list(top.get("modules"), "modules")]
    words = [_ranked(w, "word") for w in _list(top.get("words"), "words")]
    entries = [_entry(e) for e in _list(critical.get("spans"), "critical_path.spans")]
    return Attribution(
        _str(design.get("top")),
        _num(timing.get("fmax_mhz")),
        _num(timing.get("cpd_ns")),
        _num(timing.get("worst_slack_ns")),
        _int0(timing.get("paths_kept")),
        _num(cover.get("critical_matched_delay_share")),
        tuple(s for s in statements if s is not None),
        tuple(m for m in modules if m is not None),
        tuple(w for w in words if w is not None),
        tuple(e for e in entries if e is not None),
        tuple(p for p in paths if p is not None),
    )


def _read_capped(path: Path, limit: int) -> str:
    """Text of ``path``; raise ``TimingError`` when it is unreadable or over ``limit`` bytes."""
    try:
        size = path.stat().st_size
        if size > limit:
            raise TimingError(f"{path.name} is {size} bytes, over the {limit} byte limit")
        with path.open("rb") as handle:
            data = handle.read(limit + 1)
    except OSError as e:
        raise TimingError(f"cannot read {path.name}: {e.strerror or e}") from e
    if len(data) > limit:
        raise TimingError(f"{path.name} is over the {limit} byte limit")
    return data.decode("utf-8", errors="replace")


def load_attribution(path: Path) -> Attribution:
    """Read ``path``; raise ``TimingError`` with a plain message when it is missing or bad.

    Reads at most ``MAX_ATTRIBUTION_BYTES``. The read is synchronous (the Timing panel calls it
    on the GUI thread; it is not moved to the load pool).
    """
    text = _read_capped(path, MAX_ATTRIBUTION_BYTES)
    try:
        data = json.loads(text)
    except ValueError as e:
        raise TimingError(f"{path.name} is not valid JSON: {e}") from e
    return parse(data)


def _step_order(step: Path) -> tuple[int, str]:
    """Sort key of a step directory ``<n>-<tool>``: by the integer ``n``, so 2 comes before 10."""
    m = re.match(r"(\d+)-", step.name)
    return (int(m.group(1)) if m else -1, step.name)


def _flow_steps(run_dir: Path) -> list[Path]:
    try:
        return sorted(run_dir.glob(STEP_GLOB), key=_step_order)
    except OSError:
        return []


def find_attribution(run_dir: Path) -> Path | None:
    """The attribution.json of the last odin3-flow step directory of a run, if it exists."""
    for step in reversed(_flow_steps(run_dir)):
        cand = step / "out" / "timing" / FILE_NAME
        if cand.is_file():
            return cand
    return None


def missing_reason(run_dir: Path) -> str | None:
    """Why there is no attribution: the text of the last ``timing/timing.log``; None without one."""
    for step in reversed(_flow_steps(run_dir)):
        log = step / "out" / "timing" / LOG_NAME
        if not log.is_file():
            continue
        try:
            text = _read_capped(log, MAX_SMALL_BYTES).strip()
        except TimingError:
            return None
        if text == "ok":
            return f"timing.log says ok but {FILE_NAME} is missing"
        return text[:500] or None
    return None


def critical_line_shares(att: Attribution) -> dict[str, dict[int, float]]:
    """Per file, per line: the share of the critical path delay (sums to at most 1)."""
    out: dict[str, dict[int, float]] = {}
    for e in att.critical_path:
        if e.file is not None and e.line is not None:
            lines = out.setdefault(e.file, {})
            lines[e.line] = lines.get(e.line, 0.0) + e.share
    return out


def top_line_shares(att: Attribution, n: int) -> dict[str, dict[int, float]]:
    """Per file, per line: delay on the worst ``n`` paths over the delay of those paths."""
    chosen = att.path_lines[: max(n, 0)]
    total = sum(delay for path in chosen for _, _, delay in path)
    out: dict[str, dict[int, float]] = {}
    if total <= 0:
        return out
    for path in chosen:
        for file, line, delay in path:
            lines = out.setdefault(file, {})
            lines[line] = lines.get(line, 0.0) + delay / total
    return out


@dataclass(frozen=True)
class SourceHints:
    """Where the producer looked for sources (``source_cwd`` and ``designs`` of ``inputs.json``)."""

    search_dirs: tuple[Path, ...] = ()
    designs: tuple[Path, ...] = ()


def source_hints(attribution: Path) -> SourceHints:
    """The hints next to ``attribution`` (``out/timing/attribution.json``); empty when absent."""
    flow = attribution.parent.parent
    try:
        data = json.loads(_read_capped(attribution.parent / INPUTS_NAME, MAX_SMALL_BYTES))
    except (TimingError, ValueError):
        return SourceHints((flow,))
    raw = data if isinstance(data, dict) else {}
    cwd = raw.get("source_cwd")
    dirs = [flow]
    if isinstance(cwd, str) and cwd:
        dirs.insert(0, flow / cwd)
    designs = raw.get("designs")
    named = [Path(d) for d in designs if isinstance(d, str)] if isinstance(designs, list) else []
    return SourceHints(tuple(dirs), tuple(named))


class SourceResolver:
    """Maps the file names of an attribution to files on disk, inside the project ``roots`` only.

    Order: the recorded ``source_cwd`` and flow directory, the recorded designs by path suffix,
    each root; then a base-name match, accepted only when exactly one file matches. A name with
    ``..`` and a path outside every root is never returned. Results are cached.
    """

    def __init__(self, roots: Sequence[Path], hints: SourceHints | None = None) -> None:
        self.roots = list(roots)
        self.hints = hints or SourceHints()
        self._real = [r.resolve() for r in self.roots]
        self._cache: dict[str, Path | None] = {}

    def inside(self, path: Path) -> bool:
        try:
            real = path.resolve()
        except OSError:
            return False
        return any(real.is_relative_to(r) for r in self._real)

    def _usable(self, path: Path) -> bool:
        return path.is_file() and self.inside(path)

    def _exact(self, given: Path) -> list[Path]:
        if given.is_absolute():
            return [given]
        n = len(given.parts)
        recorded = [d / given for d in self.hints.search_dirs]
        by_suffix = [d for d in self.hints.designs if d.parts[-n:] == given.parts]
        return recorded + by_suffix + [r / given for r in self.roots]

    def _unique(self, pool: Sequence[Path], name: str) -> list[Path]:
        seen: dict[Path, Path] = {}
        for cand in pool:
            if cand.name == name and self._usable(cand):
                seen.setdefault(cand.resolve(), cand)
        return list(seen.values())

    def _named(self, name: str) -> list[Path]:
        """Files called ``name``: among the recorded designs first, else under the roots."""
        recorded = self._unique(self.hints.designs, name)
        return recorded if recorded else self._unique([r / name for r in self.roots], name)

    def _find(self, file: str) -> Path | None:
        given = Path(file)
        if ".." in given.parts or not file:
            return None
        for cand in self._exact(given):
            if self._usable(cand):
                return cand
        named = self._named(given.name)
        return named[0] if len(named) == 1 else None

    def resolve(self, file: str) -> Path | None:
        if file not in self._cache:
            self._cache[file] = self._find(file)
        return self._cache[file]


def resolve_source(
    file: str, roots: Sequence[Path], hints: SourceHints | None = None
) -> Path | None:
    """The file on disk for ``file``; see ``SourceResolver``."""
    return SourceResolver(roots, hints).resolve(file)


def file_shares(
    shares: dict[str, dict[int, float]], path: Path, resolver: SourceResolver
) -> dict[int, float]:
    """The line shares that belong to the disk file ``path``."""
    out: dict[int, float] = {}
    target = path.resolve()
    for name, lines in shares.items():
        found = resolver.resolve(name)
        if found is not None and found.resolve() == target:
            for line, share in lines.items():
                out[line] = out.get(line, 0.0) + share
    return out


def _where(file: str | None, line: int | None) -> str:
    return "(I/O port)" if file is None or line is None else f"{file}:{line}"


def summary_lines(att: Attribution, top: int = 10) -> list[str]:
    """The text of ``wyrd timing``: header, critical path in order, ranked statements."""
    fmax = "n/a" if att.fmax_mhz is None else f"{att.fmax_mhz:.2f} MHz"
    cpd = "n/a" if att.cpd_ns is None else f"{att.cpd_ns:.3f} ns"
    lines = [
        f"Timing of {att.top or '(unknown top)'}: Fmax {fmax}, CPD {cpd}, "
        f"{att.paths_kept} paths attributed"
    ]
    lines.append("Critical path, in order:")
    for e in att.critical_path:
        lines.append(
            f"  {_where(e.file, e.line)}  module {e.module}  word {e.word or '-'}  "
            f"{e.delay_ns:.3f} ns ({e.share * 100:.1f}%)"
        )
    lines.append("Statements that set the critical path:")
    for s in att.statements[:top]:
        lines.append(
            f"  {s.share * 100:5.1f}%  {s.delay_ns:.3f} ns  {s.id}  module {s.module}  "
            f"word {s.word or '-'}"
        )
    return lines
