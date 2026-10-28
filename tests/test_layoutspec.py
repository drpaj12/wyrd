"""Layout presets and the Wyrd guide text (no Qt needed)."""

import unittest
from pathlib import Path

from wyrd.guimodel import layoutspec as ls
from wyrd.guimodel import mimirhelp, panelhelp

ROOT = Path(__file__).parent.parent


class PresetTest(unittest.TestCase):
    def test_presets_use_known_panels_and_areas_once(self) -> None:
        for p in ls.PRESETS:
            seen: list[str] = []
            for g in p.groups:
                self.assertIn(g.area, ls.AREAS)
                self.assertIn(g.current, g.docks)
                seen += g.docks
            self.assertEqual(len(seen), len(set(seen)), p.name)
            self.assertTrue(set(seen) <= set(ls.PANELS), p.name)
            self.assertEqual(sorted(seen + list(p.parked())), sorted(ls.PANELS), p.name)

    def test_named_presets(self) -> None:
        names = [p.name for p in ls.PRESETS]
        self.assertEqual(
            names, ["Project", "Timing + source", "Mímir explorer", "Everything tabbed"]
        )
        self.assertEqual(ls.DEFAULT_PRESET, "Project")
        self.assertIn(ls.MIMIR, ls.preset_named("Mímir explorer").shown())
        self.assertIn(ls.PROJECT, ls.preset_named("Mímir explorer").parked())
        self.assertEqual(ls.preset_named("Everything tabbed").parked(), ())
        with self.assertRaises(KeyError):
            ls.preset_named("nope")

    def test_zoom_and_version(self) -> None:
        self.assertEqual(ls.clamp_zoom(99), ls.ZOOM_MAX)
        self.assertEqual(ls.clamp_zoom(-99), ls.ZOOM_MIN)
        self.assertEqual(ls.parse_zoom("3"), 3)
        self.assertEqual(ls.parse_zoom("x"), 0)
        self.assertEqual(ls.parse_zoom(None), 0)
        self.assertTrue(ls.state_usable(str(ls.LAYOUT_VERSION)))
        self.assertFalse(ls.state_usable(ls.LAYOUT_VERSION + 1))
        self.assertFalse(ls.state_usable(None))


class PanelHelpTest(unittest.TestCase):
    def test_every_panel_has_four_parts(self) -> None:
        self.assertEqual(set(panelhelp.PANELS), set(ls.PANELS))
        for name, parts in panelhelp.PANELS.items():
            self.assertEqual(len(parts), len(mimirhelp.SECTIONS), name)
            self.assertTrue(all(len(t) > 40 for t in parts), name)

    def test_source_help_defines_the_heat_terms(self) -> None:
        text = " ".join(panelhelp.PANELS[ls.SOURCE]).lower()
        for term in ("red", "blue", "theta", "strip", "dotted underline"):
            self.assertIn(term, text)

    def test_guide_covers_every_panel_and_the_mimir_chapter(self) -> None:
        for name in ls.PANELS:
            self.assertIn(f"### {name}", panelhelp.GUIDE)
        self.assertIn(mimirhelp.GUIDE.strip(), panelhelp.GUIDE)

    def test_docs_page_carries_the_guide(self) -> None:
        doc = (ROOT / "docs" / "user" / "gui.md").read_text(encoding="utf-8")
        a, b = doc.index(panelhelp.GUIDE_BEGIN), doc.index(panelhelp.GUIDE_END)
        self.assertEqual(doc[a + len(panelhelp.GUIDE_BEGIN) : b].strip(), panelhelp.GUIDE.strip())


if __name__ == "__main__":
    unittest.main()
