"""o3viz viewer: vendored files are complete; headless smoke when Playwright and Chromium exist."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wyrd.o3viz import export, serve

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "o3viz"


class TestVendored(unittest.TestCase):
    def test_vendor_files_and_licence(self) -> None:
        v = serve.WEB / "vendor"
        for name in ("three.module.min.js", "OrbitControls.js", "three.LICENSE", "VERSIONS.txt"):
            self.assertTrue((v / name).is_file(), name)
        self.assertIn("MIT", (v / "three.LICENSE").read_text())

    def test_no_cdn_references(self) -> None:
        for name in ("index.html", "app.js"):
            text = (serve.WEB / name).read_text()
            self.assertNotIn("http://", text.replace("http://127", ""))
            self.assertNotIn("https://", text)


@unittest.skipUnless(importlib.util.find_spec("playwright"), "needs playwright and chromium")
class TestSmoke(unittest.TestCase):
    def test_loads_without_console_errors(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "o3viz_shot", ROOT / "tools" / "o3viz_shot.py"
        )
        assert spec is not None and spec.loader is not None
        o3viz_shot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(o3viz_shot)

        with tempfile.TemporaryDirectory() as d:
            bundle = Path(d) / "b.o3viz"
            export.export_bundle(DATA / "flow", bundle, "test:t", [DATA / "src"])
            shot = Path(d) / "s.png"
            errors = o3viz_shot.shoot(bundle, shot, "logic_level", "placed:hl2")
            self.assertEqual(errors, [])
            self.assertGreater(shot.stat().st_size, 5000)


if __name__ == "__main__":
    unittest.main()
