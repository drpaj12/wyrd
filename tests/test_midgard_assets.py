import hashlib
import importlib.util
import os
import unittest
import zipfile
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parent.parent
ASSETS = ROOT / "wyrd" / "midgard" / "assets"
ZIP = Path(
    os.environ.get(
        "MIDGARD_ZIP",
        str(Path.home() / "odin3-ws/ODIN_III_v2_EXAMPLES/verilogTown-master.zip"),
    )
)
P = "verilogTown-master/"
ANDROID = P + "VERILOG_TOWN/verilogTown-android/assets/"


def load_tool() -> ModuleType:
    path = ROOT / "tools" / "import_midgard_assets.py"
    spec = importlib.util.spec_from_file_location("import_midgard_assets", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IncludeRulesTest(unittest.TestCase):
    def test_include_rules(self) -> None:
        inc = load_tool().include
        self.assertEqual(inc(ANDROID + "data/stop_tran.png"), "data/stop_tran.png")
        self.assertIsNone(inc(ANDROID + "data/car_sheet1.png"))
        self.assertEqual(inc(ANDROID + "ASSET_RESOURCES/level12_normal.png"),
                         "ASSET_RESOURCES/level12_normal.png")
        self.assertIsNone(inc(ANDROID + "ASSET_RESOURCES/level13_normal.png"))
        self.assertEqual(inc(ANDROID + "ASSET_RESOURCES/score_level3_pressed.png"),
                         "ASSET_RESOURCES/score_level3_pressed.png")
        self.assertIsNone(inc(ANDROID + "ASSET_RESOURCES/score_level3_normal.png"))
        self.assertIsNone(inc(ANDROID + "ASSET_RESOURCES/score_level3_mouse_on.png"))
        self.assertIsNone(inc(ANDROID + "ASSET_RESOURCES/verilogTown.png"))
        self.assertIsNone(inc(ANDROID + "ASSET_RESOURCES/localHighScore.png"))
        self.assertEqual(inc(P + "Levels/Lv7/map/lv07.xml"), "levels/Lv7/lv07.xml")
        self.assertIsNone(inc(P + "Levels/Lv7/VerilogFiles/Traffic_signal_set_0.v"))
        self.assertIsNone(inc(P + "VERILOG_TOWN/verilogTown-desktop/assets/x.png"))
        le = P + "VERILOG_TOWN/LevelEditor/src/images/"
        self.assertEqual(inc(le + "FOUR_WAY.png"), "editors/ledit/FOUR_WAY.png")
        ve = P + "VERILOG_TOWN/VerilogEditor/src/images/"
        self.assertEqual(inc(ve + "save.png"), "editors/vedit/save.png")
        self.assertEqual(inc(ve + "go_n.png"), "editors/vedit/go_n.png")
        self.assertIsNone(inc(ve + "upload.png"))
        self.assertIsNone(inc(ve + "middle.gif"))

    def test_make_starter(self) -> None:
        text = "module light1 (clk, rst, outN, outS, outE, outW, sensor_light, general_sensors);\n"
        out: str = load_tool().make_starter(text)
        self.assertTrue(out.startswith("// Midgard III: rst is active low"))
        self.assertIn("general_sensors, debug_port);", out.splitlines()[3])


@unittest.skipUnless(ZIP.exists(), "verilogTown zip not available")
class ZipTest(unittest.TestCase):
    def test_zip_counts(self) -> None:
        tool = load_tool()
        sizes: dict[str, list[int]] = {}
        with zipfile.ZipFile(ZIP) as z:
            for info in z.infolist():
                dest = tool.include(info.filename)
                if dest is None:
                    continue
                key = dest.split("/")[0]
                if key == "levels":
                    key += "." + dest.rsplit(".", 1)[1]
                sizes.setdefault(key, []).append(info.file_size)
            authored = tool.authored(z)
        got = {k: (len(v), sum(v)) for k, v in sizes.items()}
        self.assertEqual(got["data"], (55, 1342253))
        self.assertEqual(got["ASSET_RESOURCES"], (82, 2628922))
        self.assertEqual(got["levels.png"], (13, 5414307))
        self.assertEqual(got["levels.xml"], (13, 322333))
        self.assertEqual(got["editors"], (45, 52822 + 211001))
        self.assertEqual(sum(n for n, _ in got.values()), 208)
        self.assertEqual(sum(b for _, b in got.values()), 9971638)
        self.assertEqual(
            set(authored),
            {"starter.v", "examples/constant_outputs.v", "templates/combinational.v",
             "templates/sequential.v"},
        )
        self.assertIn("general_sensors, debug_port);", authored["templates/combinational.v"])


class CommittedTreeTest(unittest.TestCase):
    def manifest(self) -> list[tuple[str, int, str]]:
        rows = []
        for line in (ASSETS / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
            sha, size, path = line.split("  ", 2)
            rows.append((sha, int(size), path))
        return rows

    def test_manifest_matches_tree(self) -> None:
        rows = self.manifest()
        self.assertEqual(len(rows), 208)
        self.assertEqual(sum(r[1] for r in rows), 9971638)
        self.assertEqual([r[2] for r in rows], sorted(r[2] for r in rows))
        for sha, size, path in rows:
            data = (ASSETS / path).read_bytes()
            self.assertEqual(len(data), size, path)
            self.assertEqual(hashlib.sha256(data).hexdigest(), sha, path)
        listed = {r[2] for r in rows}
        on_disk = {
            p.relative_to(ASSETS).as_posix()
            for top in ("data", "ASSET_RESOURCES", "levels")
            for p in (ASSETS / top).rglob("*")
            if p.is_file()
        }
        self.assertEqual(on_disk, {p for p in listed if p.split("/")[0] != "editors"})
        font = ASSETS / "fonts"
        self.assertTrue(
            (font / "OFL.txt").read_text(encoding="utf-8").startswith(
                "Copyright (c) 2011, Font Diner, Inc (diner@fontdiner.com),"
            )
        )
        ttf = font / "Creepster-Regular.ttf"
        self.assertTrue(ttf.exists())
        self.assertLess(ttf.stat().st_size, 200_000)

    def test_authored_files(self) -> None:
        def text(rel: str) -> str:
            return (ASSETS / rel).read_text(encoding="utf-8")

        starter = text("starter.v")
        self.assertIn("general_sensors, debug_port);", starter)
        self.assertIn("// Midgard III:", starter)
        self.assertIn("sensor_light[6] == 1'b1", starter)
        const = text("examples/constant_outputs.v")
        self.assertIn("general_sensors, debug_port);", const)
        self.assertIn("outN = Left_only", const)
        self.assertIn("posedge clk", text("templates/sequential.v"))
        self.assertIn("always @(*)", text("templates/combinational.v"))
        notice = text("NOTICE")
        for needle in (
            "Copyright (c) 2014 Peter Jamieson, Naoki Mizuno, and Boyu Zhang",
            "Permission is hereby granted, free of charge",
            "John-Rhys Garcia",
            "Jamieson, Grace, Mizuno, Zhang, ASEE 2017",
        ):
            self.assertIn(needle, notice)
        self.assertIn("wyrd midgard", (ROOT / "NOTICE").read_text(encoding="utf-8"))

    def test_fixture_present(self) -> None:
        self.assertEqual(
            (ROOT / "tests" / "data" / "midgard" / "first_map.xml").stat().st_size, 44671
        )


if __name__ == "__main__":
    unittest.main()
