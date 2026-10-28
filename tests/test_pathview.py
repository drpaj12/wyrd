"""Path view: model (cut-off, overlays) and GUI wiring on a synthetic schema 6 store."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import mimir_fixture
from wyrd import mimirview
from wyrd.guimodel import heatmimir, pathview
from wyrd.mimirview import MimirView

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QSettings

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.mainwindow import MainWindow

    def setUpModule() -> None:
        qapp()


F = mimir_fixture.FILE


class ModelTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.v = MimirView(mimir_fixture.build(Path(tmp.name) / "p.db", paths=True))

    def nodes(self, i: int) -> list[mimirview.PathNodeRow]:
        return self.v.path_detail("r1", i).nodes

    def test_cutoff_choices(self) -> None:
        self.assertEqual(pathview.cutoff_at(0), 0.90)
        self.assertIsNone(pathview.cutoff_at(3))
        self.assertEqual(pathview.cutoff_at(99), 0.90)
        self.assertEqual(pathview.cutoff_index("0.99"), 2)
        self.assertEqual(pathview.cutoff_index("junk"), 0)
        self.assertEqual(pathview.cutoff_header(0.9), "showing paths with crit >= 0.90")
        self.assertIn("off", pathview.cutoff_header(None))

    def test_visible_below_cutoff_is_hidden(self) -> None:
        self.assertTrue(pathview.visible(0.9, 0.9))
        self.assertFalse(pathview.visible(0.8999, 0.9))
        self.assertFalse(pathview.visible(None, 0.9))
        self.assertTrue(pathview.visible(None, None))

    def test_path_overlay_steps_and_marker(self) -> None:
        ov = pathview.path_overlay(self.nodes(1), 1.0, lambda f: f == F, 0.9)
        self.assertEqual(ov.lines(), {10, 20})
        self.assertEqual(ov.marker(10), "1 1.00")
        self.assertEqual(ov.marker(20), "2 0.50")
        self.assertEqual(ov.marker(5), "")

    def test_path_below_cutoff_draws_nothing(self) -> None:
        self.assertEqual(pathview.path_overlay(self.nodes(2), 0.8, lambda f: True, 0.9).lines(),
                         set())  # fmt: skip
        self.assertEqual(pathview.path_overlay(self.nodes(2), 0.8, lambda f: True, None).lines(),
                         {10, 30})  # fmt: skip

    def test_other_file_steps_are_left_out(self) -> None:
        ov = pathview.path_overlay(self.nodes(3), 0.4, lambda f: f == F, None)
        self.assertEqual(ov.lines(), {10})

    def test_union_colours_by_max_crit_and_skips_low_paths(self) -> None:
        paths = [(1.0, self.nodes(1)), (0.8, self.nodes(2)), (0.95, self.nodes(2))]
        ov = pathview.union_overlay(paths, lambda f: f == F, 0.9)
        self.assertTrue(ov.union)
        self.assertEqual(ov.colors, {10: 1.0, 20: 1.0, 30: 0.95})
        self.assertEqual(pathview.union_theta(0.99), 0.99)
        self.assertEqual(pathview.union_theta(None), 0.90)

    def test_click_queries_most_specific_first(self) -> None:
        q = pathview.click_queries(["f:1"], "w", 3)
        self.assertEqual(q, [(("f:1",), "w", 3), (("f:1",), "w", None), (("f:1",), None, None)])
        self.assertEqual(pathview.click_queries(["f:1"], None, None), [(("f:1",), None, None)])

    def test_step_cells(self) -> None:
        cells = pathview.step_cells(self.nodes(1)[0])
        self.assertEqual(cells, ["1", "d.v:10", "a[3]", "top", "1.000"])


BODY = (
    "\n".join(f"// line {i}" for i in range(1, 10))
    + "\nmodule top(input [3:0] a, output y);\n"
    + "\n".join(f"// line {i}" for i in range(11, 40))
    + "\nendmodule\n"
)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class WindowTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        (self.tmp / "d.v").write_text(BODY, encoding="utf-8")
        self.db = mimir_fixture.build(self.tmp / "p.db", paths=True)
        patch = mock.patch.dict(os.environ, {"VTR_ROOT": str(self.tmp)})
        patch.start()
        self.addCleanup(patch.stop)
        self.ini = str(self.tmp / "s.ini")
        self.w = MainWindow(QSettings(self.ini, QSettings.Format.IniFormat), silent=True)
        self.addCleanup(dispose, self.w)
        rows = [("span", f"{F}:10", -1, "", 1.0), ("word", "top/a", 3, "name", 1.0)]
        self.w._on_mimir_heat(
            heatmimir.model_from_objects(rows, F, "report", str(self.db), "r1")
        )

    def click_token(self) -> None:
        fh = self.w.source_view.text.file_heat
        assert fh is not None
        r = fh.ranges[0]
        self.w._on_heat_click(r.line, r.col_start)

    def test_click_lists_paths_and_shows_one(self) -> None:
        self.click_token()
        p = self.w.paths
        self.assertEqual([r.index for r in p.refs], [1])  # 0.90 cut-off hides 0.8 and 0.4
        self.assertIn("crit >= 0.90", p.header.text())
        ov = self.w.source_view.text.overlay
        assert ov is not None
        self.assertEqual(ov.lines(), {10, 20})
        self.assertEqual(self.w.source_view.text.heat_width(), pathview_width())
        self.w.source_view.text.resize(500, 300)
        self.assertFalse(self.w.source_view.text.grab().isNull())  # paints markers and the veil

    def test_cutoff_off_lists_all_and_next_walks(self) -> None:
        p = self.w.paths
        self.click_token()
        p.cutoff.setCurrentIndex(3)
        self.assertEqual([r.index for r in p.refs], [1, 2, 3])
        self.assertFalse(p.prev.isEnabled())
        p.next.click()
        chosen = p.chosen()
        assert chosen is not None
        self.assertEqual(chosen.index, 2)
        ov = self.w.source_view.text.overlay
        assert ov is not None
        self.assertEqual(ov.lines(), {10, 30})
        self.assertEqual(p.steps.rowCount(), 2)

    def test_cutoff_is_remembered(self) -> None:
        self.w.paths.cutoff.setCurrentIndex(2)
        s2 = QSettings(self.ini, QSettings.Format.IniFormat)
        s2.sync()
        self.assertEqual(str(s2.value("pathsCutoff")), "0.99")

    def test_union_colours_lines(self) -> None:
        self.click_token()
        self.w.paths.cutoff.setCurrentIndex(3)
        self.w.paths.union.setChecked(True)
        ov = self.w.source_view.text.overlay
        assert ov is not None
        self.assertTrue(ov.union)
        self.assertEqual(ov.colors, {10: 1.0, 20: 1.0})  # path 2 (0.8) is below 0.90

    def test_step_in_another_file_opens_it(self) -> None:
        self.click_token()
        p = self.w.paths
        p.cutoff.setCurrentIndex(3)
        p.table.selectRow(2)
        (self.tmp / "other.v").write_text(BODY, encoding="utf-8")
        p.steps.selectRow(1)
        self.assertEqual(self.w.source_view.path, self.tmp / "other.v")

    def test_v5_store_says_so(self) -> None:
        v5 = mimir_fixture.build(self.tmp / "v5.db", timing=True)
        self.w.paths.show_for(str(v5), "r1", "x", [((f"{F}:10",), None, None)])
        self.assertIn("--paths-from-blobs", self.w.paths.status.text())
        self.assertEqual(self.w.paths.refs, [])


def pathview_width() -> int:
    from wyrd.gui.sourceview import STEP_WIDTH

    return STEP_WIDTH


if __name__ == "__main__":
    unittest.main()
