"""Midgard III editors: launch argv (Qt-free) and the Verilog editor window (Qt offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fakes_midgard import FakeLightBackend
from wyrd.midgard.model.vedit import EditorSession, load_template
from wyrd.midgard.model.watch import editor_launch_argv

HAVE_QT = importlib.util.find_spec("PySide6") is not None
GOOD = "module light1;"

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    from wyrd.midgard.editors import verilog_editor as ve

    _APP: QCoreApplication | None = None

    def setUpModule() -> None:
        global _APP
        _APP = QApplication.instance() or QApplication([])


class LaunchArgvTest(unittest.TestCase):
    def test_editor_launch_argv(self) -> None:
        self.assertEqual(
            editor_launch_argv(Path("/p/a.v"), 3, "Traffic_signal_set_1", "/py"),
            [
                "/py",
                "-m",
                "wyrd.midgard.editors.verilog_editor",
                "--file",
                "/p/a.v",
                "--level",
                "3",
                "--name",
                "Traffic_signal_set_1",
            ],
        )


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class VerilogWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "a.v"
        self.path.write_text(GOOD + "\n", encoding="utf-8")
        self.backend = FakeLightBackend()

    def window(self) -> "ve.VerilogEditorWindow":
        session = EditorSession(self.path, self.backend)
        win = ve.VerilogEditorWindow(session, title="Traffic_signal_set_0 - Level 1")
        self.addCleanup(self._quiet_close, win)
        self.addCleanup(session.close)
        return win

    @staticmethod
    def _quiet_close(win: "ve.VerilogEditorWindow") -> None:
        win.session.dirty = False
        win.close()
        win.deleteLater()

    def test_window_wiring(self) -> None:
        w = self.window()
        self.assertEqual(w.windowTitle(), "Traffic_signal_set_0 - Level 1")
        self.assertFalse(w.session.dirty)
        w.code.setPlainText("x")
        self.assertTrue(w.session.dirty)
        w.code.setPlainText(GOOD)
        w.actions["save"].trigger()
        self.assertIn("Saving complete.", w.messages.toPlainText())
        w.actions["verify"].trigger()
        self.assertIn("Compile successful", w.messages.toPlainText())
        w.sensor_edit.setText("01000000")
        w.actions["simulate"].trigger()
        self.assertIn("OutN Val = 4", w.messages.toPlainText())
        self.assertEqual(w.animation.last_out, (4, 0, 0, 0))
        w.sensor_edit.setText("0100000")
        w.actions["simulate"].trigger()
        self.assertIn("Simulation cycle not sucessful", w.messages.toPlainText())
        self.assertEqual(w.general_edit.text(), "0" * 30)

    def test_shortcuts_and_menus(self) -> None:
        w = self.window()
        keys = {
            "save": "Ctrl+S",
            "verify": "Ctrl+R",
            "exit": "Ctrl+E",
            "undo": "Ctrl+Z",
            "redo": "Ctrl+Y",
            "search": "Ctrl+F",
            "simulate": "Ctrl+M",
            "reset": "",
            "combinational": "Ctrl+1",
            "sequential": "Ctrl+2",
        }
        self.assertEqual(set(w.actions), set(keys))
        for name, key in keys.items():
            self.assertEqual(w.actions[name].shortcut().toString(), key, name)
        bar = w.menuBar()
        assert bar is not None
        self.assertEqual(
            [a.text() for a in bar.actions()], ["File", "Edit", "Simulate", "Template"]
        )

    def test_sensor_checkboxes_follow_field(self) -> None:
        w = self.window()
        w.sensor_edit.setText("01000001")
        self.assertEqual(w.animation.internal_signal(), "01000001")
        w.animation.boxes[3].setChecked(True)
        self.assertEqual(w.sensor_edit.text(), "01001001")

    def test_templates_and_search(self) -> None:
        w = self.window()
        w.actions["sequential"].trigger()
        self.assertEqual(w.code.toPlainText(), load_template("sequential"))
        w.actions["combinational"].trigger()
        self.assertEqual(w.code.toPlainText(), load_template("combinational"))
        w.code.setPlainText("Go a Go b Go")
        dlg = ve.SearchReplaceDialog(w, w.code)
        dlg.find_edit.setText("Go")
        dlg.replace_edit.setText("GO")
        self.assertEqual(dlg.replace_all(), 3)
        self.assertEqual(w.code.toPlainText(), "GO a GO b GO")
        self.assertTrue(dlg.find_next())
        self.assertEqual(w.code.textCursor().selectedText(), "GO")
        dlg.case_box.setChecked(True)
        dlg.find_edit.setText("go")
        self.assertFalse(dlg.find_next())

    def test_highlighter_marks_keywords(self) -> None:
        w = self.window()
        w.code.setPlainText("module x; // module\nendmodule")
        layout = w.code.document().firstBlock().layout()
        assert layout is not None
        spans = [(f.start, f.length) for f in layout.formats()]
        self.assertIn((0, 6), spans)
        self.assertIn((10, 9), spans)

    def test_close_flow(self) -> None:
        old = self.path.read_text(encoding="utf-8")
        w = self.window()
        w.code.setPlainText("new text")
        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel
        ) as q:
            self.assertFalse(w.close())
        q.assert_called_once()
        self.assertEqual(self.path.read_text(encoding="utf-8"), old)
        self.assertIn("Compiling", w.messages.toPlainText())
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.assertTrue(w.close())
        self.assertEqual(self.path.read_text(encoding="utf-8"), old)

    def test_close_yes_saves_and_clean_does_not_ask(self) -> None:
        w = self.window()
        w.code.setPlainText("saved text")
        with mock.patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.assertTrue(w.close())
        self.assertEqual(self.path.read_text(encoding="utf-8"), "saved text\n")
        w2 = self.window()
        with mock.patch.object(QMessageBox, "question", side_effect=AssertionError("asked")):
            self.assertTrue(w2.close())
        self.assertIn("Compiling", w2.messages.toPlainText())

    def test_main_args(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            ve.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
