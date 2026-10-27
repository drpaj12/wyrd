"""Placement atlas model: load one Norns round-7 atlas JSON, summarise it, colour and compare it.

Standard library only (no Qt). The format is the "Atlas export" of Norns round 7: one JSON (gzip
accepted) per run with `design`, `arm`, `seed`, `grid`, `cpd_ns`, `wirelength`, `chan_width`,
`clbs` (id, type, x, y, atoms) and `atoms` (name, kind, class, construct, inst, word, bit, crit,
pcrit). Source of the data: Norns round 7, VTR runs with VTR (Rose et al., FPGA 2012) and VTR 9
(Elgammal et al., TRETS 2025), commit 3c9a4d23b2.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CLB_TYPES = ("clb", "io", "mem", "mult")
CATEGORICAL_KEYS = ("construct", "word", "inst", "class")
NUMERIC_KEYS = ("crit", "pcrit")
KEYS = CATEGORICAL_KEYS + NUMERIC_KEYS
NONE_LABEL = "(none)"
RUN_NAME = re.compile(r"^(?P<arm>[A-Za-z0-9]+)\.s(?P<seed>\d+)\.json(?:\.gz)?$")
SAMPLE_NAME = re.compile(r"^(?P<design>.+)\.(?P<arm>[A-Za-z0-9]+)\.s(?P<seed>\d+)\.json(?:\.gz)?$")


class AtlasError(Exception):
    """The file is not a valid atlas; the message says why."""


@dataclass(frozen=True)
class Atom:
    name: str
    kind: str
    cls: str
    construct: str
    inst: str
    word: str | None
    bit: int | None
    crit: float | None
    pcrit: float | None


@dataclass(frozen=True)
class Clb:
    id: int
    type: str
    x: int
    y: int
    atoms: tuple[int, ...]


@dataclass(frozen=True)
class Atlas:
    design: str
    arm: str
    seed: int
    grid: tuple[int, int]
    cpd_ns: float | None
    wirelength: float | None
    chan_width: float | None
    clbs: tuple[Clb, ...]
    atoms: tuple[Atom, ...]

    def clb_by_id(self) -> dict[int, Clb]:
        return {c.id: c for c in self.clbs}

    def atom_clb(self) -> dict[int, int]:
        """Atom index -> id of the CLB that holds it (atoms in no CLB are absent)."""
        return {a: c.id for c in self.clbs for a in c.atoms}


# ---------------------------------------------------------------- loading


def _num(d: dict[str, object], key: str, where: str) -> float | None:
    v = d.get(key)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int | float):
        raise AtlasError(f"{where}: '{key}' is not a number")
    return float(v)


def _int(d: dict[str, object], key: str, where: str) -> int:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise AtlasError(f"{where}: '{key}' is not an integer")
    return v


def _str(d: dict[str, object], key: str, where: str, optional: bool = False) -> str | None:
    v = d.get(key)
    if v is None and optional:
        return None
    if not isinstance(v, str):
        raise AtlasError(f"{where}: '{key}' is not a string")
    return v


def _dict(v: object, where: str) -> dict[str, object]:
    if not isinstance(v, dict):
        raise AtlasError(f"{where} is not an object")
    return v


def _parse_atom(raw: object, i: int) -> Atom:
    where = f"atoms[{i}]"
    d = _dict(raw, where)
    bit = d.get("bit")
    if bit is not None and (isinstance(bit, bool) or not isinstance(bit, int)):
        raise AtlasError(f"{where}: 'bit' is not an integer")
    return Atom(
        name=str(_str(d, "name", where)),
        kind=str(_str(d, "kind", where)),
        cls=str(_str(d, "class", where)),
        construct=str(_str(d, "construct", where)),
        inst=str(_str(d, "inst", where)),
        word=_str(d, "word", where, optional=True),
        bit=bit,
        crit=_num(d, "crit", where),
        pcrit=_num(d, "pcrit", where),
    )


def _parse_clb(raw: object, i: int, n_atoms: int) -> Clb:
    where = f"clbs[{i}]"
    d = _dict(raw, where)
    kind = str(_str(d, "type", where))
    if kind not in CLB_TYPES:
        raise AtlasError(f"{where}: unknown type '{kind}'")
    members = d.get("atoms")
    if not isinstance(members, list):
        raise AtlasError(f"{where}: 'atoms' is not a list")
    for m in members:
        if isinstance(m, bool) or not isinstance(m, int) or not 0 <= m < n_atoms:
            raise AtlasError(f"{where}: atom index {m!r} out of range")
    return Clb(_int(d, "id", where), kind, _int(d, "x", where), _int(d, "y", where), tuple(members))


def _check_unique(clbs: list[Clb], grid: tuple[int, int]) -> None:
    seen_id: set[int] = set()
    seen_xy: set[tuple[int, int]] = set()
    held: set[int] = set()
    for c in clbs:
        if c.id in seen_id:
            raise AtlasError(f"duplicate CLB id {c.id}")
        if (c.x, c.y) in seen_xy:
            raise AtlasError(f"two CLBs at ({c.x}, {c.y})")
        if not (0 <= c.x < grid[0] and 0 <= c.y < grid[1]):
            raise AtlasError(
                f"CLB {c.id} at ({c.x}, {c.y}) is outside the {grid[0]}x{grid[1]} grid"
            )
        seen_id.add(c.id)
        seen_xy.add((c.x, c.y))
        for a in c.atoms:
            if a in held:
                raise AtlasError(f"atom {a} is in more than one CLB")
            held.add(a)


def parse_atlas(data: object) -> Atlas:
    """Validate a decoded atlas JSON object (raises AtlasError)."""
    d = _dict(data, "atlas")
    grid_raw = d.get("grid")
    if (
        not isinstance(grid_raw, list)
        or len(grid_raw) != 2
        or any(isinstance(g, bool) or not isinstance(g, int) or g < 1 for g in grid_raw)
    ):
        raise AtlasError("'grid' is not [width, height] of positive integers")
    grid = (int(grid_raw[0]), int(grid_raw[1]))
    atoms_raw, clbs_raw = d.get("atoms"), d.get("clbs")
    if not isinstance(atoms_raw, list) or not isinstance(clbs_raw, list):
        raise AtlasError("'atoms' and 'clbs' must be lists")
    atoms = [_parse_atom(a, i) for i, a in enumerate(atoms_raw)]
    clbs = [_parse_clb(c, i, len(atoms)) for i, c in enumerate(clbs_raw)]
    _check_unique(clbs, grid)
    return Atlas(
        design=str(_str(d, "design", "atlas")),
        arm=str(_str(d, "arm", "atlas")),
        seed=_int(d, "seed", "atlas"),
        grid=grid,
        cpd_ns=_num(d, "cpd_ns", "atlas"),
        wirelength=_num(d, "wirelength", "atlas"),
        chan_width=_num(d, "chan_width", "atlas"),
        clbs=tuple(clbs),
        atoms=tuple(atoms),
    )


def load_atlas(path: Path) -> Atlas:
    """Read an atlas file (.json or .json.gz); raises AtlasError on any problem."""
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, EOFError, ValueError) as e:  # gzip.BadGzipFile and JSONDecodeError included
        raise AtlasError(f"{path.name}: cannot read: {e}") from e
    try:
        return parse_atlas(data)
    except AtlasError as e:
        raise AtlasError(f"{path.name}: {e}") from e


# ---------------------------------------------------------------- finding runs


@dataclass(frozen=True)
class RunFile:
    design: str
    arm: str
    seed: int
    path: Path


def _run_of(path: Path, design: str | None) -> RunFile | None:
    if design is None:
        m = SAMPLE_NAME.match(path.name)
        return None if m is None else RunFile(m["design"], m["arm"], int(m["seed"]), path)
    m = RUN_NAME.match(path.name)
    return None if m is None else RunFile(design, m["arm"], int(m["seed"]), path)


def find_runs(root: Path) -> list[RunFile]:
    """Atlas files under a Norns runs/r7 root (`<design>/atlas/<arm>.s<seed>.json.gz`) or a
    flat folder of `<design>.<arm>.s<seed>.json.gz` samples; sorted by design, arm, seed."""
    found: list[RunFile] = []
    if not root.is_dir():
        return found
    for p in sorted(root.glob("*/atlas/*.json*")):
        r = _run_of(p, p.parent.parent.name)
        if r:
            found.append(r)
    for p in sorted(root.glob("*.json*")):
        r = _run_of(p, None)
        if r:
            found.append(r)
    found.sort(key=lambda r: (r.design, _arm_order(r.arm), r.seed))
    return found


def _arm_order(arm: str) -> tuple[int, str]:
    """stock first, then known, then hindsight rounds by number."""
    if arm == "stock":
        return (0, arm)
    m = re.fullmatch(r"h(\d+)", arm)
    return (2, f"{int(m[1]):04d}") if m else (1, arm)


def designs_of(runs: list[RunFile]) -> list[str]:
    return sorted({r.design for r in runs})


def arms_of(runs: list[RunFile], design: str) -> list[str]:
    return sorted({r.arm for r in runs if r.design == design}, key=_arm_order)


def seeds_of(runs: list[RunFile], design: str, arm: str) -> list[int]:
    return sorted({r.seed for r in runs if r.design == design and r.arm == arm})


def path_of(runs: list[RunFile], design: str, arm: str, seed: int) -> Path | None:
    for r in runs:
        if (r.design, r.arm, r.seed) == (design, arm, seed):
            return r.path
    return None


# ---------------------------------------------------------------- summaries


def atom_value(atom: Atom, key: str) -> str | float | None:
    """The atom's value for a colour key: text for categorical keys, a number or None."""
    if key == "construct":
        return atom.construct or None
    if key == "word":
        return atom.word
    if key == "inst":
        return atom.inst or None
    if key == "class":
        return atom.cls or None
    if key == "crit":
        return atom.crit
    if key == "pcrit":
        return atom.pcrit
    raise ValueError(f"unknown key '{key}'")


