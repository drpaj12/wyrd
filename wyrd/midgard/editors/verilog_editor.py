"""The Verilog editor window (spec 8.1), a PySide6 port of VerilogEditor.

The behaviour (save, verify, simulate, reset, close) lives in `model/vedit.py`; this module only
draws it. It imports no pygame; the game starts it with `subprocess`.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRect, QRegularExpression, QSize, Qt
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QPixmap,
    QRegularExpressionValidator,
    QResizeEvent,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from wyrd.midgard.model import ASSETS
from wyrd.midgard.model.vedit import (
    EditorSession,
    VerifyResult,
    animation_image_names,
    load_template,
)

VEDIT = ASSETS / "editors" / "vedit"
_KEYWORD_TEXT = (
    "always assign begin case else endcase end for function if input integer module negedge "
    "output parameter posedge real reg task signed wire while endmodule"
)
KEYWORDS = frozenset(_KEYWORD_TEXT.split())
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"\b(?:\d+)?'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+|\b\d+\b")
# Light image positions and size on the 84 pixel animation of the original, as fractions.
_PANEL = 84.0
_LIGHT_POS = {"n": (61, 62), "s": (0, 0), "e": (0, 62), "w": (61, 0)}
_LIGHT_SIZE = 23
# Grid (column, row) of the eight sensor check boxes, index 0 to 7, as in the original.
_BOX_CELLS = ((1, 1), (2, 1), (1, 2), (2, 2), (1, 0), (0, 2), (2, 3), (3, 1))


def _icon(name: str) -> QIcon:
    return QIcon(str(VEDIT / f"{name}.png"))


def _format(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setForeground(QColor(color))
    if bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    fmt.setFontItalic(italic)
    return fmt


class KeywordHighlighter(QSyntaxHighlighter):
    """Keywords red and bold as in SyntaxHighlighter.java; comments and numbers added."""

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self.keyword = _format("#cc0000", bold=True)
        self.comment = _format("#2e7d32", italic=True)
        self.number = _format("#1a4fb0")

    def highlightBlock(self, text: str) -> None:
        for m in _NUMBER.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.number)
        for m in _WORD.finditer(text):
            if m.group() in KEYWORDS:
                self.setFormat(m.start(), m.end() - m.start(), self.keyword)
        self._comments(text)

    def _comments(self, text: str) -> None:
        in_block = self.previousBlockState() == 1
        pos = 0
        while pos < len(text):
            if in_block:
                end = text.find("*/", pos)
                stop = len(text) if end < 0 else end + 2
                self.setFormat(pos, stop - pos, self.comment)
                in_block = end < 0
                pos = stop
                continue
            line = text.find("//", pos)
            block = text.find("/*", pos)
            if line >= 0 and (block < 0 or line < block):
                self.setFormat(line, len(text) - line, self.comment)
                break
            if block < 0:
                break
            in_block = True
            pos = block
            self.setFormat(block, 2, self.comment)
            pos = block + 2
        self.setCurrentBlockState(1 if in_block else 0)


class LineNumberArea(QWidget):
    def __init__(self, editor: CodeEditor) -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event: QPaintEvent) -> None:
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """A monospace editor with a line-number gutter."""

    def __init__(self) -> None:
        super().__init__()
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(11)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.gutter = LineNumberArea(self)
        self.blockCountChanged.connect(self._update_margin)
        self.updateRequest.connect(self._scroll_gutter)
        self._update_margin()

    def gutter_width(self) -> int:
        digits = max(3, len(str(self.blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margin(self, _count: int = 0) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect: QRect, dy: int) -> None:
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_margin()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        area = self.contentsRect()
        self.gutter.setGeometry(QRect(area.left(), area.top(), self.gutter_width(), area.height()))

    def paint_gutter(self, event: QPaintEvent) -> None:
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor("#f0f0f0"))
        painter.setPen(QColor("#808080"))
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible():
                painter.drawText(
                    0,
                    top,
                    self.gutter.width() - 4,
                    height,
                    Qt.AlignmentFlag.AlignRight,
                    str(block.blockNumber() + 1),
                )
            block = block.next()
            top += height
        painter.end()


class AnimationPanel(QWidget):
    """The intersection picture: eight sensor check boxes and the four lights of the last step."""

    def __init__(self) -> None:
        super().__init__()
        self.last_out: tuple[int, int, int, int] | None = None
        self._background = QPixmap(str(VEDIT / "animationImage.png"))
        self._lights: dict[str, QPixmap] = {}
        self.setMinimumSize(128, 128)
        grid = QGridLayout(self)
        self.boxes: list[QCheckBox] = []
        for col, row in _BOX_CELLS:
            box = QCheckBox()
            self.boxes.append(box)
            grid.addWidget(box, row, col)

    def internal_signal(self) -> str:
        return "".join("1" if self.boxes[i].isChecked() else "0" for i in range(7, -1, -1))

    def set_states(self, bits: str) -> None:
        for i, ch in enumerate(bits):
            self.boxes[7 - i].setChecked(ch == "1")

    def set_output(self, out: tuple[int, int, int, int] | None) -> None:
        self.last_out = out
        self.update()

    def _light(self, name: str) -> QPixmap:
        if name not in self._lights:
            self._lights[name] = QPixmap(str(VEDIT / f"{name}.png"))
        return self._lights[name]

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._background)
        if self.last_out is not None:
            sx, sy = self.width() / _PANEL, self.height() / _PANEL
            for name in animation_image_names(self.last_out):
                px, py = _LIGHT_POS[name[-1]]
                target = QRect(
                    round(px * sx), round(py * sy), round(_LIGHT_SIZE * sx), round(_LIGHT_SIZE * sy)
                )
                painter.drawPixmap(target, self._light(name))
        painter.end()


class SearchReplaceDialog(QDialog):
    """Search and Replace after SearchAndReplaceDialog.java."""

    def __init__(self, parent: QWidget | None, code: QPlainTextEdit) -> None:
        super().__init__(parent)
        self.code = code
        self.setWindowTitle("Search and Replace")
        self.find_edit = QLineEdit()
        self.replace_edit = QLineEdit()
        self.case_box = QCheckBox("case sensitive")
        layout = QGridLayout(self)
        layout.addWidget(QLabel("Search: "), 0, 0)
        layout.addWidget(self.find_edit, 0, 1, 1, 4)
        layout.addWidget(self.case_box, 0, 5)
        layout.addWidget(QLabel("Replace: "), 1, 0)
        layout.addWidget(self.replace_edit, 1, 1, 1, 4)
        buttons: list[tuple[str, Callable[[], object]]] = [
            ("Search", self.search_from_start),
            ("Replace", self.replace_current),
            ("Replace && Search", self.replace_and_search),
            ("Next", self.find_next),
            ("Replace All", self.replace_all),
        ]
        for col, (label, action) in enumerate(buttons):
            button = QPushButton(label)
            button.clicked.connect(action)
            layout.addWidget(button, 2, col)
        self.find_edit.returnPressed.connect(self.find_next)

    def _flags(self) -> QTextDocument.FindFlag:
        if self.case_box.isChecked():
            return QTextDocument.FindFlag.FindCaseSensitively
        return QTextDocument.FindFlag(0)

    def find_next(self) -> bool:
        target = self.find_edit.text()
        if not target:
            return False
        if self.code.find(target, self._flags()):
            return True
        cursor = self.code.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.code.setTextCursor(cursor)
        return self.code.find(target, self._flags())

    def search_from_start(self) -> bool:
        cursor = self.code.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.code.setTextCursor(cursor)
        return self.find_next()

    def replace_current(self) -> bool:
        cursor = self.code.textCursor()
        if not cursor.hasSelection():
            return False
        cursor.insertText(self.replace_edit.text())
        return True

    def replace_and_search(self) -> bool:
        self.replace_current()
        return self.find_next()

    def replace_all(self) -> int:
        target = self.find_edit.text()
        if not target:
            return 0
        text = self.code.toPlainText()
        flags = 0 if self.case_box.isChecked() else re.IGNORECASE
        new, count = re.subn(
            re.escape(target), lambda _m: self.replace_edit.text(), text, flags=flags
        )
        if count:
            self.code.setPlainText(new)
        return count


class ActionMap(dict[str, QAction]):
    """Named actions; calling it still gives QWidget.actions() (the attribute shadows it)."""

    def __init__(self, owner: QWidget) -> None:
        super().__init__()
        self._owner = owner

    def __call__(self) -> list[QAction]:
        return QWidget.actions(self._owner)


class VerilogEditorWindow(QMainWindow):
    def __init__(self, session: EditorSession, title: str = "Verilog Editor") -> None:
        super().__init__()
        self.session = session
        self.setWindowTitle(title)
        self.code = CodeEditor()
        self.highlighter = KeywordHighlighter(self.code.document())
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.sensor_edit = QLineEdit("0" * 8)
        self.sensor_edit.setValidator(QRegularExpressionValidator(QRegularExpression("[01]{0,8}")))
        self.general_edit = QLineEdit("0" * 30)
        self.general_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[01]{0,30}"))
        )
        self.animation = AnimationPanel()
        self.actions: ActionMap = ActionMap(self)
        self._build_layout()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.code.setPlainText(session.text)
        self.code.textChanged.connect(self._text_changed)
        self.sensor_edit.textChanged.connect(self._sensor_text_changed)
        for box in self.animation.boxes:
            box.toggled.connect(self._box_toggled)
        self.resize(1000, 700)

    def _build_layout(self) -> None:
        lower = QWidget()
        row = QHBoxLayout(lower)
        log = QVBoxLayout()
        log.addWidget(QLabel("Error log"))
        log.addWidget(self.messages)
        row.addLayout(log, 1)
        row.addWidget(self.animation)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.code)
        split.addWidget(lower)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)

    def _add(self, key: str, text: str, shortcut: str, slot: Callable[[], object]) -> None:
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if (VEDIT / f"{key}.png").is_file():
            action.setIcon(_icon(key))
        action.triggered.connect(slot)
        self.addAction(action)
        self.actions[key] = action

    def _build_actions(self) -> None:
        self._add("save", "Save", "Ctrl+S", self.do_save)
        self._add("verify", "Verify", "Ctrl+R", self.do_verify)
        self._add("exit", "Exit", "Ctrl+E", self.close)
        self._add("undo", "Undo", "Ctrl+Z", self.code.undo)
        self._add("redo", "Redo", "Ctrl+Y", self.code.redo)
        self._add("search", "Search and Replace", "Ctrl+F", self.do_search)
        self._add("simulate", "Simulate", "Ctrl+M", self.do_simulate)
        self._add("reset", "Reset Simulation", "", self.do_reset)
        self._add("combinational", "Combinational", "Ctrl+1", self.use_combinational)
        self._add("sequential", "Sequential", "Ctrl+2", self.use_sequential)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        assert bar is not None
        layout = (
            ("File", ("verify", "-", "save", "-", "exit")),
            ("Edit", ("undo", "redo", "search")),
            ("Simulation", ("simulate", "reset")),
            ("Template", ("combinational", "sequential")),
        )
        for title, keys in layout:
            menu = bar.addMenu(title)
            assert menu is not None
            for key in keys:
                if key == "-":
                    menu.addSeparator()
                else:
                    menu.addAction(self.actions[key])

    def _build_toolbar(self) -> None:
        bar = QToolBar("tools")
        bar.setMovable(False)
        for key in ("save", "verify", "undo", "redo", "search", "simulate", "reset"):
            action = self.actions[key]
            action.setToolTip(action.text())
            bar.addAction(action)
        bar.addWidget(QLabel("Internal Sensors:"))
        bar.addWidget(self.sensor_edit)
        bar.addWidget(QLabel("General Sensors:"))
        bar.addWidget(self.general_edit)
        self.addToolBar(bar)

    # signals

    def _text_changed(self) -> None:
        self.session.set_text(self.code.toPlainText())

    def _sensor_text_changed(self, text: str) -> None:
        if len(text) == 8 and text != self.animation.internal_signal():
            self.animation.set_states(text)

    def _box_toggled(self, _checked: bool) -> None:
        self.sensor_edit.setText(self.animation.internal_signal())

    # actions

    def show_messages(self, *lines: str) -> None:
        self.messages.setPlainText("\n".join(lines))

    def do_save(self) -> None:
        self.show_messages(self.session.save())

    def do_verify(self) -> None:
        result = self.session.verify()
        self.show_messages(*result.messages)
        self.animation.set_output(None)

    def do_reset(self) -> None:
        self.show_messages(self.session.reset())
        self.animation.set_output(None)

    def do_simulate(self) -> None:
        result, text = self.session.simulate(self.sensor_edit.text(), self.general_edit.text())
        self.show_messages(text)
        if result is not None:
            self.animation.set_output(result.out)

    def do_search(self) -> None:
        SearchReplaceDialog(self, self.code).exec()

    def use_template(self, name: str) -> None:
        self.code.setPlainText(load_template(name))

    def use_combinational(self) -> None:
        self.use_template("combinational")

    def use_sequential(self) -> None:
        self.use_template("sequential")

    def _exit_check(self, prompt: bool) -> VerifyResult:
        """The compile shown on exit; any failure becomes a message, so the window still closes."""
        try:
            return self.session.check_unsaved() if prompt else self.session.verify()
        except Exception as exc:  # a backend or file error must not keep the window open
            return VerifyResult(False, (f"Error: {exc}",))

    def closeEvent(self, event: QCloseEvent) -> None:
        prompt = self.session.should_prompt_on_exit()
        self.show_messages(*self._exit_check(prompt).messages)
        if not prompt:
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            "Save this file?",
            "Content changed.\nDo you want to save this file?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.StandardButton.Yes:
            self.session.save()
        event.accept()


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m wyrd.midgard.editors.verilog_editor",
        description="Midgard III Verilog editor window.",
    )
    p.add_argument("--file", required=True, help="the Verilog file to edit")
    p.add_argument("--level", type=int, default=0, help="level number, for the window title")
    p.add_argument("--name", default="", help="file name shown in the window title")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    path = Path(args.file)
    session = EditorSession(path)
    window = VerilogEditorWindow(session, f"{args.name or path.stem} - Level {args.level}")
    window.show()
    code = app.exec()
    session.close()
    return int(code)


if __name__ == "__main__":
    sys.exit(main())
