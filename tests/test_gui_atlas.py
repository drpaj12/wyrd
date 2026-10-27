"""Atlas panel; Qt runs offscreen. Fixtures: tests/data/atlas (Norns round-7 samples)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from wyrd import atlas

HAVE_QT = importlib.util.find_spec("PySide6") is not None
DATA = Path(__file__).parent / "data" / "atlas"

if HAVE_QT:
    from PySide6.QtCore import QEventLoop, QTimer

    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.atlaspanel import AtlasPanel

    def setUpModule() -> None:
        qapp()

    def wait(panel: AtlasPanel, action: Callable[[], object], seconds: int = 30) -> bool:
        """Run `action`, then the event loop until `finished` (False on timeout)."""
        loop = QEventLoop()
        result: list[bool] = []

        def done(ok: bool) -> None:
            result.append(ok)
            loop.quit()

        panel.finished.connect(done)
        QTimer.singleShot(0, action)
        QTimer.singleShot(seconds * 1000, loop.quit)
        loop.exec()
        panel.finished.disconnect(done)
        return bool(result and result[0])


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class AtlasPanelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.panel = AtlasPanel()
        self.addCleanup(dispose, self.panel)

    def load(self, name: str) -> None:
        self.assertTrue(wait(self.panel, lambda: self.panel.open_file(DATA / name)))

    def test_empty(self) -> None:
        self.assertIsNone(self.panel.atlas_a)
        self.assertIn("No atlas loaded", self.panel.status.text())

    def test_open_file_lists_runs(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        p = self.panel
        designs = [p.design.itemText(i) for i in range(p.design.count())]
        self.assertEqual(designs, ["ch_intrinsics", "diffeq1"])
        self.assertEqual(p.design.currentText(), "diffeq1")
        self.assertEqual((p.arm_a.currentText(), p.arm_b.currentText()), ("stock", "h1"))
        a = p.atlas_a
        self.assertIsNotNone(a)
        assert a is not None
        self.assertEqual(set(p.view_a.items_by_clb), {c.id for c in a.clbs})
        self.assertTrue(p.view_b.isHidden())
        self.assertGreater(p.last_draw_s, 0.0)

    def test_hover_text(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        v = self.panel.view_a
        a = v.atlas
        assert a is not None
        clb = a.clbs[0]
        text = v.text_for(clb.id)
        self.assertIn(f"at ({clb.x}, {clb.y})", text)
        self.assertIn("pcrit", text)
        self.assertEqual(v.text_for(-5), "")

    def test_clb_at_position(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        v = self.panel.view_a
        a = v.atlas
        assert a is not None
        clb = a.clbs[0]
        pt = v.mapFromScene(v.items_by_clb[clb.id].sceneBoundingRect().center())
        self.assertEqual(v.clb_at(pt.x(), pt.y()), clb.id)

    def test_every_key_draws(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        for i in range(self.panel.key.count()):
            self.panel.key.setCurrentIndex(i)
            self.panel.redraw()
            atl = self.panel.view_a.atlas
            assert atl is not None
            self.assertEqual(len(self.panel.view_a.items_by_clb), len(atl.clbs))

    def test_highlight(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        p = self.panel
        p.key.setCurrentText("word")
        p._key_changed()
        self.assertGreater(p.values.count(), 0)
        p.values.setCurrentRow(0)
        value = p.selected_value()
        a = p.atlas_a
        assert a is not None and value is not None
        want = atlas.clbs_with(a, "word", value)
        self.assertGreater(len(want), 0)
        thick = {i for i, it in p.view_a.items_by_clb.items() if it.pen().width() == 3}
        self.assertEqual(thick, want)
        p.clear_button.click()
        self.assertIsNone(p.selected_value())

    def test_side_by_side_seed_fallback_warns(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        p = self.panel
        p.mode.setCurrentIndex(1)
        self.assertTrue(wait(p, lambda: p.request()))
        self.assertFalse(p.view_b.isHidden())
        self.assertEqual(p.atlas_b.arm if p.atlas_b else "", "h1")  # seed 1 absent: first seed
        self.assertIn("WARNING", p.label_b.text())
        self.assertIn("WARNING", p.info.text())

    def test_diff_needs_same_seed(self) -> None:
        self.load("diffeq1.stock.s1.json.gz")
        p = self.panel
        p.mode.setCurrentIndex(2)
        p.request()
        self.assertIsNone(p.atlas_b)
        self.assertIn("no B file", p.label_b.text())
        self.assertEqual(len(p.view_b.items_by_clb), 0)

    def test_diff_modes_same_seed(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            for arm, src in (("stock", "diffeq1.stock.s1"), ("h1", "diffeq1.stock.s1")):
                (Path(t) / f"diffeq1.{arm}.s1.json.gz").write_bytes(
                    (DATA / f"{src}.json.gz").read_bytes()
                )
            self.assertTrue(wait(self.panel, lambda: self.panel.scan(Path(t))))
            p = self.panel
            p.mode.setCurrentIndex(2)
            self.assertTrue(wait(p, lambda: p.request()))
            self.assertIn("co-membership", p.info.text())
            self.assertIn("0 of", p.info.text())
            p.mode.setCurrentIndex(3)
            self.assertTrue(wait(p, lambda: p.request()))
            self.assertIn("position changed", p.info.text())

    def test_open_file_does_not_glob_above(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            sub = Path(t) / "a" / "b" / "c"
            sub.mkdir(parents=True)
            (Path(t) / "x.stock.s9.json").write_bytes(b"{}")
            f = sub / "d.stock.s1.json.gz"
            f.write_bytes((DATA / "diffeq1.stock.s1.json.gz").read_bytes())
            self.assertTrue(wait(self.panel, lambda: self.panel.open_file(f)))
            self.assertEqual([r.design for r in self.panel.runs], ["d"])

    def test_cache_key_follows_file_change(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "d.stock.s1.json.gz"
            f.write_bytes((DATA / "diffeq1.stock.s1.json.gz").read_bytes())
            self.assertTrue(wait(self.panel, lambda: self.panel.open_file(f)))
            first = len(self.panel.atlas_a.clbs) if self.panel.atlas_a else 0
            f.write_bytes((DATA / "ch_intrinsics.stock.s1.json.gz").read_bytes())
            self.assertTrue(wait(self.panel, lambda: self.panel.request()))
            self.assertNotEqual(len(self.panel.atlas_a.clbs) if self.panel.atlas_a else 0, first)

    def test_scan_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            d = Path(t) / "x" / "atlas"
            d.mkdir(parents=True)
            (d / "stock.s1.json.gz").write_bytes((DATA / "diffeq1.stock.s1.json.gz").read_bytes())
            self.assertTrue(wait(self.panel, lambda: self.panel.scan(Path(t))))
            self.assertEqual(self.panel.design.currentText(), "x")
        self.assertEqual(self.panel.scan(Path("/nonexistent-atlas-root")), 0)

    def test_bad_file(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "bad.json"
            p.write_text("{}", encoding="utf-8")
            self.assertFalse(wait(self.panel, lambda: self.panel.open_file(p)))
            self.assertIn("bad.json", self.panel.status.text())
