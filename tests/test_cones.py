"""Cones: walk, timing cone, cut-off on the hot/cold colours, and the GUI buttons."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import mimir_fixture as fx
from tests.test_pathview import BODY
from wyrd import mimirview
from wyrd.guimodel import cone, heatmimir, pathview
from wyrd.guimodel.heatview import BitSeg, FileHeat, HeatRange
from wyrd.mimirview import MimirView

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from PySide6.QtCore import QSettings

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.mainwindow import MainWindow

    def setUpModule() -> None:
        qapp()


G = fx.gnode
F = fx.FILE


def span(name: str) -> str:
    return G(name)[0]


class WalkTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.v = MimirView(fx.build(Path(tmp.name) / "g.db", graph=True))
        self.g = self.v.hdl_graph("r1")

    def walkcone(
        self, name: str, direction: str, cross: bool = False, cutoff: float | None = None
    ) -> cone.Cone:
        crits = self.v.span_crits("r1")
        return cone.structural_cone(self.g.edges, self.g.ports, [span(name)], None, None,
                                    direction, cross, crits.get, cutoff)  # fmt: skip

    def levels(self, c: cone.Cone) -> dict[int, int]:
        return {n.line: n.level for n in c.nodes}

    def test_forward_stops_at_the_register(self) -> None:
        c = self.walkcone("a", cone.FORWARD)
        self.assertEqual(self.levels(c), {10: 0, 20: 1, 30: 2, 40: 3})
        self.assertEqual(c.source, cone.STRUCTURAL)

    def test_forward_crossing_reaches_the_output(self) -> None:
        c = self.walkcone("a", cone.FORWARD, cross=True)
        self.assertEqual(self.levels(c), {10: 0, 20: 1, 30: 2, 40: 3, 50: 4})
        self.assertEqual({n.line: n.kind for n in c.nodes if n.kind}, {50: cone.PO})

    def test_backward_ends_at_the_input(self) -> None:
        c = self.walkcone("c", cone.BACKWARD)
        self.assertEqual(self.levels(c), {30: 0, 20: 1, 10: 2})
        self.assertEqual({n.line: n.kind for n in c.nodes if n.kind}, {10: cone.PI})

    def test_backward_stops_at_a_register_output(self) -> None:
        c = self.walkcone("d", cone.BACKWARD)
        self.assertEqual(self.levels(c), {50: 0, 40: 1})
        self.assertEqual([n.kind for n in c.nodes if n.line == 40], [cone.REG])
        crossed = self.walkcone("d", cone.BACKWARD, cross=True)
        self.assertEqual(self.levels(crossed), {50: 0, 40: 1, 30: 2, 20: 3, 10: 4})

    def test_cutoff_hides_cold_lines_and_counts_them(self) -> None:
        c = self.walkcone("a", cone.FORWARD, cutoff=0.9)
        self.assertEqual(self.levels(c), {10: 0, 20: 1, 30: 2})
        self.assertEqual(c.hidden, 1)

    def test_word_and_bit_pick_the_start(self) -> None:
        nodes = {n for e in self.g.edges for n in e[:2]}
        got = cone.start_nodes(nodes, [span("a")], "a", 3)
        self.assertEqual(got, {G("a")})
        self.assertEqual(cone.start_nodes(nodes, [span("a")], "a", 7), {G("a")})  # word only
        self.assertEqual(cone.start_nodes(nodes, [span("a")], "zz", None), {G("a")})  # line

    def test_unknown_token_gives_a_note(self) -> None:
        c = cone.structural_cone(self.g.edges, self.g.ports, ["x.v:1"], None, None, cone.FORWARD,
                                 False, lambda s: 1.0, None)  # fmt: skip
        self.assertEqual(c.nodes, [])
        self.assertTrue(c.notes)

    def test_timing_cone_takes_steps_after_and_before(self) -> None:
        v = MimirView(fx.build(self.v.path.parent / "t.db", paths=True))
        paths = [v.path_detail("r1", i).nodes for i in (1, 2, 3)]
        crit = {f"{F}:{n}": 1.0 for n in (10, 20, 30)}

        def crit_of(s: str) -> float | None:
            return crit.get(s)

        fwd = cone.timing_cone(paths, [f"{F}:10"], "a", cone.FORWARD, crit_of, None)
        self.assertEqual(self.levels(fwd), {20: 1, 30: 1, 5: 1})  # 5: path 3 leaves the file
        self.assertEqual({n.file for n in fwd.nodes}, {F, "$VTR_ROOT/other.v"})
        self.assertEqual(fwd.source, cone.TIMING)
        self.assertIn("stops where", fwd.notes[0])
        back = cone.timing_cone(paths, [f"{F}:20"], None, cone.BACKWARD, crit_of, None)
        self.assertEqual(self.levels(back), {10: 1})
        cut = cone.timing_cone(paths, [f"{F}:10"], "a", cone.FORWARD, crit_of, 0.9)
        self.assertEqual(self.levels(cut), {20: 1, 30: 1})
        self.assertEqual(cut.hidden, 1)  # other.v:5 has no crit
        cold = cone.timing_cone(paths, [f"{F}:10"], "a", cone.FORWARD, lambda s: None, 0.9)
        self.assertEqual((cold.nodes, cold.hidden), ([], 3))

    def test_graph_notes(self) -> None:
        old = MimirView(fx.build(self.v.path.parent / "p.db", paths=True))
        self.assertEqual(old.hdl_graph("r1").note, mimirview.NO_GRAPH)
        self.assertEqual(self.v.hdl_graph("r2").note, mimirview.NO_RUN_GRAPH)


class CutHeatTest(unittest.TestCase):
    def test_below_cutoff_is_plain_text(self) -> None:
        hot = HeatRange(3, 0, 1, "a", 0.95, (BitSeg(1, 0, 1, 0.95), BitSeg(0, 1, 2, 0.5)),
                        ((1, 0.95), (0, 0.5)))  # fmt: skip
        cold = HeatRange(4, 0, 1, "b", 0.5)
        fh = FileHeat({3: 0.95, 4: 0.5}, [hot, cold], {3: (1,), 4: (2,)}, ["u"])
        out = pathview.cut_heat(fh, 0.9)
        self.assertEqual(out.lines, {3: 0.95})
        self.assertEqual([r.line for r in out.ranges], [3])
        self.assertEqual(out.ranges[0].segments, (BitSeg(1, 0, 1, 0.95),))
        self.assertEqual(out.ranges[0].strip, ((1, 0.95),))
        self.assertEqual(out.line_paths, {3: (1,)})
        self.assertIs(pathview.cut_heat(fh, None), fh)


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class WindowTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        (self.tmp / "d.v").write_text(BODY, encoding="utf-8")
        self.db = fx.build(self.tmp / "p.db", graph=True)
        patch = mock.patch.dict(os.environ, {"VTR_ROOT": str(self.tmp)})
        patch.start()
        self.addCleanup(patch.stop)
        self.w = MainWindow(
            QSettings(str(self.tmp / "s.ini"), QSettings.Format.IniFormat), silent=True
        )
        self.addCleanup(dispose, self.w)
        rows = [("span", f"{F}:10", -1, "", 1.0), ("word", "top/a", 3, "name", 1.0)]
        self.w._on_mimir_heat(heatmimir.model_from_objects(rows, F, "report", str(self.db), "r1"))
        fh = self.w.source_view.text.file_heat
        assert fh is not None
        r = fh.ranges[0]
        self.w._on_heat_click(r.line, r.col_start)

    def test_fan_out_button_marks_levels_in_the_gutter(self) -> None:
        self.w.source_view.fan_out.click()
        p = self.w.paths
        assert p.cone is not None
        self.assertEqual(p.cone.source, cone.STRUCTURAL)
        self.assertIn("Structural cone", p.cone_status.text())
        ov = self.w.source_view.text.overlay
        assert ov is not None
        self.assertEqual(ov.levels, {10: 0, 20: 1, 30: 2})  # cut-off 0.90 hides lines 40, 50
        self.assertEqual(ov.marker(20), "L1")
        self.assertEqual(p.cone_tree.topLevelItemCount(), 3)
        self.w.source_view.text.resize(500, 300)
        self.assertFalse(self.w.source_view.text.grab().isNull())

    def test_cutoff_off_and_crossing_shows_the_whole_cone(self) -> None:
        p = self.w.paths
        p.cutoff.setCurrentIndex(3)
        p.cross.setChecked(True)
        p.fan_out.click()
        assert p.cone is not None
        self.assertEqual({n.line for n in p.cone.nodes}, {10, 20, 30, 40, 50})
        kinds = {n.line: n.kind for n in p.cone.nodes if n.kind}
        self.assertEqual(kinds, {50: cone.PO})

    def test_fan_in_and_timing_source(self) -> None:
        p = self.w.paths
        p.cone_source.setCurrentIndex(1)
        p.fan_in.click()
        assert p.cone is not None
        self.assertEqual(p.cone.source, cone.TIMING)
        self.assertIn("Timing cone", p.cone_status.text())

    def test_clearing_and_choosing_a_path_remove_the_cone(self) -> None:
        p = self.w.paths
        p.fan_out.click()
        p.clear_cone_button.click()
        self.assertIsNone(p.cone)
        p.fan_out.click()
        p.table.clearSelection()
        p.table.selectRow(0)
        self.assertIsNone(p.cone)

    def test_cutoff_applies_to_the_base_colouring(self) -> None:
        fh = self.w.source_view.text.file_heat
        assert fh is not None and fh.ranges  # crit 1.0 at the default cut-off 0.90
        rows = [("span", f"{F}:10", -1, "", 0.95), ("word", "top/a", 3, "name", 0.95)]
        self.w._on_mimir_heat(heatmimir.model_from_objects(rows, F, "report", str(self.db), "r1"))
        shown = self.w.source_view.text.file_heat
        assert shown is not None and shown.ranges
        self.w.paths.cutoff.setCurrentIndex(2)  # 0.99: 0.95 becomes plain text
        cold = self.w.source_view.text.file_heat
        assert cold is not None
        self.assertEqual((cold.ranges, cold.lines), ([], {}))
        self.w.paths.cutoff.setCurrentIndex(3)  # off: back
        again = self.w.source_view.text.file_heat
        assert again is not None
        self.assertTrue(again.ranges)


if __name__ == "__main__":
    unittest.main()
