"""Coloured ranges of one source file from in-scope facts, and the hot/cold colour map. Qt-free.

Columns are derived by whole-token name match of the attributed word on the line (provenance spans
are line-level). A bus word is split into one segment per bit, MSB first by default.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from wyrd.guimodel.heat import Fact, HeatModel
from wyrd.guimodel.verilog_lex import tokenize_line

# ColorBrewer RdYlBu (diverging, colour-blind safe): crit 0 blue ... 1 red.
STOPS: tuple[tuple[float, tuple[int, int, int]], ...] = (
    (0.0, (0x2C, 0x7B, 0xB6)),
    (0.25, (0xAB, 0xD9, 0xE9)),
    (0.5, (0xFF, 0xFF, 0xBF)),
    (0.75, (0xFD, 0xAE, 0x61)),
    (1.0, (0xD7, 0x19, 0x1C)),
)
DECL_KEYWORDS = r"input|output|inout|wire|reg|logic"
LEGEND_NOTE = "Token columns are derived by name match; bits are shown MSB first."


def crit_rgb(crit: float) -> tuple[int, int, int]:
    c = min(max(crit, 0.0), 1.0)
    for (x0, a), (x1, b) in zip(STOPS, STOPS[1:], strict=False):
        if c <= x1:
            t = (c - x0) / (x1 - x0)
            return (
                round(a[0] + (b[0] - a[0]) * t),
                round(a[1] + (b[1] - a[1]) * t),
                round(a[2] + (b[2] - a[2]) * t),
            )
    return STOPS[-1][1]


def crit_hex(crit: float) -> str:
    r, g, b = crit_rgb(crit)
    return f"#{r:02x}{g:02x}{b:02x}"


def text_is_dark(rgb: tuple[int, int, int]) -> bool:
    """True when black text reads better on ``rgb``."""
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2] > 140


@dataclass(frozen=True)
class BitSeg:
    bit: int
    col_start: int
    col_end: int
    crit: float


@dataclass(frozen=True)
class HeatRange:
    line: int
    col_start: int
    col_end: int
    word: str
    crit: float
    segments: tuple[BitSeg, ...] = ()
    strip: tuple[tuple[int, float], ...] = ()
    unknown_bits: bool = False
    paths: tuple[int, ...] = ()
    tooltip: str = ""


@dataclass
class FileHeat:
    lines: dict[int, float] = field(default_factory=dict)
    ranges: list[HeatRange] = field(default_factory=list)
    line_paths: dict[int, tuple[int, ...]] = field(default_factory=dict)
    unplaced: list[str] = field(default_factory=list)

    def range_at(self, line: int, col: int) -> HeatRange | None:
        for r in self.ranges:
            if r.line == line and r.col_start <= col < r.col_end:
                return r
        return None


def _code_mask(text: str) -> list[list[bool]]:
    """Per line, per column: True where the character is code (not a comment or string)."""
    out: list[list[bool]] = []
    in_comment = False
    for line in text.split("\n"):
        mask = [True] * len(line)
        spans, in_comment = tokenize_line(line, in_comment)
        for s in spans:
            if s.kind in ("comment", "string"):
                for i in range(s.start, min(s.start + s.length, len(line))):
                    mask[i] = False
        out.append(mask)
    return out


def _token_re(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w$]){re.escape(word)}(?![\w$])")


def _matches(word: str, line: str, mask: list[bool]) -> list[tuple[int, int]]:
    return [m.span() for m in _token_re(word).finditer(line) if mask[m.start()]]


def declaration_line(word: str, lines: Sequence[str]) -> int | None:
    """1-based first line where ``word`` is declared (after input/output/inout/wire/reg/logic)."""
    kw = re.compile(rf"\b(?:{DECL_KEYWORDS})\b")
    tok = _token_re(word)
    for i, line in enumerate(lines, 1):
        k = kw.search(line)
        m = tok.search(line, k.end()) if k else None
        if m:
            return i
    return None


def declared_range(word: str, lines: Sequence[str]) -> tuple[int, int] | None:
    """(hi, lo) of a literal ``[hi:lo]`` before ``word`` in its declaration, else None."""
    stop = rf"(?:(?!\b(?:{DECL_KEYWORDS})\b)[^;\n])*?"
    pat = re.compile(
        rf"\b(?:{DECL_KEYWORDS})\b{stop}\[\s*(\d+)\s*:\s*(\d+)\s*\]{stop}(?<![\w$]){re.escape(word)}(?![\w$])"
    )
    for line in lines:
        m = pat.search(line)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None


def bit_order(width: tuple[int, int] | None, seen: int, msb_first: bool) -> list[int]:
    """Bit indices in display order; empty when the width is unknown or 1."""
    if width is not None:
        hi, lo = width
        order = list(range(hi, lo - 1, -1)) if hi >= lo else list(range(hi, lo + 1))
    else:
        order = list(range(seen - 1, -1, -1))
    if len(order) < 2:
        return []
    return order if msb_first else order[::-1]


def segment_sizes(length: int, n: int) -> list[int]:
    base, extra = divmod(length, n)
    return [base + 1 if i < extra else base for i in range(n)]


def _make_segments(
    start: int, length: int, order: list[int], bits: dict[int, float]
) -> tuple[BitSeg, ...]:
    out: list[BitSeg] = []
    pos = start
    for bit, size in zip(order, segment_sizes(length, len(order)), strict=True):
        out.append(BitSeg(bit, pos, pos + size, bits.get(bit, 0.0)))
        pos += size
    return tuple(out)


def _tooltip(
    word: str, crit: float, order: list[int], bits: dict[int, float], unknown: bool, npaths: int
) -> str:
    parts = [f"{word}: crit {crit:.3f}, {npaths} path(s)"]
    if order:
        parts.append("bits: " + ", ".join(f"[{b}] {bits.get(b, 0.0):.3f}" for b in order))
    if unknown:
        parts.append("bit unknown")
    return "\n".join(parts)


def _range(
    line: int,
    span: tuple[int, int],
    word: str,
    facts: Sequence[Fact],
    order_args: tuple[tuple[int, int] | None, int, bool],
) -> HeatRange:
    width, seen, msb_first = order_args
    bits: dict[int, float] = {}
    for f in facts:
        if f.bit_known and f.bit is not None:
            bits[f.bit] = max(bits.get(f.bit, 0.0), f.crit)
    crit = max(f.crit for f in facts)
    order = bit_order(width, max(seen, max(bits) + 1 if bits else 0), msb_first) if bits else []
    unknown = not bits
    start, end = span
    segments: tuple[BitSeg, ...] = ()
    strip: tuple[tuple[int, float], ...] = ()
    if order and len(order) <= end - start:
        segments = _make_segments(start, end - start, order, bits)
    elif order:
        strip = tuple((b, bits.get(b, 0.0)) for b in order)
    paths = tuple(sorted({f.path for f in facts if f.path >= 0}))
    tip = _tooltip(word, crit, order, bits, unknown, len(paths))
    return HeatRange(line, start, end, word, crit, segments, strip, unknown, paths, tip)


def _facts_ok(model: HeatModel, f: Fact, names: set[str]) -> bool:
    if f.file is not None:
        return f.file in names
    known = model.module_files.get(f.module)
    return known is None or bool(known & names)


def build_file_heat(
    model: HeatModel,
    facts: Iterable[Fact],
    names: set[str],
    text: str,
    msb_first: bool = True,
) -> FileHeat:
    """Colour data for one file. ``names`` are the attribution names that resolve to it."""
    mine = [f for f in facts if _facts_ok(model, f, names)]
    lines = text.split("\n")
    mask = _code_mask(text)
    heat = FileHeat()
    _line_tints(heat, mine)
    all_words: dict[tuple[str, str], list[Fact]] = {}
    at_line: dict[tuple[int, str, str], list[Fact]] = {}
    for f in mine:
        if not f.word:
            continue
        all_words.setdefault((f.module, f.word), []).append(f)
        if f.line is not None:
            at_line.setdefault((f.line, f.module, f.word), []).append(f)

    def args(module: str, word: str) -> tuple[tuple[int, int] | None, int, bool]:
        return declared_range(word, lines), model.seen_width.get((module, word), 0), msb_first

    for (line, module, word), group in sorted(at_line.items()):
        if not 1 <= line <= len(lines):
            continue
        for span in _matches(word, lines[line - 1], mask[line - 1]):
            heat.ranges.append(_range(line, span, word, group, args(module, word)))
    for (module, word), group in sorted(all_words.items()):
        unlined = [f for f in group if f.line is None]
        if unlined:
            _place_declaration(heat, model, lines, mask, module, word, group, args(module, word))
    heat.ranges.sort(key=lambda r: (r.line, r.col_start))
    return heat


def _line_tints(heat: FileHeat, facts: Sequence[Fact]) -> None:
    paths: dict[int, set[int]] = {}
    for f in facts:
        if f.line is None:
            continue
        heat.lines[f.line] = max(heat.lines.get(f.line, 0.0), f.crit)
        if f.path >= 0:
            paths.setdefault(f.line, set()).add(f.path)
    heat.line_paths = {k: tuple(sorted(v)) for k, v in paths.items()}


def _place_declaration(
    heat: FileHeat,
    model: HeatModel,
    lines: Sequence[str],
    mask: list[list[bool]],
    module: str,
    word: str,
    group: Sequence[Fact],
    order_args: tuple[tuple[int, int] | None, int, bool],
) -> None:
    line = declaration_line(word, lines)
    spans = _matches(word, lines[line - 1], mask[line - 1]) if line else []
    kw = re.compile(rf"\b(?:{DECL_KEYWORDS})\b")
    if line and spans:
        k = kw.search(lines[line - 1])
        after = [s for s in spans if k is not None and s[0] >= k.end()]
        span = after[0] if after else spans[0]
        heat.ranges = [r for r in heat.ranges if (r.line, r.col_start) != (line, span[0])]
        heat.ranges.append(_range(line, span, word, group, order_args))
    else:
        heat.unplaced.append(f"{module}.{word}" if module else word)
