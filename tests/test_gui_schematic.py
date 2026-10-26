"""Schematic panel; Qt runs offscreen. Fixtures: tests/data/schematic, a fake netlistsvg."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests.test_schematic import DATA, fake_tool
from wyrd import schematic

HAVE_QT = importlib.util.find_spec("PySide6") is not None

if HAVE_QT:
    from tests.qt_helpers import dispose, qapp
    from wyrd.gui.schematicpanel import NO_NETLIST, SchematicPanel

    def setUpModule() -> None:
        qapp()


@unittest.skipUnless(HAVE_QT, "PySide6 not installed")
class SchematicPanelTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.panel = SchematicPanel(fake_tool(self.tmp), auto_tools=False)
        self.addCleanup(dispose, self.panel)

    def test_initial(self) -> None:
        self.assertEqual(self.panel.status.text(), NO_NETLIST)
        self.assertFalse(self.panel.draw_button.isEnabled())
        self.assertFalse(self.panel.draw())

    def test_load_and_draw_module(self) -> None:
        self.panel.load(DATA / "dag2.json")
        self.assertEqual(self.panel.module.count(), 3)
        self.assertIn("bm_dag2_mod", self.panel.module.itemText(0))
        self.assertTrue(self.panel.draw())
        self.assertIn("6 cells drawn", self.panel.status.text())
        self.assertTrue(self.panel.svg.renderer().isValid())
        self.assertGreater(self.panel.svg.width(), 0)

    def test_draw_cone_of_net_and_line(self) -> None:
        self.panel.load(DATA / "dag2.json")
        self.panel.target.setText("out0")
        self.assertTrue(self.panel.draw())
        self.assertIn("(cone): 4 cells", self.panel.status.text())
        self.panel.target.setText("bm_dag2_mod.v:33")
        self.assertTrue(self.panel.draw())
        self.assertIn("1 cells", self.panel.status.text())

    def test_too_large_and_bad_target(self) -> None:
        self.panel.load(DATA / "dag2.json")
        self.panel.max_cells.setValue(3)
        self.assertFalse(self.panel.draw())
        self.assertIn("fan-in cone", self.panel.status.text())
        self.panel.target.setText("a_in")
        self.assertFalse(self.panel.draw())
        self.assertIn("not driven", self.panel.status.text())

    def test_set_run_finds_netlist(self) -> None:
        out = self.tmp / "step" / "out"
        out.mkdir(parents=True)
        (out / "n.json").write_bytes((DATA / "mux.json").read_bytes())
        self.panel.set_run(self.tmp)
        self.assertEqual(self.panel.module.count(), 1)
        self.panel.set_run(None)
        self.assertEqual(self.panel.status.text(), NO_NETLIST)
        self.assertEqual(self.panel.module.count(), 0)

    def test_bad_file(self) -> None:
        bad = self.tmp / "bad.json"
        bad.write_text("[]", encoding="utf-8")
        self.panel.load(bad)
        self.assertFalse(self.panel.draw_button.isEnabled())

    def test_without_tool_says_how_to_install(self) -> None:
        panel = SchematicPanel(None, auto_tools=False)
        self.addCleanup(dispose, panel)
        panel.load(DATA / "mux.json")
        self.assertFalse(panel.draw())
        self.assertIn("npm install netlistsvg", panel.status.text())

    def test_real_tool(self) -> None:
        tools = schematic.find_tools()
        if tools is None:
            self.skipTest("node and netlistsvg not installed")
        panel = SchematicPanel(tools, auto_tools=False)
        self.addCleanup(dispose, panel)
        panel.load(DATA / "dag2.json")
        self.assertTrue(panel.draw())
        self.assertGreater(panel.svg.width(), 50)


if __name__ == "__main__":
    unittest.main()
