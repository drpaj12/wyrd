"""Hot/cold model: criticality, scope, ranges, bit split, colours, Mímir adapter (no Qt)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from wyrd.guimodel import heat, heatmimir, heatview
from wyrd.guimodel.heat import Scope
from wyrd.guimodel.timing import TimingError

DATA = Path(__file__).parent / "data" / "heat"
ADDER = DATA / "bm_DL_BCD_adder.attribution.json"

BUS_SRC = (
    "module top(input [2:0] SIGNAL, output y);\n"
    "  assign y = SIGNAL[2] ^ SIGNAL[1] ^ SIGNAL[0];  // SIGNAL\n"
    "endmodule\n"
)


def _node(
    span: str | None, word: str | None, bit: int | None, via: str | None
) -> dict[str, object]:
    return {
        "span": span,
        "module": "top",
        "word": word,
        "bit": bit,
        "word_via": via,
        "delay_ns": 0.5,
    }


def _path(index: int, slack: float, nodes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "index": index,
        "slack_ns": slack,
        "required_ns": 0.0,
        "startpoint": "a (.input clocked by clk)",
        "endpoint": f"e{index} (.output clocked by clk)",
        "nodes": nodes,
    }


def bus_model(second_slack: float = -1.0) -> heat.HeatModel:

    def pad(b: int) -> dict[str, object]:
        return _node(None, "SIGNAL", b, "pad")

    def use(b: int) -> dict[str, object]:
        return _node("top.v:2", "SIGNAL", b, "name")

    paths = [
        _path(1, -2.0, [pad(2), pad(0), use(2), use(0)]),
        _path(2, second_slack, [pad(1), use(1)]),
    ]
    return heat.parse_heat({"schema_version": 1, "paths": paths, "words": []})


class CritTest(unittest.TestCase):
    def test_hand_computed(self) -> None:
        rows = [heat.PathRow(i, "a (x clocked by c)", "b (y clocked by c)", s, 0.0)
                for i, s in ((1, -4.0), (2, -3.0), (3, -1.0))]
        crit, pairs, skipped = heat.path_criticalities(rows)
        self.assertEqual((pairs, skipped), (1, 0))
        self.assertAlmostEqual(crit[1], 1.0)
        self.assertAlmostEqual(crit[2], 0.75)
        self.assertAlmostEqual(crit[3], 0.25)

    def test_positive_slack_is_one_minus_slack_over_req(self) -> None:
        rows = [heat.PathRow(1, "a", "b", 1.0, 10.0), heat.PathRow(2, "a", "b", 4.0, 10.0)]
        crit, _, _ = heat.path_criticalities(rows)
        self.assertAlmostEqual(crit[1], 0.9)
        self.assertAlmostEqual(crit[2], 0.6)

    def test_pairs_are_separate_and_negative_denominator_skipped(self) -> None:
        rows = [heat.PathRow(1, "a (x clocked by c1)", "b (y clocked by c1)", -2.0, 0.0),
                heat.PathRow(2, "a (x clocked by c2)", "b (y clocked by c2)", -1.0, 0.0),
                heat.PathRow(3, "a (x clocked by c3)", "b (y clocked by c3)", -1.0, -5.0)]
        crit, pairs, skipped = heat.path_criticalities(rows)
        self.assertEqual((pairs, skipped), (3, 1))
        self.assertEqual((crit[1], crit[2]), (1.0, 1.0))
        self.assertNotIn(3, crit)

    def test_fixture_adder(self) -> None:
        model = heat.load_heat(ADDER)
        self.assertEqual(len(model.paths), 10)
        self.assertAlmostEqual(model.paths[1].crit, 1.0)
        # slack -2.941 of worst -4.619, max_req 0
        self.assertAlmostEqual(model.paths[5].crit, 1 - (-2.941 + 4.619) / 4.619, places=6)

    def test_bad_schema(self) -> None:
        with self.assertRaises(TimingError):
            heat.parse_heat({"schema_version": 2})
        with self.assertRaises(TimingError):
            heat.parse_heat([])


class ScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.model = heat.load_heat(ADDER)

    def test_critical_is_rank_zero(self) -> None:
        facts = self.model.select(Scope(heat.SCOPE_CRITICAL))
        self.assertTrue(facts)
        self.assertEqual({f.path for f in facts}, {1})

    def test_top_n(self) -> None:
        facts = self.model.select(Scope(heat.SCOPE_TOP, n=3))
        self.assertEqual({f.path for f in facts}, {1, 2, 3})

    def test_theta(self) -> None:
        low = self.model.select(Scope(heat.SCOPE_NEAR, theta=0.90))
        high = self.model.select(Scope(heat.SCOPE_NEAR, theta=0.999))
        self.assertTrue(all(f.crit >= 0.90 for f in low))
        self.assertLess(len(high), len(low))
        self.assertEqual({f.path for f in low}, {1, 2})  # crit of path 2 = 0.995, path 3 = 0.866

    def test_second_fixture_loads(self) -> None:
        model = heat.load_heat(DATA / "bm_DL_logic_w_Dff.attribution.json")
        self.assertTrue(model.select(Scope()))


class BitSplitTest(unittest.TestCase):
    def heat(self, scope: Scope, src: str = BUS_SRC, msb: bool = True) -> heatview.FileHeat:
        model = bus_model()
        return heatview.build_file_heat(model, model.select(scope), {"top.v"}, src, msb)

    def decl(self, h: heatview.FileHeat) -> heatview.HeatRange:
        found = [r for r in h.ranges if r.line == 1]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_rbr_split_on_declaration(self) -> None:
        r = self.decl(self.heat(Scope(heat.SCOPE_CRITICAL)))
        self.assertEqual(r.word, "SIGNAL")
        pieces = [(r.word[s.col_start - r.col_start:s.col_end - r.col_start], s.bit, s.crit)
                  for s in r.segments]
        self.assertEqual(pieces, [("SI", 2, 1.0), ("GN", 1, 0.0), ("AL", 0, 1.0)])

    def test_lsb_first_setting(self) -> None:
        r = self.decl(self.heat(Scope(heat.SCOPE_CRITICAL), msb=False))
        self.assertEqual([s.bit for s in r.segments], [0, 1, 2])

    def test_all_paths_make_bit_hot(self) -> None:
        r = self.decl(self.heat(Scope(heat.SCOPE_TOP, n=2)))
        self.assertEqual([s.crit for s in r.segments], [1.0, 0.5, 1.0])

    def test_use_line_token_and_comment_skipped(self) -> None:
        h = self.heat(Scope(heat.SCOPE_CRITICAL))
        cols = [(r.col_start, r.col_end) for r in h.ranges if r.line == 2]
        self.assertEqual(len(cols), 3)  # three uses; the one in the comment is skipped
        self.assertIn(2, h.lines)
        self.assertEqual(h.line_paths[2], (1,))

    def test_width_over_identifier_length_gives_strip(self) -> None:
        src = "module top(input [9:0] AB, output y);\n  assign y = &AB;\nendmodule\n"
        def pad(b: int) -> dict[str, object]:
            return _node(None, "AB", b, "pad")

        model = heat.parse_heat({"schema_version": 1, "words": [],
                                 "paths": [_path(1, -1.0, [pad(9), pad(3)])]})
        h = heatview.build_file_heat(model, model.select(Scope()), {"x.v"}, src)
        r = next(r for r in h.ranges if r.line == 1)
        self.assertEqual(r.segments, ())
        self.assertEqual(len(r.strip), 10)
        self.assertEqual(r.strip[0], (9, 1.0))
        self.assertEqual(dict(r.strip)[5], 0.0)

    def test_unknown_bits_marker(self) -> None:
        paths = [_path(1, -1.0, [_node("top.v:2", "SIGNAL", None, "declarator")])]
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": paths})
        h = heatview.build_file_heat(model, model.select(Scope()), {"top.v"}, BUS_SRC)
        rs = [r for r in h.ranges if r.line == 2]
        self.assertTrue(rs)
        self.assertTrue(all(r.unknown_bits and not r.segments for r in rs))
        self.assertIn("bit unknown", rs[0].tooltip)

    def test_json_id_bit_not_used(self) -> None:
        paths = [_path(1, -1.0, [_node("top.v:2", "SIGNAL", 2, "json-id")])]
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": paths})
        h = heatview.build_file_heat(model, model.select(Scope()), {"top.v"}, BUS_SRC)
        self.assertTrue(all(r.unknown_bits for r in h.ranges))

    def test_unplaced_pad(self) -> None:
        model = bus_model()
        src = "module top;\nendmodule\n"
        h = heatview.build_file_heat(model, model.select(Scope()), {"top.v"}, src)
        self.assertEqual(h.unplaced, ["top.SIGNAL"])

    def test_wrong_file_gets_nothing(self) -> None:
        model = bus_model()
        h = heatview.build_file_heat(model, model.select(Scope()), {"other.v"}, BUS_SRC)
        self.assertEqual((h.lines, h.ranges), ({}, []))

    def test_segment_sizes(self) -> None:
        self.assertEqual(heatview.segment_sizes(6, 3), [2, 2, 2])
        self.assertEqual(heatview.segment_sizes(7, 3), [3, 2, 2])

    def test_declared_range(self) -> None:
        lines = ["input [7:4] a, output b", "wire [3:0] c, d;", "reg e;"]
        self.assertEqual(heatview.declared_range("a", lines), (7, 4))
        self.assertIsNone(heatview.declared_range("b", lines))
        self.assertEqual(heatview.declared_range("d", lines), (3, 0))
        self.assertIsNone(heatview.declared_range("e", lines))


class ColourTest(unittest.TestCase):
    def test_ends_and_middle(self) -> None:
        self.assertEqual(heatview.crit_hex(0.0), "#2c7bb6")
        self.assertEqual(heatview.crit_hex(1.0), "#d7191c")
        self.assertEqual(heatview.crit_hex(0.5), "#ffffbf")
        self.assertEqual(heatview.crit_hex(2.0), "#d7191c")

    def test_red_dominates_when_hot_blue_when_cold(self) -> None:
        hot, cold = heatview.crit_rgb(0.95), heatview.crit_rgb(0.05)
        self.assertGreater(hot[0], hot[2])
        self.assertGreater(cold[2], cold[0])

    def test_text_contrast(self) -> None:
        self.assertTrue(heatview.text_is_dark(heatview.crit_rgb(0.5)))
        self.assertFalse(heatview.text_is_dark(heatview.crit_rgb(1.0)))


class MimirAdapterTest(unittest.TestCase):
    ROWS = [
        ("span", "top.v:2", -1, "", 0.97),
        ("word", "top/SIGNAL", -1, "name", 0.97),
        ("word", "top/SIGNAL", 2, "name", 0.97),
        ("word", "top/SIGNAL", 0, "pad", 0.92),
        ("module", "top", -1, "", 0.97),
    ]

    def test_model_and_scope(self) -> None:
        model = heatmimir.model_from_objects(self.ROWS)
        self.assertFalse(model.has_paths)
        self.assertEqual(model.select(Scope(heat.SCOPE_CRITICAL)), [])
        self.assertEqual(len(model.select(Scope(heat.SCOPE_NEAR, theta=0.95))), 2)

    def test_colours_declaration_bits(self) -> None:
        model = heatmimir.model_from_objects(self.ROWS)
        facts = model.select(Scope(heat.SCOPE_NEAR))
        h = heatview.build_file_heat(model, facts, {"top.v"}, BUS_SRC)
        r = next(r for r in h.ranges if r.line == 1)
        self.assertEqual([s.crit for s in r.segments], [0.97, 0.0, 0.92])
        self.assertEqual(h.lines, {2: 0.97})

    def test_real_json_round_trip(self) -> None:
        data = json.loads(ADDER.read_text(encoding="utf-8"))
        self.assertEqual(heat.parse_heat(data).facts, heat.load_heat(ADDER).facts)


TWO_MODULES = (
    "module a(input [7:0] data, output y);\n"
    "endmodule\n"
    "module b(input [3:0] data, output z);\n"
    "endmodule\n"
)


def _mimir_rows(module: str) -> list[tuple[str, str, int, str, float]]:
    return [
        ("span", "top.v:2", -1, "", 0.97),
        ("word", f"{module}/data", 3, "name", 1.0),
        ("word", f"{module}/data", 0, "name", 0.1),
    ]


class FixRoundTest(unittest.TestCase):
    def mimir(self, module: str, text: str, names: set[str]) -> heatview.FileHeat:
        model = heatmimir.model_from_objects(_mimir_rows(module))
        return heatview.build_file_heat(model, model.select(Scope(heat.SCOPE_NEAR)), names, text)

    def test_h1_unrelated_file_gets_nothing(self) -> None:
        h = self.mimir("a", TWO_MODULES, {"other.v"})
        self.assertEqual((h.lines, h.ranges), ({}, []))

    def test_h1_only_matching_module(self) -> None:
        h = self.mimir("b", TWO_MODULES, {"top.v"})
        self.assertEqual([r.line for r in h.ranges], [3])
        self.assertEqual(len(h.ranges[0].segments), 4)  # [3:0] of module b

    def test_h1_module_missing_in_file_is_unplaced(self) -> None:
        h = self.mimir("zz", TWO_MODULES, {"top.v"})
        self.assertEqual(h.ranges, [])
        self.assertEqual(h.unplaced, ["zz.data"])

    def test_m1_unknown_bit_keeps_known_bits(self) -> None:
        paths = [_path(1, -1.0, [_node("top.v:2", "SIGNAL", 2, "name"),
                                 _node("top.v:2", "SIGNAL", None, "declarator")])]
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": paths})
        h = heatview.build_file_heat(model, model.select(Scope()), {"top.v"}, BUS_SRC)
        r = next(r for r in h.ranges if r.line == 2)
        self.assertTrue(r.unknown_bits)
        self.assertEqual([s.crit for s in r.segments], [1.0, 0.0, 0.0])

    def test_m2_declared_range_per_module(self) -> None:
        lines = TWO_MODULES.split("\n")
        self.assertEqual(heatview.declared_range("data", lines, None, (1, 2)), (7, 0))
        self.assertEqual(heatview.declared_range("data", lines, None, (3, 4)), (3, 0))
        self.assertIsNone(heatview.declared_range("data", lines))  # ambiguous
        self.assertEqual(heatview.module_range("b", lines), (3, 4))
        self.assertIsNone(heatview.module_range("c", lines))

    def test_m2_attribution_uses_module_width(self) -> None:
        def pad(b: int) -> dict[str, object]:
            n = _node(None, "data", b, "pad")
            n["module"] = "b"
            return n

        model = heat.parse_heat({"schema_version": 1, "words": [],
                                 "paths": [_path(1, -1.0, [pad(3), pad(0)])]})
        model = heat.HeatModel(model.facts, model.paths, model.seen_width, {})
        h = heatview.build_file_heat(model, model.select(Scope()), {"x.v"}, TWO_MODULES)
        r = next(r for r in h.ranges if r.line == 3)
        self.assertEqual([s.bit for s in r.segments], [3, 2, 1, 0][:len(r.segments)])

    def test_l1_skipped_pair_at_rank_zero_keeps_scope(self) -> None:
        bad = _path(1, 1.0, [_node("top.v:2", "SIGNAL", 0, "name")])
        bad["required_ns"] = -5.0
        bad["startpoint"] = "q (.input clocked by other)"
        good = _path(2, -1.0, [_node("top.v:2", "SIGNAL", 0, "name")])
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": [bad, good]})
        self.assertEqual({f.path for f in model.select(Scope(heat.SCOPE_CRITICAL))}, {2})

    def test_l1_rank_by_crit_then_slack(self) -> None:
        a = _path(1, 0.5, [_node("top.v:2", "SIGNAL", 0, "name")])
        b = _path(2, -1.0, [_node("top.v:2", "SIGNAL", 0, "name")])
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": [a, b]})
        self.assertEqual({f.path for f in model.select(Scope(heat.SCOPE_CRITICAL))}, {2})

    def test_l2_declaration_skips_comments(self) -> None:
        text = "// input a\nmodule m(input a);\nendmodule\n"
        lines = text.split("\n")
        mask = heatview._code_mask(text)
        self.assertEqual(heatview.declaration_line("a", lines), 1)
        self.assertEqual(heatview.declaration_line("a", lines, mask), 2)

    def test_l3_bits_beyond_declared_width(self) -> None:
        src = "module top(input [1:0] AB, output y);\nendmodule\n"
        paths = [_path(1, -1.0, [_node(None, "AB", 3, "pad"), _node(None, "AB", 0, "pad")])]
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": paths})
        h = heatview.build_file_heat(model, model.select(Scope()), {"x.v"}, src)
        r = next(r for r in h.ranges if r.line == 1)
        self.assertTrue(r.beyond_width)
        self.assertEqual([b for b, _ in r.strip or tuple((s.bit, 0.0) for s in r.segments)],
                         [3, 1, 0])
        self.assertIn("outside the declared width", r.tooltip)

    def test_l6_rounding_before_theta(self) -> None:
        self.assertEqual(heat.round_crit(0.8999999999), 0.9)
        row = ("span", "top.v:2", -1, "", 0.8999999999)
        model = heatmimir.model_from_objects([row])
        self.assertEqual(len(model.select(Scope(heat.SCOPE_NEAR, theta=0.9))), 1)

    def test_l9_single_bit_zero_is_not_whole_token_hot(self) -> None:
        src = "module top(input SIGNALX, output y);\nendmodule\n"
        paths = [_path(1, -1.0, [_node(None, "SIGNALX", 0, "pad")])]
        model = heat.parse_heat({"schema_version": 1, "words": [], "paths": paths})
        h = heatview.build_file_heat(model, model.select(Scope()), {"x.v"}, src)
        r = next(r for r in h.ranges if r.line == 1)
        self.assertTrue(r.unknown_bits)
        self.assertEqual([s.crit for s in r.segments], [heatview.UNKNOWN_CRIT, 1.0])
        self.assertEqual(r.segments[-1].bit, 0)

    def test_l7_utf16_columns(self) -> None:
        text = "a\U0001F600b x"
        self.assertEqual(heatview.utf16_col(text, 3), 4)
        self.assertEqual(heatview.codepoint_col(text, 4), 3)
        self.assertEqual(heatview.codepoint_col(text, 1), 1)
        self.assertEqual(heatview.codepoint_col("ab", 9), 2)

    def test_l7_big_file_builds_fast(self) -> None:
        import time

        n = 3000
        src = "module top(input [2:0] SIGNAL, output y);\n" + "  assign y = SIGNAL[1];\n" * n
        nodes = [_node(f"top.v:{i + 2}", "SIGNAL", i % 3, "name") for i in range(n)]
        model = heat.parse_heat({"schema_version": 1, "words": [],
                                 "paths": [_path(1, -1.0, nodes)]})
        t = time.monotonic()
        heatview.build_file_heat(model, model.select(Scope()), {"top.v"}, src)
        self.assertLess(time.monotonic() - t, 5.0)  # was quadratic: 10k lines took 59 s

    def test_l4_note_states_remainder_rule(self) -> None:
        self.assertIn("extra characters to the leading segments", heatview.LEGEND_NOTE)


if __name__ == "__main__":
    unittest.main()
