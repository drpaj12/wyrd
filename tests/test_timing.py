"""Timing model and flow-step option.

Fixture ``tests/data/timing``: ``out/timing/attribution.json`` and ``bm_DL_BCD_adder.v`` come from
a real run on the micro design ``tests/micro/verilog/micro/bm_DL_BCD_adder.v`` of Odin III main
(31ecd157), made in a directory holding a copy of the design, with absolute paths made relative:

    tools/heavy-run tools/flow/odin3-flow bm_DL_BCD_adder.v --top bm_DL_BCD_adder \
        --timing-attr --out out
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_steps import _settings
from wyrd.guimodel import timing
from wyrd.guimodel.timing import TimingError
from wyrd.model import Design, Recipe, RunSpec, StepSpec
from wyrd.steps import get_step
from wyrd.steps.flow import attribution_path, timing_metrics

DATA = Path(__file__).parent / "data" / "timing"
ATTR = DATA / "out" / "timing" / "attribution.json"


def _raw() -> dict[str, object]:
    data: dict[str, object] = json.loads(ATTR.read_text(encoding="utf-8"))
    return data


class ModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.att = timing.load_attribution(ATTR)

    def test_header(self) -> None:
        self.assertEqual(self.att.top, "bm_DL_BCD_adder")
        self.assertAlmostEqual(self.att.fmax_mhz or 0, 216.483)
        self.assertAlmostEqual(self.att.cpd_ns or 0, 4.61929)
        self.assertEqual(self.att.paths_kept, 10)

    def test_statements_ranked(self) -> None:
        first = self.att.statements[0]
        self.assertEqual(first.id, "bm_DL_BCD_adder.v:15")
        self.assertEqual(first.word, "Z")
        self.assertEqual(first.text, "Z = X + Y + Cin;")
        self.assertAlmostEqual(first.share, 0.492531)
        shares = [s.delay_ns for s in self.att.statements]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_modules_and_words(self) -> None:
        self.assertEqual(self.att.modules[0].name, "bm_DL_BCD_adder")
        self.assertIn("bm_DL_BCD_adder.Cout", [w.name for w in self.att.words])

    def test_critical_path_in_order(self) -> None:
        kinds = [e.kind for e in self.att.critical_path]
        self.assertEqual(kinds[0], "port")
        self.assertEqual(self.att.critical_path[1].line, 15)
        total = sum(e.share for e in self.att.critical_path)
        self.assertAlmostEqual(total, 1.0, places=3)

    def test_critical_line_shares(self) -> None:
        got = timing.critical_line_shares(self.att)["bm_DL_BCD_adder.v"]
        self.assertEqual(sorted(got), [15, 16, 19])
        self.assertAlmostEqual(got[15], 0.492531)

    def test_top_n_shares(self) -> None:
        one = timing.top_line_shares(self.att, 1)["bm_DL_BCD_adder.v"]
        all_ = timing.top_line_shares(self.att, 100)["bm_DL_BCD_adder.v"]
        self.assertIn(15, one)
        self.assertLessEqual(sum(all_.values()), 1.0 + 1e-9)
        self.assertEqual(timing.top_line_shares(self.att, 0), {})

    def test_split_span(self) -> None:
        self.assertEqual(timing.split_span("a/b.v:12"), ("a/b.v", 12))
        self.assertEqual(timing.split_span("C:\\x.v:3"), ("C:\\x.v", 3))
        self.assertIsNone(timing.split_span(None))
        self.assertIsNone(timing.split_span("nolines"))
        self.assertIsNone(timing.split_span("a.v:x"))

    def test_resolve_source(self) -> None:
        src = DATA / "bm_DL_BCD_adder.v"
        self.assertEqual(timing.resolve_source("bm_DL_BCD_adder.v", [DATA]), src)
        self.assertEqual(timing.resolve_source("elsewhere/bm_DL_BCD_adder.v", [DATA]), src)
        self.assertIsNone(timing.resolve_source("nope.v", [DATA]))
        self.assertEqual(timing.resolve_source(str(src), [DATA]), src)
        self.assertIsNone(timing.resolve_source(str(src), []))  # outside every root

    def test_file_shares(self) -> None:
        shares = timing.critical_line_shares(self.att)
        resolver = timing.SourceResolver([DATA])
        got = timing.file_shares(shares, DATA / "bm_DL_BCD_adder.v", resolver)
        self.assertEqual(sorted(got), [15, 16, 19])
        self.assertEqual(timing.file_shares(shares, DATA / "other.v", resolver), {})

    def test_summary_lines(self) -> None:
        text = "\n".join(timing.summary_lines(self.att))
        self.assertIn("Fmax 216.48 MHz", text)
        self.assertIn("(I/O port)", text)
        self.assertIn("bm_DL_BCD_adder.v:15", text)
        self.assertLessEqual(len(timing.summary_lines(self.att, top=1)), len(text.splitlines()))

    def test_unknown_schema(self) -> None:
        data = _raw()
        data["schema_version"] = 2
        with self.assertRaisesRegex(TimingError, "schema_version 2.*schema_version 1 only"):
            timing.parse(data)

    def test_bad_shapes(self) -> None:
        for key in ("timing", "coverage", "critical_path", "design", "spans", "paths"):
            data = _raw()
            data[key] = 5
            with self.assertRaises(TimingError, msg=key):
                timing.parse(data)
        with self.assertRaises(TimingError):
            timing.parse([])

    def test_load_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "attribution.json"
            with self.assertRaisesRegex(TimingError, "cannot read"):
                timing.load_attribution(bad)
            bad.write_text("{nope", encoding="utf-8")
            with self.assertRaisesRegex(TimingError, "not valid JSON"):
                timing.load_attribution(bad)

    def test_find_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            self.assertIsNone(timing.find_attribution(run))
            step = run / "01-odin3-flow"
            shutil.copytree(DATA / "out", step / "out")
            self.assertEqual(timing.find_attribution(run), step / "out/timing/attribution.json")


class RobustModelTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_step_order_is_numeric(self) -> None:
        run = self.tmp / "run"
        for n in (2, 10, 1):
            shutil.copytree(DATA / "out", run / f"{n}-odin3-flow" / "out")
        want = run / "10-odin3-flow/out/timing/attribution.json"
        self.assertEqual(timing.find_attribution(run), want)

    def test_missing_reason_uses_last_step(self) -> None:
        run = self.tmp / "run"
        self.assertIsNone(timing.missing_reason(run))
        for n, text in ((2, "old failure\n"), (10, "no paths parsed\n")):
            log = run / f"{n}-odin3-flow" / "out" / "timing" / "timing.log"
            log.parent.mkdir(parents=True)
            log.write_text(text, encoding="utf-8")
        self.assertEqual(timing.missing_reason(run), "no paths parsed")
        log.write_text("ok\n", encoding="utf-8")
        self.assertIn("says ok", timing.missing_reason(run) or "")

    def test_oversized_file(self) -> None:
        big = self.tmp / "attribution.json"
        big.write_text("{}" + " " * 200, encoding="utf-8")
        limit = mock.patch.object(timing, "MAX_ATTRIBUTION_BYTES", 100)
        with limit, self.assertRaisesRegex(TimingError, "over the 100 byte limit"):
            timing.load_attribution(big)

    def test_schema_version_must_be_int(self) -> None:
        for version in (True, 1.0, "1", None):
            data = _raw()
            data["schema_version"] = version
            with self.assertRaises(TimingError, msg=repr(version)):
                timing.parse(data)

    def test_non_object_elements_are_skipped(self) -> None:
        data = _raw()
        for key in ("spans", "modules", "words", "paths"):
            value = data[key]
            assert isinstance(value, list)
            data[key] = [5, None, *value]
        crit = data["critical_path"]
        assert isinstance(crit, dict) and isinstance(crit["spans"], list)
        crit["spans"] = ["x", *crit["spans"]]
        paths = data["paths"]
        assert isinstance(paths, list) and isinstance(paths[2], dict)
        paths[2]["nodes"] = [7, *paths[2]["nodes"]]
        got, want = timing.parse(data), timing.load_attribution(ATTR)
        self.assertEqual(got, want)

    def test_same_named_files_are_not_guessed(self) -> None:
        for sub in ("a", "b"):
            (self.tmp / sub).mkdir()
            (self.tmp / sub / "x.v").write_text("//\n", encoding="utf-8")
        roots = [self.tmp / "a", self.tmp / "b"]
        self.assertIsNone(timing.resolve_source("other/x.v", roots))
        self.assertEqual(timing.resolve_source("x.v", roots[:1]), self.tmp / "a" / "x.v")
        hints = timing.SourceHints((), (self.tmp / "b" / "x.v",))
        self.assertEqual(timing.resolve_source("b/x.v", roots, hints), self.tmp / "b" / "x.v")

    def test_inputs_json_prefers_recorded_designs(self) -> None:
        for sub in ("a", "b"):
            (self.tmp / sub).mkdir()
            (self.tmp / sub / "x.v").write_text("//\n", encoding="utf-8")
        out = self.tmp / "b" / "run" / "out"
        (out / "timing").mkdir(parents=True)
        inputs = {"source_cwd": "odin3", "designs": [str(self.tmp / "b" / "x.v")]}
        (out / "timing" / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
        hints = timing.source_hints(out / "timing" / "attribution.json")
        self.assertEqual(hints.designs, (self.tmp / "b" / "x.v",))
        roots = [self.tmp / "a", self.tmp / "b"]
        self.assertEqual(timing.resolve_source("x.v", roots, hints), self.tmp / "b" / "x.v")
        moved = timing.resolve_source("/gone/elsewhere/x.v", roots, hints)
        self.assertEqual(moved, self.tmp / "b" / "x.v")

    def test_paths_are_confined_to_roots(self) -> None:
        (self.tmp / "in").mkdir()
        (self.tmp / "in" / "x.v").write_text("//\n", encoding="utf-8")
        (self.tmp / "secret.v").write_text("//\n", encoding="utf-8")
        roots = [self.tmp / "in"]
        self.assertIsNone(timing.resolve_source("../secret.v", roots))
        self.assertIsNone(timing.resolve_source(str(self.tmp / "secret.v"), roots))
        self.assertIsNone(timing.resolve_source("", roots))
        inside = timing.resolve_source(str(self.tmp / "in" / "x.v"), roots)
        self.assertEqual(inside, roots[0] / "x.v")


def _run(args: dict[str, object]) -> RunSpec:
    design = Design("d", (Path("/src/a.v"),), "top")
    return RunSpec(design, "k6", Recipe("r", (StepSpec("odin3-flow", args),)))


class FlowOptionTest(unittest.TestCase):
    def argv(self, args: dict[str, object]) -> list[str]:
        run = _run(args)
        return get_step(run.recipe.steps[0]).command(run, Path("/s"), _settings())[0]

    def test_default_has_no_timing_flags(self) -> None:
        argv = self.argv({})
        self.assertNotIn("--timing-attr", argv)
        self.assertNotIn("--timing-paths", argv)

    def test_timing_attr(self) -> None:
        argv = self.argv({"timing_attr": True})
        self.assertIn("--timing-attr", argv)
        self.assertNotIn("--timing-paths", argv)
        self.assertEqual(argv[-2:], ["--out", "/s/out"])

    def test_timing_paths_implies_attr(self) -> None:
        argv = self.argv({"timing_paths": 20})
        self.assertIn("--timing-attr", argv)
        self.assertEqual(argv[argv.index("--timing-paths") + 1], "20")

    def test_bad_values(self) -> None:
        bad: list[dict[str, object]] = [
            {"timing_attr": "yes"},
            {"timing_paths": 0},
            {"timing_paths": True},
            {"timing_paths": 1.5},
            {"timing_attr": True, "vpr": False},
            {"timing_attr": True, "target": "lpm"},
        ]
        for args in bad:
            with self.assertRaises(ValueError, msg=str(args)):
                get_step(StepSpec("odin3-flow", args))

    def test_collect_records_fmax_and_cpd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            step_dir = Path(tmp)
            shutil.copytree(DATA / "out", step_dir / "out")
            self.assertEqual(attribution_path(step_dir), step_dir / "out/timing/attribution.json")
            got = {
                m.name: m
                for m in get_step(StepSpec("odin3-flow", {"timing_attr": True})).collect(step_dir)
            }
            self.assertEqual(got["timing.attributed"].value, 1.0)
            self.assertAlmostEqual(got["timing.fmax_mhz"].value, 216.483)
            self.assertEqual(got["timing.cpd_ns"].unit, "ns")
            plain = get_step(StepSpec("odin3-flow")).collect(step_dir)
            self.assertEqual(plain, [])

    def test_collect_missing_or_bad(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            step_dir = Path(tmp)
            self.assertEqual([m.value for m in timing_metrics(step_dir)], [0.0])
            target = attribution_path(step_dir)
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"schema_version": 2, "timing": {}}), encoding="utf-8")
            self.assertEqual([m.name for m in timing_metrics(step_dir)], ["timing.attributed"])
            self.assertEqual(timing_metrics(step_dir)[0].value, 0.0)
            for version in (True, 1.0):
                body: dict[str, object] = {"schema_version": version, "timing": {}}
                target.write_text(json.dumps(body), encoding="utf-8")
                self.assertEqual(timing_metrics(step_dir)[0].value, 0.0, msg=repr(version))


if __name__ == "__main__":
    unittest.main()
