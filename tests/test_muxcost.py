"""`wyrd mux-cost`: the report on committed Odin III outputs (hand-checked), the JSON schema, the
no-routing case, the routed select lateness on a synthetic timing report and the usage errors.

The fixtures in ``tests/data/muxcost/<name>/`` are the word-level snapshot and the mapped BLIF (with
their version 2 name maps) that ``wyrd mux-cost`` writes for ``tests/data/muxcost/src/<name>.v``
(Odin III 1.6.1, ``odin3-flow --prov --prov-cut`` script). A run through a real Odin III is
`TestRealOdin3`, skipped unless WYRD_TEST_ODIN3 and WYRD_TEST_ODIN3_FLOW name the programs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_cli import CliBase
from wyrd import cli
from wyrd.muxcost import blif, flow, logical, lutcost, netlist, provmap, render, report

DATA = Path(__file__).parent / "data" / "muxcost"
REAL = os.environ.get("WYRD_TEST_ODIN3"), os.environ.get("WYRD_TEST_ODIN3_FLOW")


def inputs(
    name: str, net_timing: Path | None = None, timing_optional: bool = False
) -> report.Inputs:
    d = DATA / name
    return report.Inputs(
        d / "snapshot.json",
        d / "snapshot.json.names",
        d / f"{name}.blif",
        d / f"{name}.blif.names",
        net_timing=net_timing,
        timing_optional=timing_optional,
    )


def table(doc: dict[str, object], key: str = "muxes") -> list[dict[str, object]]:
    found = doc[key]
    assert isinstance(found, list)
    return found


def wyrd(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def row_by_construct(doc: dict[str, object], kind: str) -> dict[str, object]:
    (found,) = [r for r in table(doc) if r["construct"] == kind]
    return found


class TestCaseTernary(unittest.TestCase):
    """case_tern.v: a 4-bit `case` (pmux, 3 arms and a constant default) and a 4-bit `?:`."""

    def setUp(self) -> None:
        self.doc = report.build(inputs("case_tern"))

    def test_totals(self) -> None:
        t = self.doc["totals"]
        assert isinstance(t, dict)
        self.assertEqual(t["logical_muxes"], 2)
        self.assertEqual(t["mux_cells"], 2)
        self.assertEqual(t["mux_bits"], 16)  # 4 x (4 - 1) + 4 x (2 - 1)
        self.assertEqual(t["luts"], 8)
        self.assertEqual(t["cuts"], {"exact": 8, "approx": 0, "none": 0})
        self.assertEqual(t["luts_attributed"], 8)

    def test_case_row(self) -> None:
        r = row_by_construct(self.doc, "case")
        self.assertEqual((r["file"], r["line"], r["span"]), ("case_tern.v", 5, "5.5-10.12"))
        self.assertEqual((r["kind"], r["width"], r["arms"], r["const_arms"]), ("$pmux", 4, 4, 1))
        self.assertEqual((r["dup_arms"], r["related_arms"], r["select_width"]), (0, 0, 3))
        self.assertEqual((r["mux_bits"], r["share"]), (12, 0.75))
        # 4 LUTs; each also covers the select decode cells ($eq, $logic_not), so all are shared.
        self.assertEqual((r["luts"], r["luts_shared"]), (4, 4))
        # per output bit: a, b, c and 3 select bits = 6 signals -> ceil(5 / 5) = 1 LUT; 4 bits
        self.assertEqual(r["lut_lower_bound"], 4)

    def test_ternary_row(self) -> None:
        r = row_by_construct(self.doc, "?:")
        self.assertEqual((r["line"], r["kind"], r["width"], r["arms"]), (14, "$mux", 4, 2))
        self.assertEqual((r["mux_bits"], r["share"], r["select_width"]), (4, 0.25, 1))
        self.assertEqual((r["luts"], r["luts_shared"], r["lut_lower_bound"]), (4, 0, 4))

    def test_constructs_rollup_sorted_by_bits(self) -> None:
        cons = table(self.doc, "constructs")
        self.assertEqual([c["construct"] for c in cons], ["case", "?:"])
        self.assertEqual([c["mux_bits"] for c in cons], [12, 4])

    def test_sort_luts_and_limit(self) -> None:
        doc = report.build(inputs("case_tern"), sort="luts", limit=1)
        rows = table(doc)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["luts"], 4)


class TestChain(unittest.TestCase):
    """chain.v: if / else if / else if / else over 4-bit words; arm `a` twice, a constant arm."""

    def test_one_logical_mux_of_three_cells(self) -> None:
        doc = report.build(inputs("chain"))
        (r,) = table(doc)
        self.assertEqual((r["construct"], r["line"], r["kind"], r["cells"]), ("if", 4, "$mux", 3))
        self.assertEqual((r["width"], r["arms"], r["const_arms"], r["dup_arms"]), (4, 4, 1, 1))
        self.assertEqual((r["mux_bits"], r["share"]), (12, 1.0))
        self.assertEqual((r["luts"], r["luts_shared"], r["lut_lower_bound"]), (4, 0, 4))


class TestShiftx(unittest.TestCase):
    """index.v: `v[idx]` on 8 bits is one $shiftx of 8 arms; its LUTs have approximate cuts."""

    def test_arms_bits_and_unattributed_luts(self) -> None:
        doc = report.build(inputs("index"))
        (r,) = table(doc)
        self.assertEqual(
            (r["construct"], r["kind"], r["arms"], r["select_width"]), ("index", "$shiftx", 8, 3)
        )
        self.assertEqual(r["mux_bits"], 7)
        self.assertEqual(r["lut_lower_bound"], 2)  # 8 data + 3 select = 11 signals: ceil(10 / 5)
        self.assertEqual(r["luts"], 0)
        t = doc["totals"]
        assert isinstance(t, dict)
        self.assertEqual(t["cuts"], {"exact": 0, "approx": 3, "none": 0})


class TestNoRouting(unittest.TestCase):
    def test_timing_columns_are_absent_not_zero(self) -> None:
        doc = report.build(inputs("case_tern"))
        self.assertFalse(doc["timing"])
        for row in table(doc):
            for key in ("sel_crit", "data_crit", "late", "witness"):
                self.assertNotIn(key, row)
        text = render.render(doc)
        self.assertNotIn("late", text.split("\n\n")[1])
        self.assertIn("No routed timing report", text)

    def test_sort_crit_needs_a_report(self) -> None:
        with self.assertRaises(report.ReportError):
            report.build(inputs("case_tern"), sort="crit")


MUX_KEYS = {
    "id", "kind", "cells", "construct", "file", "line", "span", "width", "arms", "const_arms",
    "dup_arms", "related_arms", "select_width", "mux_bits", "share", "luts", "luts_shared",
    "lut_lower_bound",
}  # fmt: skip
CONS_KEYS = {
    "construct", "file", "line", "span", "muxes", "mux_bits", "share", "arms", "luts",
    "luts_shared", "lut_lower_bound",
}  # fmt: skip


class TestJsonSchema(unittest.TestCase):
    def test_keys_and_types_are_stable(self) -> None:
        doc = json.loads(json.dumps(report.build(inputs("case_tern"))))
        self.assertEqual(
            set(doc),
            {
                "schema",
                "schema_version",
                "design",
                "totals",
                "sort",
                "timing",
                "muxes",
                "constructs",
            },
        )
        self.assertEqual((doc["schema"], doc["schema_version"]), ("wyrd-mux-cost", 1))
        self.assertEqual(doc["design"], {"top": "case_tern", "lut_k": 6})
        self.assertEqual(
            set(doc["totals"]),
            {"logical_muxes", "mux_cells", "mux_bits", "luts", "luts_attributed", "cuts"},
        )
        for row in doc["muxes"]:
            self.assertEqual(set(row), MUX_KEYS)
            self.assertIsInstance(row["share"], float)
            self.assertIsInstance(row["mux_bits"], int)
            self.assertIsInstance(row["file"], str)
        for row in doc["constructs"]:
            self.assertEqual(set(row), CONS_KEYS)

    def test_routed_adds_exactly_the_timing_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv = write_timing(Path(tmp), "case_tern", {})
            doc = report.build(inputs("case_tern", net_timing=csv))
        self.assertTrue(doc["timing"])
        self.assertIn("timing_note", doc)
        for row in table(doc):
            self.assertEqual(set(row), MUX_KEYS | {"sel_crit", "data_crit", "late", "witness"})
        for row in table(doc, "constructs"):
            self.assertEqual(set(row), CONS_KEYS | {"late"})

    def test_same_input_same_output(self) -> None:
        a = json.dumps(report.build(inputs("chain")), sort_keys=True)
        b = json.dumps(report.build(inputs("chain")), sort_keys=True)
        self.assertEqual(a, b)


def lut_of(name: str, latch_q: str) -> str:
    """The LUT atom that feeds the flip-flop named ``latch_q``."""
    text = (DATA / name / f"{name}.blif").read_text(encoding="utf-8")
    for line in text.splitlines():
        words = line.split()
        if words[:1] == [".latch"] and words[2] == latch_q:
            return words[1]
    raise AssertionError(latch_q)


def write_timing(
    tmp: Path, name: str, slack_ns: dict[tuple[str, int], float], default: float = 2.0
) -> Path:
    """A VPR-format report_net_timing.csv: every LUT input pin of the BLIF, slacks in seconds."""
    luts = blif.read(DATA / name / f"{name}.blif").luts
    lines = [
        "netname,Fanout,bb_xmin,bb_ymin,bb_layer_min,bb_xmax,bb_ymax,bb_layer_max,src_pin_name,src_pin_slack,sinks"
    ]
    for lut, ins in sorted(luts.items()):
        sinks = ";".join(
            f"{lut}.in[{i}],{slack_ns.get((lut, i), default) * 1e-9:.6e},1.0e-10"
            for i in range(len(ins))
        )
        lines.append(f'"n_{lut}",1,0,0,0,0,0,0,"x.out[0]",1.0e-9,"{sinks}"')
    path = tmp / "report_net_timing.csv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestRoutedLateness(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_select_against_data_pins(self) -> None:
        y0, z0 = lut_of("case_tern", "y[0]"), lut_of("case_tern", "z[0]")
        z1 = lut_of("case_tern", "z[1]")
        slack = {
            (y0, 3): 0.5,  # sel[0] pin of the case LUT of bit 0
            (y0, 0): 1.0,  # a[0] pin: the worst data pin of the case
            (z0, 2): 0.0,  # en pin of the ternary LUT of bit 0: worst pin of the design
            (z0, 0): 4.0, (z0, 1): 4.0,  # its data pins: the most relaxed
            (z1, 0): 4.0, (z1, 1): 4.0,
        }  # fmt: skip
        csv = write_timing(self.tmp, "case_tern", slack, default=2.0)
        doc = report.build(inputs("case_tern", net_timing=csv))
        # s_min 0.0, s_max 4.0: crit = (4 - slack) / 4
        case = row_by_construct(doc, "case")
        self.assertEqual((case["sel_crit"], case["data_crit"], case["late"]), (0.875, 0.75, 0.125))
        self.assertEqual(case["witness"], f"{y0}.in[3]")
        tern = row_by_construct(doc, "?:")
        self.assertEqual(
            (tern["sel_crit"], tern["late"]), (1.0, 0.5)
        )  # data: other bits at 2.0 -> 0.5
        self.assertIn(
            str(tern["witness"]), {f"{lut_of('case_tern', f'z[{i}]')}.in[2]" for i in range(4)}
        )

    def test_tie_witness_is_fixed_by_the_seed(self) -> None:
        csv = write_timing(self.tmp, "case_tern", {})
        a = report.build(inputs("case_tern", net_timing=csv))
        b = report.build(inputs("case_tern", net_timing=csv))
        self.assertEqual(row_by_construct(a, "?:")["witness"], row_by_construct(b, "?:")["witness"])

    def test_sort_by_crit_and_table_column(self) -> None:
        z0 = lut_of("case_tern", "z[0]")
        csv = write_timing(self.tmp, "case_tern", {(z0, 2): 0.0, (z0, 0): 4.0, (z0, 1): 4.0})
        doc = report.build(inputs("case_tern", net_timing=csv), sort="crit")
        self.assertEqual([r["construct"] for r in table(doc)], ["?:", "case"])
        self.assertIn("late", render.render(doc))

    def test_report_that_does_not_join_is_an_error(self) -> None:
        bad = self.tmp / "report_net_timing.csv"
        bad.write_text(
            "netname,Fanout,bb_xmin,bb_ymin,bb_layer_min,bb_xmax,bb_ymax,bb_layer_max,src_pin_name,src_pin_slack,sinks\n"
            '"n",1,0,0,0,0,0,0,"q.out[0]",1.0e-9,"other.in[0],1.0e-9,1.0e-10"\n',
            encoding="utf-8",
        )
        with self.assertRaises(report.ReportError):
            report.build(inputs("case_tern", net_timing=bad))
        doc = report.build(inputs("case_tern", net_timing=bad, timing_optional=True))
        self.assertFalse(doc["timing"])
        self.assertIn("notes", doc)


class TestPieces(unittest.TestCase):
    def test_name_map_header_and_escapes(self) -> None:
        with self.assertRaises(provmap.MapError):
            provmap.parse("# odin3-names 1 hash=sha256\n")
        self.assertEqual(provmap.unescape("a%09b%25"), "a\tb%")

    def test_lower_bound_formula(self) -> None:
        # 11 signals, K = 6: ceil(10 / 5) = 2 per output bit; one-signal and constant bits cost 0
        arms = tuple(tuple(i if k == 0 else "0" for k in range(1)) for i in range(2, 10))
        lm = logical.Logical("m", ("m",), arms, (20, 21, 22), 1, 7)
        self.assertEqual(lutcost.lower_bound(lm, 6), 2)
        self.assertEqual(lutcost.lower_bound(lm, 4), 4)  # ceil(10 / 3)
        const = logical.Logical("m", ("m",), (("0",), ("1",)), (5,), 1, 1)
        self.assertEqual(lutcost.lower_bound(const, 6), 0)  # one signal: a wire or an inverter

    def test_related_and_duplicate_arms(self) -> None:
        # {a1, a0, 0, 1} and {a1, a0, 1, 0}: differ in constant bits only
        arms = ((2, 3, "0", "1"), (2, 3, "1", "0"), (2, 3, "1", "0"), (4, 5, "0", "0"), ("0",) * 4)
        lm = logical.Logical("m", ("m",), arms, (9,), 4, 4)
        self.assertEqual(lm.related, 3)  # the three arms of the signature (2, 3, const, const)
        self.assertEqual(lm.dup_arms, 1)
        self.assertEqual(lm.const_arms, 1)

    def test_mux_arms_of_each_kind(self) -> None:
        mux: dict[str, object] = {"connections": {"A": [2, 3], "B": [4, 5], "S": [6], "Y": [7, 8]}}
        self.assertEqual(netlist.mux_arms(mux, "$mux"), ((2, 3), (4, 5)))
        pmux: dict[str, object] = {"connections": {"A": [2], "B": [3, 4], "S": [5, 6], "Y": [7]}}
        self.assertEqual(netlist.mux_arms(pmux, "$pmux"), ((2,), (3,), (4,)))
        shiftx: dict[str, object] = {"connections": {"A": [2, 3, 4, 5], "B": [6, 7], "Y": [8, 9]}}
        self.assertEqual(netlist.mux_arms(shiftx, "$shiftx"), ((2, 3), (3, 4), (4, 5)))  # 3 offsets
        const_sel: dict[str, object] = {"connections": {"A": [2, 3, 4], "B": ["0", "1"], "Y": [8]}}
        self.assertEqual(len(netlist.mux_arms(const_sel, "$shiftx")), 1)  # not a mux

    def test_replay_script_and_command_line(self) -> None:
        line = (
            "$ /opt/odin3 --diag-paths resolved --top t -p read_techlib /x/vtr.o3lib; "
            'read_verilog "t.v"; hardmap; lower; abc --lut 6 --prov-cut on; '
            'write_blif --vtr --lut-k 6 --name-style hash --prov-map "/o/odin3/t.blif"'
        )
        argv, script = flow.split_command(line)
        self.assertEqual(argv, ["/opt/odin3", "--diag-paths", "resolved", "--top", "t"])
        out = flow.replay_script(script, Path("/w/snapshot.json"), Path("/w"))
        self.assertIn(
            'hardmap; write_json --odin3 --name-style hash --prov-map "/w/snapshot.json"; lower;',
            out,
        )
        self.assertTrue(out.endswith('--prov-map "/w/t.blif"'))
        with self.assertRaises(flow.FlowError):
            flow.replay_script("read_verilog x; hardmap", Path("/s"), Path("/w"))

    def test_map_without_uid_is_refused(self) -> None:
        m = provmap.parse(
            "# odin3-names 2 hash=sha256\nR\tr1\tS\tstmt\torigin\tt1.1\t\tf1:1.1-1.2\tc1\t\n"
        )
        with self.assertRaises(provmap.MapError):
            lutcost.require_uid(m)


class TestCli(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def earlier_run(self, name: str) -> Path:
        words = self.tmp / "run" / "words"
        words.mkdir(parents=True)
        for f in (DATA / name).iterdir():
            shutil.copy(f, words / f.name)
        return self.tmp / "run"

    def test_table_and_json_from_an_earlier_run(self) -> None:
        run = self.earlier_run("case_tern")
        code, out, _ = wyrd("mux-cost", "--from", str(run))
        self.assertEqual(code, 0)
        self.assertIn("Per HDL construct", out)
        self.assertIn("case_tern.v:5", out)
        code, out, _ = wyrd(
            "mux-cost", "--from", str(run), "--json", "--sort", "luts", "--limit", "1"
        )
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(len(doc["muxes"]), 1)
        self.assertEqual(doc["schema"], "wyrd-mux-cost")

    def test_net_timing_option(self) -> None:
        run = self.earlier_run("case_tern")
        csv = write_timing(self.tmp, "case_tern", {})
        code, out, _ = wyrd(
            "mux-cost", "--from", str(run), "--json", "--net-timing", str(csv), "--sort", "crit"
        )
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["timing"])

    def test_sort_crit_without_report_exits_1(self) -> None:
        run = self.earlier_run("case_tern")
        code, _, err = wyrd("mux-cost", "--from", str(run), "--sort", "crit")
        self.assertEqual(code, 1)
        self.assertIn("--net-timing", err)

    def test_usage_errors_exit_2(self) -> None:
        self.assertEqual(wyrd("mux-cost")[0], 2)
        self.assertEqual(wyrd("mux-cost", "--project", "p")[0], 2)
        self.assertEqual(wyrd("mux-cost", "a.v", "--from", "d")[0], 2)
        self.assertEqual(wyrd("mux-cost", "--from", str(self.tmp))[0], 2)
        self.assertEqual(wyrd("mux-cost", "--from", str(self.tmp), "--limit", "0")[0], 2)


class TestProjectRun(CliBase):
    """`--project DIR --run KEY`: the design and top of the run, output under the run directory."""

    def test_design_run_dir_and_found_timing_report(self) -> None:
        root = self.init_project()
        self.assertEqual(wyrd("run", "--project", str(root))[0], 0)
        rows = cli._rows(str(root))
        assert rows is not None
        key, run_dir = str(rows[0]["key"]), Path(str(rows[0]["run_dir"]))
        seen: list[flow.FlowSpec] = []

        def fake_run(spec: flow.FlowSpec) -> report.Inputs:
            seen.append(spec)
            return inputs("case_tern")

        (run_dir / "vpr").mkdir(parents=True, exist_ok=True)
        write_timing(run_dir / "vpr", "case_tern", {})  # found, and its pins join the BLIF
        with mock.patch.object(flow, "run", fake_run):
            code, out, err = wyrd("mux-cost", "--project", str(root), "--run", key[:8], "--json")
        self.assertEqual(code, 0, err)
        (spec,) = seen
        self.assertEqual(spec.files, (root / "a.v",))
        self.assertEqual(spec.out, run_dir / "mux-cost")
        self.assertTrue(json.loads(out)["timing"])
        self.assertEqual(wyrd("mux-cost", "--project", str(root), "--run", "abc")[0], 2)
        self.assertEqual(wyrd("mux-cost", "--project", str(root), "--run", "ffffff")[0], 2)


@unittest.skipUnless(all(REAL), "set WYRD_TEST_ODIN3 and WYRD_TEST_ODIN3_FLOW to run Odin III")
class TestRealOdin3(unittest.TestCase):
    def test_samples_match_the_fixtures(self) -> None:
        odin3, odin3_flow = REAL
        assert odin3 and odin3_flow
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("case_tern", "chain", "index"):
                spec = flow.FlowSpec(
                    (DATA / "src" / f"{name}.v",), name, Path(tmp) / name, odin3_flow, odin3
                )
                got = report.build(flow.run(spec))
                want = report.build(inputs(name))
                for key in ("muxes", "constructs", "totals"):
                    self.assertEqual(_strip(got[key]), _strip(want[key]), name)


def _strip(value: object) -> object:
    """Drop the hash names (mux ids and witnesses) so two runs compare."""
    if isinstance(value, list):
        return [_strip(v) for v in value]
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in ("id", "witness")}
    return value


if __name__ == "__main__":
    unittest.main()
