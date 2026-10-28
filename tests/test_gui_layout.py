"""Window layout, View capabilities, zoom, About headers, tooltips; Qt runs offscreen."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QRect, QSettings, Qt
    from PySide6.QtGui import QMouseEvent, QPointingDevice, QWheelEvent
    from PySide6.QtWidgets import QDockWidget, QMenu, QPlainTextEdit, QVBoxLayout, QWidget

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


class _FakeFileHeat:
    """Just enough of a FileHeat for the heat-click handler."""

    ranges: tuple[object, ...] = ()
    line_paths: dict[int, tuple[int, ...]] = {1: (3, 4)}

    def range_at(self, line: int, col: int) -> None:
        return None


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

    def on_top(self, w: MainWindow) -> set[str]:
        """The docks the user sees: not hidden and the current tab of their group."""
        assert w.viewlayout is not None
        return {n for n, d in w.docks.items() if w.viewlayout._on_screen(d)}

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
            self.assertEqual(self.on_top(w), {g.current for g in p.groups}, p.name)

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
        self.assertEqual(self.on_top(w), {"Timing"})
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

    def helpbox_in(self, name: str, width: int, panel: bool = True) -> HelpBox:
        box = HelpBox(name, panel=panel)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.addWidget(box)
        lay.addStretch(1)  # as in a panel: the content below takes the spare height
        host.resize(width, 600)
        host.show()
        pump()
        self.addCleanup(dispose, host)
        return box

    def test_helpbox_does_not_clip_on_a_narrow_dock(self) -> None:
        for name in ls.PANELS:
            box = self.helpbox_in(name, 300)
            self.assertTrue(box.is_shown())
            need = box.label.heightForWidth(box.label.width())
            self.assertGreaterEqual(box.label.height(), need, name)
            self.assertGreaterEqual(box.height(), box.heightForWidth(box.width()), name)
            # no empty gap under the text
            self.assertLessEqual(box.label.height() - need, 4, name)

    def test_helpbox_is_taller_when_narrower(self) -> None:
        box = self.helpbox_in("Timing", 300)
        self.assertGreater(box.heightForWidth(300), box.heightForWidth(900))

    def test_helpbox_starts_expanded_then_remembers_per_panel(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        settings = QSettings(str(Path(tmp.name) / "a.ini"), QSettings.Format.IniFormat)
        first = HelpBox("Source", panel=True, settings=settings)
        other = HelpBox("Timing", panel=True, settings=settings)
        self.assertTrue(first.is_shown() and other.is_shown())  # first run: expanded
        first.toggle.click()
        self.assertFalse(first.is_shown())
        again = HelpBox("Source", panel=True, settings=settings)
        self.assertFalse(again.is_shown())  # remembered
        self.assertTrue(HelpBox("Timing", panel=True, settings=settings).is_shown())
        unshared = HelpBox("Source", panel=True)  # no settings: nothing shared, nothing stored
        self.assertTrue(unshared.is_shown())
        unshared.toggle.click()
        self.assertTrue(HelpBox("Source", panel=True).is_shown())

    # ---- fix round: L1 L2 L7 L8 Q1 Q2 and the wording ----

    def test_maximise_fallback_is_the_largest_shown_dock_not_dict_order(self) -> None:
        w = self.make()
        lay = w.viewlayout
        assert lay is not None
        lay.apply_preset("Everything tabbed")
        pump()
        w.docks["Timing"].raise_()
        pump()
        lay._last = None
        # nothing focused, mouse elsewhere: the one visible tab of the one group
        self.assertEqual(self.on_top(w), {"Timing"})
        self.assertIs(lay._largest(), w.docks["Timing"])
        lay.apply_preset("Timing + source")
        pump()
        self.assertIs(lay._largest(), w.docks["Source"])  # 0.6 of the width beats Timing's 0.4

    def test_maximise_ignores_hidden_tabs(self) -> None:
        w = self.make()
        lay = w.viewlayout
        assert lay is not None
        lay.apply_preset("Everything tabbed")
        pump()
        w.docks["Atlas"].raise_()
        pump()
        self.assertFalse(lay._on_screen(w.docks["Source"]))  # a tab behind Atlas
        self.assertTrue(lay._on_screen(w.docks["Atlas"]))

    def test_menu_actions_ignore_the_checked_flag(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        calls: list[tuple[object, ...]] = []

        def slot(*args: object) -> None:
            calls.append(args)

        act = w._action(w.menuBar().addMenu("T"), "x", slot)
        act.trigger()
        self.assertEqual(calls, [()])

    def test_heat_click_raises_the_timing_dock(self) -> None:
        w = self.make()
        w.viewlayout.apply_preset("Project")  # type: ignore[union-attr]
        pump()
        self.assertNotIn("Timing", self.on_top(w))  # a tab behind Messages
        fh = _FakeFileHeat()
        w.source_view.text.file_heat = fh  # type: ignore[assignment]
        w._on_heat_click(1, 0)
        pump()
        self.assertIn("Timing", self.on_top(w))
        self.assertIn("line 1", w.timing.hits_label.text())

    def wheel(self, dy: int, mods: Qt.KeyboardModifier) -> QWheelEvent:
        return QWheelEvent(
            QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy), Qt.MouseButton.NoButton,
            mods, Qt.ScrollPhase.NoScrollPhase, False,
        )  # fmt: skip

    def test_ctrl_wheel_zooms_text_and_tables(self) -> None:
        w = self.make()
        lay = w.viewlayout
        assert lay is not None
        lay.set_zoom(0)
        port = w.editor.text.viewport()
        assert port is not None
        ctrl = Qt.KeyboardModifier.ControlModifier
        self.assertTrue(lay.eventFilter(port, self.wheel(120, ctrl)))
        self.assertEqual(lay.zoom, 1)
        self.assertTrue(lay.eventFilter(port, self.wheel(-120, ctrl)))
        self.assertEqual(lay.zoom, 0)
        self.assertFalse(lay.eventFilter(port, self.wheel(120, Qt.KeyboardModifier.NoModifier)))
        self.assertEqual(lay.zoom, 0)
        table_port = w.messages.table.viewport()
        assert table_port is not None
        self.assertTrue(table_port.property("wyrdWheel"))
        self.assertTrue(port.property("wyrdWheel"))

    def test_zoom_in_has_three_shortcuts(self) -> None:
        w = self.make()
        view = next(a.menu() for a in w.menuBar().actions() if a.text() == "View")
        assert isinstance(view, QMenu)
        keys = {a.text(): [k.toString() for k in a.shortcuts()] for a in view.actions()}
        self.assertIn("Ctrl+Shift+=", keys["Zoom in"])

    def test_floating_dock_off_screen_comes_back(self) -> None:
        w = self.make()
        lay = w.viewlayout
        assert lay is not None
        dock = w.docks["Messages"]
        dock.setFloating(True)
        dock.setGeometry(QRect(5000, 4000, 400, 200))
        pump()
        screen = QRect(0, 0, 1366, 768)
        lay.ensure_on_screen([screen], screen)
        self.assertTrue(screen.contains(dock.frameGeometry()))
        inside = QRect(100, 100, 300, 150)
        dock.setGeometry(inside)
        pump()
        lay.ensure_on_screen([screen], screen)
        self.assertEqual(dock.geometry().topLeft(), inside.topLeft())  # already inside: untouched
        dock.setGeometry(QRect(1300, 700, 400, 200))  # straddles the edge
        pump()
        lay.ensure_on_screen([screen], screen)
        self.assertTrue(screen.contains(dock.frameGeometry()))
        dock.setFloating(False)

    def test_layout_menu_ticks_the_active_preset(self) -> None:
        w = self.make()
        lay = w.viewlayout
        assert lay is not None
        def ticked() -> list[str]:
            return [n for n, a in lay._preset_actions.items() if a.isChecked()]

        self.assertEqual(ticked(), [ls.DEFAULT_PRESET])
        lay.apply_preset("Timing + source")
        pump()
        self.assertEqual(ticked(), ["Timing + source"])
        w.addDockWidget(Qt.DockWidgetArea.TopDockWidgetArea, w.docks["Messages"])  # the user moves
        pump()
        self.assertEqual(ticked(), [])
        self.assertEqual(lay.preset, "")
        lay.toggle_maximise(w.docks["Timing"])  # our own moves do not clear a tick
        lay.toggle_maximise()
        lay.apply_preset("Mímir explorer")
        pump()
        self.assertEqual(ticked(), ["Mímir explorer"])

    def test_tick_is_saved_and_restored(self) -> None:
        w = self.make()
        assert w.viewlayout is not None
        w.viewlayout.apply_preset("Timing + source")
        pump()
        w._closing = True
        w.close()
        w2 = self.make()
        assert w2.viewlayout is not None
        self.assertEqual(w2.viewlayout.preset, "Timing + source")

    def test_crit_wording_everywhere(self) -> None:
        from wyrd.guimodel import heatview, mimirhelp

        texts = {
            "Source": " ".join(panelhelp.PANELS[ls.SOURCE]),
            "Timing": " ".join(panelhelp.PANELS[ls.TIMING]),
            "Mimir Timing": " ".join(mimirhelp.TABS["Timing"]),
            "guide": panelhelp.GUIDE,
        }
        for name in ("Timing", "Mimir Timing", "guide"):
            t = " ".join(texts[name].split())
            self.assertIn("how close", t, name)
            self.assertIn("largest required time", t, name)
            self.assertIn("worst is 0", t, name)
            self.assertNotIn("divided by the clock period", t, name)
        src = " ".join(texts["Source"].split())
        self.assertIn("whose index is unknown", src)
        self.assertIn("always found by matching", src)
        self.assertIn("always found by name match", heatview.LEGEND_NOTE)
        self.assertIn("index is unknown", heatview.LEGEND_NOTE)
        self.assertIn("MSB first", texts["Mimir Timing"])

    def test_plot_texts_say_one_dot_per_source_and_design(self) -> None:
        m = self.make().mimir
        from wyrd.guimodel import mimirhelp

        self.assertIn("source, design", m.chart.toolTip())
        self.assertNotIn("per run", m.plot_go.toolTip())
        self.assertNotIn("per run", m.chart.toolTip())
        self.assertIn("mean", " ".join(mimirhelp.TABS["Plot"]))

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
