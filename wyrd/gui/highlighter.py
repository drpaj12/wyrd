"""Verilog syntax highlighting over the Qt-free tokenizer."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from wyrd.guimodel.verilog_lex import tokenize_line

_COLORS = {
    "keyword": "#0000c0",
    "comment": "#707070",
    "string": "#a31515",
    "number": "#098658",
    "directive": "#8000a0",
    "system": "#008080",
}


def _formats() -> dict[str, QTextCharFormat]:
    out: dict[str, QTextCharFormat] = {}
    for kind, color in _COLORS.items():
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        if kind == "keyword":
            fmt.setFontWeight(QFont.Weight.Bold)
        out[kind] = fmt
    return out


class VerilogHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._formats = _formats()

    def highlightBlock(self, text: str) -> None:
        spans, in_comment = tokenize_line(text, self.previousBlockState() == 1)
        for span in spans:
            fmt = self._formats.get(span.kind)
            if fmt is not None:
                self.setFormat(span.start, span.length, fmt)
        self.setCurrentBlockState(1 if in_comment else 0)
