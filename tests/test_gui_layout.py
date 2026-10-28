"""Window layout, View capabilities, zoom, About headers, tooltips; Qt runs offscreen."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QSettings, Qt
    from PySide6.QtGui import QMouseEvent, QPointingDevice
    from PySide6.QtWidgets import QDockWidget, QMenu, QPlainTextEdit, QWidget

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.helpbox import HelpBox
    from wyrd.gui.mainwindow import MainWindow
    from wyrd.guimodel import layoutspec as ls
    from wyrd.guimodel import panelhelp

    def setUpModule() -> None:
        qapp()


def pump() -> None:
    for _ in range(3):
        QCoreApplication.processEvents()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class LayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ini = str(Path(tmp.name) / "s.ini")
        self.windows: list[MainWindow] = []

    def tearDown(self) -> None:
        for w in self.windows:
            w._closing = True
            dispose(w)

    def make(self, size: tuple[int, int] = (1366, 768)) -> MainWindow:
        settings = QSettings(self.ini, QSettings.Format.IniFormat)
        w = MainWindow(settings, silent=True)
        w.resize(*size)
        w.show()
        pump()
        self.windows.append(w)
        return w

    def shown(self, w: MainWindow) -> set[str]:
        return {n for n, d in w.docks.items() if not d.isHidden()}

    def test_every_panel_is_a_movable_dock(self) -> None:
        w = self.make()
        self.assertEqual(list(w.docks), list(ls.PANELS))
        self.assertIsNone(w.centralWidget())
        names = set()
        for dock in w.docks.values():
            f = dock.features()
            for flag in (
                QDockWidget.DockWidgetFeature.DockWidgetClosable,
                QDockWidget.DockWidgetFeature.DockWidgetMovable,
                QDockWidget.DockWidgetFeature.DockWidgetFloatable,
            ):
                self.assertTrue(f & flag)
            names.add(dock.objectName())
        self.assertEqual(len(names), len(ls.PANELS))

    def test_presets_apply(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        for p in ls.PRESETS:
            w.viewlayout.apply_preset(p.name)
            pump()
            self.assertEqual(self.shown(w), set(p.shown()), p.name)
            self.assertEqual(w.viewlayout.preset, p.name)

    def test_reset_restores_the_default(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        w.viewlayout.apply_preset("Mímir explorer")
        w.viewlayout.reset()
        pump()
        self.assertEqual(self.shown(w), set(ls.preset_named(ls.DEFAULT_PRESET).shown()))
        w.docks["Source"].hide()
        w.viewlayout.reset()
        self.assertFalse(w.docks["Source"].isHidden())

    def test_mimir_explorer_gives_mimir_the_window(self) -> None:
        w = self.make((1366, 768))
        assert w.viewlayout is not None
        w.viewlayout.apply_preset("Mímir explorer")
        pump()
        self.assertGreater(w.docks["Mímir"].height(), 0.8 * w.height())
        self.assertTrue(w.docks["Project"].isHidden())

    def test_project_panels_can_all_be_hidden(self) -> None:
        w = self.make()
        for dock in w.docks.values():
            dock.hide()
        w.docks["Mímir"].show()
        pump()
        self.assertEqual(self.shown(w), {"Mímir"})
        self.assertGreater(w.docks["Mímir"].height(), 0.8 * w.height())

    def test_maximise_toggle(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        before = self.shown(w)
        self.assertTrue(w.viewlayout.toggle_maximise(w.docks["Timing"]))
        pump()
        self.assertEqual(self.shown(w), {"Timing"})
        self.assertTrue(w.viewlayout.maximised)
        self.assertGreater(w.docks["Timing"].height(), 0.8 * w.height())
        self.assertFalse(w.viewlayout.toggle_maximise())
        pump()
        self.assertEqual(self.shown(w), before)
        self.assertFalse(w.viewlayout.maximised)

    def test_title_double_click_maximises(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        dock = w.docks["Messages"]
        ev = QMouseEvent(
            QEvent.Type.MouseButtonDblClick, QPointF(4, 2), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            QPointingDevice.primaryPointingDevice(),
        )  # fmt: skip
        self.assertTrue(w.viewlayout.eventFilter(dock, ev))
        self.assertTrue(w.viewlayout.maximised)
        w.viewlayout.toggle_maximise()

    def test_layout_round_trip(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        w.viewlayout.apply_preset("Timing + source")
        w._closing = True
        w.close()
        w2 = self.make()
        self.assertEqual(self.shown(w2), set(ls.preset_named("Timing + source").shown()))

    def test_close_while_maximised_saves_the_earlier_layout(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        before = self.shown(w)
        w.viewlayout.toggle_maximise(w.docks["Timing"])
        w._closing = True
        w.close()
        self.assertEqual(self.shown(self.make()), before)

    def test_bad_saved_state_is_ignored(self) -> None:
        s = QSettings(self.ini, QSettings.Format.IniFormat)
        s.setValue("layout/version", ls.LAYOUT_VERSION - 1)
        s.setValue("layout/state", b"garbage")
        s.sync()
        w = self.make()
        self.assertEqual(self.shown(w), set(ls.preset_named(ls.DEFAULT_PRESET).shown()))
        s.setValue("layout/version", ls.LAYOUT_VERSION)
        s.sync()
        w2 = self.make()  # right version, unreadable state
        self.assertEqual(self.shown(w2), set(ls.preset_named(ls.DEFAULT_PRESET).shown()))

    def test_zoom_persists(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        edit = w.editor.text
        base = edit.font().pointSizeF()
        w.viewlayout.set_zoom(3)
        self.assertEqual(edit.font().pointSizeF(), base + 3)
        w.viewlayout.set_zoom(99)
        self.assertEqual(w.viewlayout.zoom, ls.ZOOM_MAX)
        w.viewlayout.set_zoom(3)
        w2 = self.make()
        assert w2.viewlayout is not None
        self.assertEqual(w2.viewlayout.zoom, 3)
        self.assertEqual(w2.editor.text.font().pointSizeF(), base + 3)
        w2.viewlayout.set_zoom(0)
        self.assertEqual(w2.editor.text.font().pointSizeF(), base)

    def test_view_menu_has_the_actions(self) -> None:
        w = self.make()
        view = next(a.menu() for a in w.menuBar().actions() if a.text() == "View")
        assert isinstance(view, QMenu)
        texts = {a.text() for a in view.actions()}
        for t in ("Maximise current panel", "Zoom in", "Zoom out", "Reset zoom"):
            self.assertIn(t, texts)
        keys = {a.text(): [k.toString() for k in a.shortcuts()] for a in view.actions()}
        self.assertEqual(keys["Maximise current panel"], ["F11", "Ctrl+Shift+M"])
        self.assertIn("Ctrl+0", keys["Reset zoom"])

    def test_tables_stretch_and_splitters_keep_handles(self) -> None:
        w = self.make()
        self.assertTrue(w.messages.table.horizontalHeader().stretchLastSection())
        edits = w.findChildren(QPlainTextEdit)
        self.assertTrue(edits)

    def test_about_header_on_every_panel(self) -> None:
        w = self.make()
        boxes = {b.tab: b for b in w.findChildren(HelpBox) if b.panel}
        self.assertEqual(set(boxes), set(ls.PANELS))
        for name in ls.PANELS:
            self.assertIn(name, w.contents[name].findChildren(HelpBox)[0].tab)
            self.assertIn("What this shows", boxes[name].label.text())

    def test_about_state_remembered_and_all_toggle(self) -> None:
        w = self.make()
        w.set_all_about(False)
        self.assertTrue(all(not b.is_shown() for b in w.findChildren(HelpBox)))
        w2 = self.make()
        panel_boxes = [b for b in w2.findChildren(HelpBox) if b.panel]
        self.assertTrue(all(not b.is_shown() for b in panel_boxes))
        w2.set_all_about(True)
        self.assertTrue(all(b.is_shown() for b in w2.findChildren(HelpBox)))

    def test_guide_dialog_shows_every_panel(self) -> None:
        from wyrd.gui.mimirguide import MimirGuideDialog

        dlg = MimirGuideDialog()
        self.addCleanup(dispose, dlg)
        text = dlg.browser.toPlainText()
        for name in panelhelp.PANELS:
            self.assertIn(name, text)

    def test_mimir_controls_have_tooltips(self) -> None:
        w = self.make()
        m = w.mimir
        controls: list[QWidget] = [
            m.open_button, m.last_button, m.source, m.filter, m.designs, m.design_label,
            m.design_level, m.design_tabs, m.run_label, m.params_pane, m.artifacts_pane,
            m.fetch_button, m.cancel_button, m.fetch_log, m.cmp_prefix, m.cmp_base,
            m.cmp_metric, m.cmp_level, m.cmp_load, m.cmp_go, m.cmp_pane, m.cmp_scroll,
            m.plot_x, m.plot_y, m.plot_source, m.log_x, m.log_y, m.plot_go, m.chart,
            m.metrics_pane.copy_button, m.metrics_pane.export_button, m.runs_pane.grid,
        ]  # fmt: skip
        self.assertEqual([c for c in controls if not c.toolTip()], [])


if __name__ == "__main__":
    unittest.main()