def clb_counts_by_type(atlas: Atlas) -> dict[str, int]:
    return dict(Counter(c.type for c in atlas.clbs))


def atoms_per_clb(atlas: Atlas) -> dict[str, float]:
    """min / mean / max atoms per CLB (zeros when there are no CLBs)."""
    sizes = [len(c.atoms) for c in atlas.clbs]
    if not sizes:
        return {"min": 0.0, "mean": 0.0, "max": 0.0}
    return {"min": float(min(sizes)), "mean": sum(sizes) / len(sizes), "max": float(max(sizes))}


def spread(atlas: Atlas, key: str) -> dict[str, int]:
    """For a categorical key: value -> number of distinct CLBs holding at least one such atom."""
    if key not in CATEGORICAL_KEYS:
        raise ValueError(f"'{key}' is not a categorical key")
    seen: dict[str, set[int]] = {}
    for c in atlas.clbs:
        for i in c.atoms:
            v = atom_value(atlas.atoms[i], key)
            if isinstance(v, str):
                seen.setdefault(v, set()).add(c.id)
    return {v: len(s) for v, s in seen.items()}


def class_shares(atlas: Atlas) -> dict[str, float]:
    """Share of the atoms carrying each N17 class (atoms with no class under NONE_LABEL)."""
    counts = Counter(a.cls or NONE_LABEL for a in atlas.atoms)
    total = sum(counts.values())
    return {k: v / total for k, v in sorted(counts.items())} if total else {}


