"""Midgard III editors: launch argv (Qt-free) and the Verilog editor window (Qt offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import gc
import importlib.util
import shutil
import tempfile
import unittest
import weakref
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from tests.fakes_midgard import FakeLightBackend
from tests.test_midgard_level import run_until_done
from wyrd.midgard.model.level import Level
from wyrd.midgard.model.leveldoc import LevelDoc
from wyrd.midgard.model.levelxml import level_path, parse_level_file
from wyrd.midgard.model.sensors import SensorSet
from wyrd.midgard.model.townmap import TownMap
from wyrd.midgard.model.vedit import EditorSession, load_template
from wyrd.midgard.model.watch import editor_launch_argv

HAVE_QT = importlib.util.find_spec("PySide6") is not None
GOOD = "module light1;"

if HAVE_QT:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox, QWidget

    from tests.qt_helpers import dispose, qapp
    from wyrd.midgard.editors import level_editor as le
    from wyrd.midgard.editors import verilog_editor as ve

    def setUpModule() -> None:
        qapp()


def assert_freed(case: unittest.TestCase, make: "Callable[[], QWidget]") -> None:
    """A dropped window is deleted at once; a lambda holding it in a connection would leak it."""
    ref = weakref.ref(make())
    gc.collect()
    case.assertIsNone(ref())


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
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dispose(win)

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
            [a.text() for a in bar.actions()], ["File", "Edit", "Simulation", "Template"]
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

    def test_close_survives_unexpected_errors(self) -> None:
        w = self.window()
        with mock.patch.object(w.session, "verify", side_effect=RuntimeError("backend died")):
            self.assertTrue(w.close())
        self.assertIn("Error: backend died", w.messages.toPlainText())
        w2 = self.window()
        w2.code.setPlainText("changed")
        with (
            mock.patch.object(w2.session, "check_unsaved", side_effect=OSError("disk")),
            mock.patch.object(
                QMessageBox, "question", return_value=QMessageBox.StandardButton.No
            ) as q,
        ):
            self.assertTrue(w2.close())
        q.assert_called_once()
        self.assertIn("Error: disk", w2.messages.toPlainText())

    def test_dirty_follows_the_file(self) -> None:
        w = self.window()
        w.code.setPlainText("x")
        self.assertTrue(w.session.dirty)
        w.code.setPlainText(GOOD)
        self.assertFalse(w.session.dirty)

    def test_windows_are_freed(self) -> None:
        session = EditorSession(self.path, self.backend)
        self.addCleanup(session.close)
        assert_freed(self, lambda: ve.VerilogEditorWindow(session))
        assert_freed(self, lambda: ve.SearchReplaceDialog(None, ve.CodeEditor()))

    def test_main_args(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            ve.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class StartDialogTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def dialog(self) -> "le.StartDialog":
        dlg = le.StartDialog()
        self.addCleanup(dispose, dlg)
        return dlg

    def run_result(self, dlg: "le.StartDialog") -> tuple[object, list[str]]:
        titles: list[str] = []

        def critical(_parent: object, title: str, text: str) -> None:
            titles.append(title)

        with mock.patch.object(QMessageBox, "critical", side_effect=critical):
            return dlg.check(), titles

    def test_start_dialog_validation(self) -> None:
        dlg = self.dialog()
        self.assertEqual(dlg.x_edit.text(), "20")
        self.assertEqual(dlg.y_edit.text(), "20")
        result, titles = self.run_result(dlg)
        self.assertIsNone(result)
        self.assertEqual(titles, ["Empty text field(s)"])
        dlg.level_edit.setText("5")
        dlg.x_edit.setText("21")
        result, titles = self.run_result(dlg)
        self.assertIsNone(result)
        self.assertEqual(titles, ["Invalid map size"])
        dlg.x_edit.setText("")
        result, titles = self.run_result(dlg)
        self.assertEqual(titles, ["Empty text field(s)"])
        dlg.x_edit.setText("2")
        result, titles = self.run_result(dlg)
        self.assertEqual(titles, ["Invalid map size"])
        dlg.x_edit.setText("20")
        result, titles = self.run_result(dlg)
        self.assertEqual(result, le.StartResult(False, 5, 20, 20, None))
        self.assertEqual(titles, [])

    def test_update_mode(self) -> None:
        dlg = self.dialog()
        dlg.update_radio.setChecked(True)
        dlg.path_edit.setText(str(self.tmp / "missing.xml"))
        result, titles = self.run_result(dlg)
        self.assertIsNone(result)
        self.assertEqual(titles, ["File not found"])
        real = self.tmp / "a.xml"
        real.write_text("<level/>", encoding="utf-8")
        dlg.path_edit.setText(str(real))
        result, titles = self.run_result(dlg)
        self.assertEqual(result, le.StartResult(True, 0, 0, 0, real))

    def test_select_button_fills_path_and_switches_mode(self) -> None:
        dlg = self.dialog()
        with mock.patch(
            "wyrd.midgard.editors.level_editor.QFileDialog.getOpenFileName",
            return_value=("/x/y.xml", ""),
        ):
            dlg.select_file()
        self.assertEqual(dlg.path_edit.text(), "/x/y.xml")
        self.assertTrue(dlg.update_radio.isChecked())


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class MapWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def window(self, doc: LevelDoc | None = None, path: Path | None = None) -> "le.MapWindow":
        doc = doc or LevelDoc(5, 20, 20)
        win = le.MapWindow(
            doc, path or self.tmp / "Lv5" / "map" / "lv05.xml", doc.read_from_xml, cell_size=60
        )
        self.addCleanup(dispose, win)
        return win

    def cell(self, win: "le.MapWindow", gx: int, gy: int) -> "le.GroupWidget":
        return win.panel.cells[gx][gy]

    def test_window_basics(self) -> None:
        win = self.window()
        self.assertEqual(win.windowTitle(), "Edit Level 5")
        self.assertEqual(
            set(win.buttons), {"Clear Map", "Edit Cars", "Export", "Export As...", "Cancel"}
        )
        self.assertEqual(len(win.panel.cells), 10)
        self.assertEqual(win.cell_size, 60)

    def test_group_mouse_behaviour(self) -> None:
        win = self.window()
        w = self.cell(win, 3, 3)
        spot = QPoint(30, 30)
        with mock.patch.object(le.GridTypeSelector, "choose", return_value="FOUR_WAY") as choose:
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, pos=spot)
        choose.assert_called_once()
        self.assertEqual(win.doc.groups[3][3], "FOUR_WAY")
        QTest.mouseClick(w, Qt.MouseButton.MiddleButton, pos=spot)
        self.assertEqual(win.doc.groups[3][3], "FOUR_WAY_2")
        QTest.mouseClick(w, Qt.MouseButton.RightButton, pos=spot)
        self.assertEqual(win.doc.groups[3][3], "NON_ROAD")
        for x in range(3):
            win.doc.set_type(x, 0, "STRAIGHT_EW")
        w0 = self.cell(win, 0, 0)
        QTest.mousePress(w0, Qt.MouseButton.RightButton, pos=spot)
        QTest.mouseMove(w0, QPoint(90, 30))
        QTest.mouseMove(w0, QPoint(150, 30))
        QTest.mouseRelease(w0, Qt.MouseButton.RightButton, pos=QPoint(150, 30))
        self.assertEqual([win.doc.groups[x][0] for x in range(3)], ["NON_ROAD"] * 3)

    def test_left_drag_lays_road(self) -> None:
        win = self.window()
        w0 = self.cell(win, 2, 5)
        QTest.mousePress(w0, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        for gx in (3, 4, 5):
            QTest.mouseMove(w0, QPoint(30 + 60 * (gx - 2), 30))
        QTest.mouseRelease(w0, Qt.MouseButton.LeftButton, pos=QPoint(30 + 180, 30))
        self.assertEqual(
            [win.doc.groups[x][5] for x in range(2, 6)], ["STRAIGHT_EW"] * 3 + ["NON_ROAD"]
        )

    def test_edge_intersection_refused(self) -> None:
        win = self.window()
        win.doc.set_type(0, 0, "FOUR_WAY")
        with (
            mock.patch.object(QMessageBox, "critical") as critical,
            mock.patch.object(le, "CarEditor") as car_editor,
        ):
            win.edit_cars()
        critical.assert_called_once()
        self.assertEqual(critical.call_args.args[2], "Can't have intersections on the edge!")
        car_editor.assert_not_called()
        with mock.patch.object(QMessageBox, "critical") as critical:
            win.export()
        self.assertEqual(
            critical.call_args.args[2], "Can't have intersections on the edge! Level is not saved."
        )
        self.assertFalse((self.tmp / "Lv5").exists())

    def test_clear_map(self) -> None:
        win = self.window()
        win.doc.set_type(1, 1, "STRAIGHT_NS")
        win.clear_map()
        self.assertEqual(win.doc.groups[1][1], "NON_ROAD")

    def test_car_editor(self) -> None:
        doc = LevelDoc(5, 20, 20)
        doc.set_type(4, 0, "STRAIGHT_NS")
        doc.set_type(4, 9, "STRAIGHT_NS")
        self.assertTrue(doc.populate_starts_ends())
        dlg = le.CarEditor(doc)
        self.addCleanup(dispose, dlg)
        dlg.add_car()
        self.assertEqual(len(dlg.rows), 1)
        with mock.patch.object(QMessageBox, "critical") as critical:
            self.assertFalse(dlg.save())
        self.assertEqual(critical.call_args.args[2], "Please input delay for all cars")
        dlg.rows[0].delay_edit.setText("0")
        with mock.patch.object(QMessageBox, "critical") as critical:
            self.assertFalse(dlg.save())
        self.assertEqual(doc.cars, [])
        dlg.rows[0].delay_edit.setText("30")
        dlg.rows[0].end_box.setCurrentIndex(1)
        self.assertTrue(dlg.save())
        self.assertEqual(len(doc.cars), 1)
        self.assertEqual(doc.cars[0].delay, 30)
        self.assertEqual(doc.cars[0].start, doc.starts[0])
        self.assertEqual(doc.cars[0].end, doc.ends[1])

    def test_car_editor_cancel_and_same_start_and_remove(self) -> None:
        doc = LevelDoc.from_xml_file(level_path(1))
        before = list(doc.cars)
        dlg = le.CarEditor(doc)
        self.addCleanup(dispose, dlg)
        self.assertEqual(len(dlg.rows), len(before))
        dlg.rows[0].remove()
        dlg.add_car()
        dlg.rows[-1].delay_edit.setText("7")
        dlg.cancel()
        self.assertEqual(doc.cars, before)
        dlg = le.CarEditor(doc)
        self.addCleanup(dispose, dlg)
        dlg.add_car()
        dlg.add_car()
        for row in dlg.rows[-2:]:
            row.delay_edit.setText("999")
        with mock.patch.object(QMessageBox, "critical") as critical:
            self.assertFalse(dlg.save())
        self.assertIn("start at the same place at the same time", critical.call_args.args[2])

    def test_export_roundtrip_level1(self) -> None:
        shipped = level_path(1)
        target = self.tmp / "Lv1" / "map" / "lv01.xml"
        target.parent.mkdir(parents=True)
        shutil.copy(shipped, target)
        doc = LevelDoc.from_xml_file(target)
        win = self.window(doc, target)
        with mock.patch.object(QMessageBox, "information") as info:
            win.export()
        info.assert_called_once()
        self.assertEqual(
            info.call_args.args[2], f"Finished exporting\n{target}\n{target.with_suffix('.png')}"
        )
        self.assertEqual(target.read_bytes(), shipped.read_bytes())
        image = QImage(str(target.with_suffix(".png")))
        self.assertEqual(image.size(), le.render_map_image(doc).size())
        self.assertEqual((image.width(), image.height()), (1280, 1280))
        doc.set_type(5, 5, "NON_ROAD" if doc.groups[5][5] != "NON_ROAD" else "STRAIGHT_EW")
        with mock.patch.object(QMessageBox, "information"):
            win.export()
        self.assertEqual(parse_level_file(target), doc.to_level_data())
        self.assertNotEqual(target.read_bytes(), shipped.read_bytes())

    def test_failed_export_keeps_the_old_files(self) -> None:
        target = self.tmp / "Lv1" / "map" / "lv01.xml"
        target.parent.mkdir(parents=True)
        shutil.copy(level_path(1), target)
        image = target.with_suffix(".png")
        image.write_bytes(b"old image")
        old = target.read_bytes()
        doc = LevelDoc.from_xml_file(target)
        doc.set_type(5, 5, "NON_ROAD" if doc.groups[5][5] != "NON_ROAD" else "STRAIGHT_EW")
        with mock.patch(
            "wyrd.midgard.model.atomicio.os.replace", side_effect=OSError("disk full")
        ):
            self.assertEqual(le.export_level(doc, target), ["Error when exporting XML file"])
        self.assertEqual(target.read_bytes(), old)
        with mock.patch.object(QImage, "save", return_value=False):
            self.assertEqual(le.export_level(doc, target), ["Error when exporting map image"])
        self.assertEqual(image.read_bytes(), b"old image")
        self.assertEqual(sorted(p.name for p in target.parent.iterdir()), ["lv01.png", "lv01.xml"])

    def test_create_defaults_to_the_data_dir(self) -> None:
        home = self.tmp / "home"
        with mock.patch.dict(os.environ, {"MIDGARD_HOME": str(home)}):
            self.assertEqual(le.default_xml_path(7), home / "levels" / "Lv7" / "map" / "lv07.xml")
            win = le._open_window(le.StartResult(False, 7, 8, 8, None))
        assert win is not None
        self.addCleanup(dispose, win)
        self.assertEqual(win.xml_path, home / "levels" / "Lv7" / "map" / "lv07.xml")
        self.assertEqual(le.default_xml_path(3, self.tmp), self.tmp / "levels/Lv3/map/lv03.xml")

    def test_export_as_chooses_the_path(self) -> None:
        win = self.window()
        other = self.tmp / "elsewhere" / "mine.xml"
        dialog = "wyrd.midgard.editors.level_editor.QFileDialog.getSaveFileName"
        with (
            mock.patch(dialog, return_value=("", "")),
            mock.patch.object(QMessageBox, "information") as info,
        ):
            win.buttons["Export As..."].click()
        info.assert_not_called()
        with (
            mock.patch(dialog, return_value=(str(other), "")),
            mock.patch.object(QMessageBox, "information") as info,
        ):
            win.buttons["Export As..."].click()
        self.assertEqual(win.xml_path, other)
        self.assertTrue(other.is_file())
        self.assertIn(str(other), info.call_args.args[2])

    def test_dialogs_and_window_are_freed(self) -> None:
        assert_freed(self, lambda: le.MapWindow(LevelDoc(1, 8, 8), self.tmp / "x.xml", False, 20))
        assert_freed(self, le.StartDialog)
        assert_freed(self, lambda: le.CarEditor(LevelDoc(1, 8, 8)))

    def test_export_reports_write_errors(self) -> None:
        doc = LevelDoc(5, 20, 20)
        blocker = self.tmp / "blocked"
        blocker.write_text("file", encoding="utf-8")
        self.assertEqual(
            le.export_level(doc, blocker / "Lv5" / "map" / "lv05.xml"),
            ["Error when exporting XML file"],
        )
        doc.set_type(0, 0, "FOUR_WAY")
        self.assertEqual(
            le.export_level(doc, self.tmp / "x" / "lv05.xml"),
            ["Can't have intersections on the edge! Level is not saved."],
        )

    def test_create_new_level_exports_a_playable_level(self) -> None:
        doc = LevelDoc(5, 20, 20)
        for gy in range(10):
            doc.set_type(4, gy, "STRAIGHT_NS")
        self.assertTrue(doc.populate_starts_ends())
        doc.add_car(doc.starts[0], doc.ends[1], 20)
        out = self.tmp / "Levels" / "Lv5" / "map" / "lv05.xml"
        self.assertEqual(le.export_level(doc, out), ["Finished exporting"])
        self.assertTrue(out.with_suffix(".png").is_file())
        data = parse_level_file(out)
        town = TownMap(data)
        self.assertEqual(town.controls, [])
        level = Level(data, SensorSet())
        level.start([])
        self.assertGreater(run_until_done(level), 0)

    def test_render_map_image_size(self) -> None:
        self.assertEqual(le.render_map_image(LevelDoc(1, 20, 20)).width(), 1280)
        self.assertEqual(le.render_map_image(LevelDoc(1, 8, 12)).height(), 768)

    def test_main_args(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            le.main(["--help"])
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
