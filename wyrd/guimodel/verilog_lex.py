"""A line-based Verilog tokenizer for syntax highlighting (no Qt)."""

from __future__ import annotations

from dataclasses import dataclass

_IEEE_1364_2005 = """
always and assign automatic begin buf bufif0 bufif1 case casex casez cell cmos config
deassign default defparam design disable edge else end endcase endconfig endfunction
endgenerate endmodule endprimitive endspecify endtable endtask event for force forever fork
function generate genvar highz0 highz1 if ifnone incdir include initial inout input instance
integer join large liblist library localparam macromodule medium module nand negedge nmos nor
noshowcancelled not notif0 notif1 or output parameter pmos posedge primitive pull0 pull1
pulldown pullup pulsestyle_onevent pulsestyle_ondetect rcmos real realtime reg release repeat
rnmos rpmos rtran rtranif0 rtranif1 scalared showcancelled signed small specify specparam
strong0 strong1 supply0 supply1 table task time tran tranif0 tranif1 tri tri0 tri1 triand
trior trireg unsigned use uwire vectored wait wand weak0 weak1 while wire wor xnor xor
"""
_SYSTEMVERILOG = """
logic bit byte int always_comb always_ff always_latch interface endinterface package
endpackage typedef enum struct union return break continue
"""
KEYWORDS: frozenset[str] = frozenset((_IEEE_1364_2005 + _SYSTEMVERILOG).split())

_IDENT_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_BODY = _IDENT_START | frozenset("0123456789$")
_DIGITS = frozenset("0123456789")
_BASES = frozenset("bBoOdDhH")
_BASE_DIGITS = frozenset("0123456789abcdefABCDEFxXzZ_?")


@dataclass(frozen=True)
class Span:
    start: int
    length: int
    kind: str


def _run(line: str, pos: int, allowed: frozenset[str]) -> int:
    """Index of the first character at or after ``pos`` that is not in ``allowed``."""
    while pos < len(line) and line[pos] in allowed:
        pos += 1
    return pos


def _comment_tail(line: str, pos: int) -> tuple[Span, bool]:
    """A block comment continuing at ``pos``; the flag says it is still open at line end."""
    end = line.find("*/", pos)
    if end < 0:
        return Span(pos, len(line) - pos, "comment"), True
    return Span(pos, end + 2 - pos, "comment"), False


def _string(line: str, pos: int) -> int:
    """End index (exclusive) of the string literal starting at ``pos``."""
    i = pos + 1
    while i < len(line):
        if line[i] == "\\":
            i += 2
        elif line[i] == '"':
            return i + 1
        else:
            i += 1
    return len(line)


def _based(line: str, pos: int) -> int | None:
    """End of a based literal whose apostrophe is at ``pos``, else None."""
    i = pos + 1
    if i < len(line) and line[i] in "sS":
        i += 1
    if i < len(line) and line[i] in _BASES:
        return _run(line, i + 1, _BASE_DIGITS)
    return None


def _exponent(line: str, pos: int) -> int:
    if pos < len(line) and line[pos] in "eE":
        i = pos + 1
        if i < len(line) and line[i] in "+-":
            i += 1
        if i < len(line) and line[i] in _DIGITS:
            return _run(line, i, _DIGITS)
    return pos


def _number(line: str, pos: int) -> int:
    """End of the number starting with a digit at ``pos``."""
    end = _run(line, pos, _DIGITS | {"_"})
    if end < len(line) and line[end] == "'":
        based = _based(line, end)
        return end if based is None else based
    if end + 1 < len(line) and line[end] == "." and line[end + 1] in _DIGITS:
        end = _run(line, end + 1, _DIGITS | {"_"})
    return _exponent(line, end)


def _word(line: str, pos: int) -> Span | None:
    """A keyword span for the identifier at ``pos``; None for a plain identifier."""
    end = _run(line, pos, _IDENT_BODY)
    word = line[pos:end]
    return Span(pos, end - pos, "keyword") if word in KEYWORDS else None


def _scan_one(line: str, i: int) -> tuple[Span | None, int, bool]:
    """Scan the token at ``i``: (span or None, next index, opens a block comment)."""
    c = line[i]
    if c == "/" and line.startswith("//", i):
        return Span(i, len(line) - i, "comment"), len(line), False
    if c == "/" and line.startswith("/*", i):
        tail, still = _comment_tail(line, i + 2)
        end = tail.start + tail.length
        return Span(i, end - i, "comment"), end, still
    if c == '"':
        end = _string(line, i)
        return Span(i, end - i, "string"), end, False
    if c in "`$":
        end = _run(line, i + 1, _IDENT_BODY)
        kind = "directive" if c == "`" else "system"
        return (Span(i, end - i, kind) if end > i + 1 else None), max(end, i + 1), False
    if c in _DIGITS:
        end = _number(line, i)
        return Span(i, end - i, "number"), end, False
    if c == "'":
        based = _based(line, i)
        if based is not None:
            return Span(i, based - i, "number"), based, False
    if c in _IDENT_START:
        end = _run(line, i, _IDENT_BODY)
        return _word(line, i), end, False
    return None, i + 1, False


def tokenize_line(line: str, in_comment: bool) -> tuple[list[Span], bool]:
    """Highlight spans of one line; the flag says a ``/* */`` comment is still open."""
    spans: list[Span] = []
    i = 0
    if in_comment:
        head, in_comment = _comment_tail(line, 0)
        spans.append(head)
        i = head.length
    while i < len(line):
        span, i, in_comment = _scan_one(line, i)
        if span is not None:
            spans.append(span)
        if in_comment:
            break
    return spans, in_comment