def summary_text(atlas: Atlas) -> str:
    """A few lines for the status area."""
    types = ", ".join(f"{n} {t}" for t, n in sorted(clb_counts_by_type(atlas).items()))
    per = atoms_per_clb(atlas)
    shares = ", ".join(f"{k} {v:.0%}" for k, v in class_shares(atlas).items())
    cons, words = spread(atlas, "construct"), spread(atlas, "word")
    head = f"{atlas.design} {atlas.arm} seed {atlas.seed}: grid {atlas.grid[0]}x{atlas.grid[1]}"
    return (
        f"{head}, {len(atlas.atoms)} atoms in {types or 'no blocks'}; per CLB "
        f"{per['min']:.0f}/{per['mean']:.1f}/{per['max']:.0f} atoms (min/mean/max).\n"
        f"{len(cons)} constructs (mean spread {_mean(cons):.1f} CLBs), {len(words)} words "
        f"(mean spread {_mean(words):.1f} CLBs). Classes: {shares or 'none'}."
    )


def _mean(d: dict[str, int]) -> float:
    return sum(d.values()) / len(d) if d else 0.0


# ---------------------------------------------------------------- colour keys


def clb_category(atlas: Atlas, clb: Clb, key: str) -> str | None:
    """The most common value of a categorical key among the CLB's atoms (ties: the first
    alphabetically); None when no atom has a value."""
    counts = Counter(v for i in clb.atoms if isinstance(v := atom_value(atlas.atoms[i], key), str))
    if not counts:
        return None
    top = max(counts.values())
    return min(v for v, n in counts.items() if n == top)


def clb_number(atlas: Atlas, clb: Clb, key: str) -> float | None:
    """The largest value of a numeric key among the CLB's atoms; None when none has one."""
    vals = [v for i in clb.atoms if isinstance(v := atom_value(atlas.atoms[i], key), float)]
    return max(vals) if vals else None


PALETTE = (
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948",
    "#b07aa1", "#ff9da7", "#9c755f", "#17becf", "#8c564b", "#bcbd22",
)  # fmt: skip
EMPTY_COLOUR = "#d9d9d9"
UNLABELLED_COLOUR = "#9e9e9e"
BLOCK_COLOUR = "#c7c7e8"


def palette_colour(value: str, order: list[str]) -> str:
    """Stable colour of a category: its rank in `order` (values sorted by decreasing CLB spread)."""
    return PALETTE[order.index(value) % len(PALETTE)] if value in order else UNLABELLED_COLOUR


def ramp_colour(v: float) -> str:
    """Criticality 0..1 as light yellow to dark red."""
    t = min(1.0, max(0.0, v))
    r = round(255 - 75 * t)
    g = round(245 - 215 * t)
    b = round(200 - 170 * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def category_order(atlas: Atlas, key: str) -> list[str]:
    """Values of a categorical key by decreasing spread, then name."""
    sp = spread(atlas, key)
    return sorted(sp, key=lambda v: (-sp[v], v))


def clb_colours(atlas: Atlas, key: str) -> dict[int, str]:
    """CLB id -> fill colour for the key (categorical: dominant value; numeric: the maximum)."""
    if key not in KEYS:
        raise ValueError(f"unknown key '{key}'")
    out: dict[int, str] = {}
    order = category_order(atlas, key) if key in CATEGORICAL_KEYS else []
    for c in atlas.clbs:
        if not c.atoms:
            out[c.id] = EMPTY_COLOUR
        elif key in CATEGORICAL_KEYS:
            v = clb_category(atlas, c, key)
            out[c.id] = UNLABELLED_COLOUR if v is None else palette_colour(v, order)
        else:
            n = clb_number(atlas, c, key)
            out[c.id] = UNLABELLED_COLOUR if n is None else ramp_colour(n)
    return out


def clbs_with(atlas: Atlas, key: str, value: str) -> set[int]:
    """Ids of the CLBs holding at least one atom whose categorical `key` equals `value`."""
    return {
        c.id for c in atlas.clbs if any(atom_value(atlas.atoms[i], key) == value for i in c.atoms)
    }


# ---------------------------------------------------------------- hover


def _fmt(v: float | None) -> str:
    return "-" if v is None else f"{v:.3f}"


def atom_line(a: Atom) -> str:
    word = a.word if a.word is not None else "-"
    bit = "" if a.bit is None else f"[{a.bit}]"
    return (
        f"{a.name}  {a.kind} {a.cls or '-'}  word {word}{bit}  construct {a.construct or '-'}"
        f"  inst {a.inst or '-'}  crit {_fmt(a.crit)}  pcrit {_fmt(a.pcrit)}"
    )


def hover_text(atlas: Atlas, clb: Clb, limit: int = 12) -> str:
    """Text for the tooltip of a CLB: position, count and the first `limit` atoms with labels."""
    head = f"{clb.type} {clb.id} at ({clb.x}, {clb.y}): {len(clb.atoms)} atoms"
    lines = [atom_line(atlas.atoms[i]) for i in clb.atoms[:limit]]
    if len(clb.atoms) > limit:
        lines.append(f"... and {len(clb.atoms) - limit} more")
    return "\n".join([head, *lines])


# ---------------------------------------------------------------- difference


def moved_atoms(a: Atlas, b: Atlas) -> dict[str, tuple[tuple[int, int], tuple[int, int]]]:
    """Atoms (matched by name) held by a CLB in both runs at different coordinates:
    name -> (position in `a`, position in `b`). CLB ids differ between runs, so positions are
    compared."""
    pos_a = _atom_positions(a)
    pos_b = _atom_positions(b)
    return {n: (pos_a[n], p) for n, p in pos_b.items() if n in pos_a and pos_a[n] != p}


def _atom_positions(atlas: Atlas) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for c in atlas.clbs:
        for i in c.atoms:
            out.setdefault(atlas.atoms[i].name, (c.x, c.y))
    return out


def moved_share(atlas: Atlas, moved: set[str]) -> dict[int, float]:
    """CLB id -> share of its atoms whose name is in `moved` (CLBs with no atoms: 0)."""
    return {
        c.id: (sum(1 for i in c.atoms if atlas.atoms[i].name in moved) / len(c.atoms))
        if c.atoms
        else 0.0
        for c in atlas.clbs
    }


def diff_colours(atlas: Atlas, moved: set[str]) -> dict[int, str]:
    """Fill colours for difference mode: share of the CLB's atoms that were elsewhere before."""
    share = moved_share(atlas, moved)
    return {c.id: EMPTY_COLOUR if not c.atoms else ramp_colour(share[c.id]) for c in atlas.clbs}


def diff_summary(a: Atlas, b: Atlas) -> str:
    moved = moved_atoms(a, b)
    common = len(set(_atom_positions(a)) & set(_atom_positions(b)))
    pct = f"{len(moved) / common:.0%}" if common else "n/a"
    return (
        f"{a.arm} s{a.seed} -> {b.arm} s{b.seed}: {len(moved)} of {common} common atoms sit in a "
        f"different CLB ({pct})."
    )
