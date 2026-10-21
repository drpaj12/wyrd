import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wyrd import settings
from wyrd.model import Design, Recipe, RunSpec, StepSpec
from wyrd.steps import arch_xml, get_step, tool_path, tool_versions

FAKE = Path(__file__).parent / "fakes" / "odin3-flow"


def _settings(vtr: str = "/vtr") -> settings.Settings:
    with mock.patch.dict("os.environ", {"VTR_ROOT": vtr, "WYRD_CONFIG": "/nonexistent/m.toml"}):
        return settings.load(None, {})


def _run(use: str = "odin3-flow", args: dict[str, object] | None = None) -> RunSpec:
    design = Design("d", (Path("/src/a.v"), Path("/src/b.v")), "top")
    recipe = Recipe("r", (StepSpec(use, args or {}),))
    return RunSpec(design, "k6", recipe)


class StepsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_flow_argv(self) -> None:
        run = _run()
        step = get_step(run.recipe.steps[0])
        argv, env = step.command(run, self.dir, _settings())
        self.assertEqual(
            argv,
            [
                "odin3-flow", "/src/a.v", "/src/b.v", "--top", "top", "--target", "vtr",
                "--arch", "/vtr/vtr_flow/arch/timing/k6.xml", "--vpr",
                "--out", str(self.dir / "out"),
            ],
        )  # fmt: skip
        self.assertEqual(env, {"VTR_ROOT": "/vtr"})
        self.assertEqual(step.tools, ("odin3_flow", "odin3", "vpr"))
        self.assertTrue(step.is_vpr)

    def test_flow_no_vpr(self) -> None:
        run = _run(args={"vpr": False, "target": "x"})
        step = get_step(run.recipe.steps[0])
        argv, _ = step.command(run, self.dir, _settings())
        self.assertIn("--no-vpr", argv)
        self.assertEqual(step.tools, ("odin3_flow", "odin3"))
        self.assertFalse(step.is_vpr)

    def _write_summary(self, data: dict[str, object]) -> None:
        (self.dir / "out").mkdir()
        (self.dir / "out" / "summary.json").write_text(json.dumps(data), encoding="utf-8")

    def test_flow_collect_flattens(self) -> None:
        self._write_summary(
            {
                "luts": 10,
                "luts_note": "x",
                "hard_blocks": {"multiply": 2.0},
                "crit_path_ns": 3.5,
                "seconds": {"vpr": 1.0},
            }
        )
        got = {m.name: m for m in get_step(StepSpec("odin3-flow")).collect(self.dir)}
        self.assertEqual(got["hard_blocks.multiply"].value, 2.0)
        self.assertNotIn("luts_note", got)
        self.assertEqual(got["seconds.vpr"].unit, "s")
        self.assertEqual(got["crit_path_ns"].unit, "ns")
        self.assertEqual(got["luts"].unit, "")

    def test_flow_collect_skips_null(self) -> None:
        self._write_summary({"luts": 10, "min_chan_width": None, "wirelength": None})
        names = [m.name for m in get_step(StepSpec("odin3-flow")).collect(self.dir)]
        self.assertEqual(names, ["luts"])

    def test_command_placeholders(self) -> None:
        argv = ["vpr", "{arch_xml}", "{files}", "--top", "{top}", "--dir", "{step_dir}"]
        run = _run("vpr", {"argv": argv})
        step = get_step(run.recipe.steps[0])
        got, env = step.command(run, self.dir, _settings())
        self.assertEqual(
            got,
            [
                "/vtr/vpr/vpr", "/vtr/vtr_flow/arch/timing/k6.xml", "/src/a.v", "/src/b.v",
                "--top", "top", "--dir", str(self.dir),
            ],
        )  # fmt: skip
        self.assertEqual(env, {})
        self.assertTrue(step.is_vpr)
        self.assertEqual(step.tools, ("vpr",))

    def test_command_shell_keeps_first_word(self) -> None:
        run = _run("shell", {"argv": ["echo", "{vtr_root}"]})
        got, _ = get_step(run.recipe.steps[0]).command(run, self.dir, _settings())
        self.assertEqual(got, ["echo", "/vtr"])

    def test_command_collect(self) -> None:
        step = get_step(StepSpec("shell", {"argv": ["true"]}))
        self.assertEqual(step.collect(self.dir), [])
        (self.dir / "metrics.json").write_text('{"a": 1, "b": "x"}', encoding="utf-8")
        self.assertEqual([(m.name, m.value) for m in step.collect(self.dir)], [("a", 1.0)])

    def test_generic_step_needs_own_argv(self) -> None:
        recipe = Recipe("r", (StepSpec("vpr", {"argv": ["vpr"]}), StepSpec("vpr")))
        with self.assertRaisesRegex(ValueError, "vpr"):
            get_step(recipe.steps[1])
        with self.assertRaisesRegex(ValueError, "shell"):
            get_step(StepSpec("shell", {"argv": [1]}))

    def _cmd(
        self, argv: list[str], s: settings.Settings | None = None, top: str | None = "t"
    ) -> list[str]:
        run = RunSpec(Design("d", (Path("/a.v"),), top), "k6", Recipe("r", ()))
        step = get_step(StepSpec("shell", {"argv": argv}))
        return step.command(run, self.dir, s or _settings())[0]

    def test_vtr_root_unset(self) -> None:
        s = settings.Settings(**{**_settings().__dict__, "vtr_root": None})
        with self.assertRaisesRegex(ValueError, "vtr_root"):
            self._cmd(["echo", "{vtr_root}"], s)
        with self.assertRaisesRegex(ValueError, "vtr_root"):
            get_step(StepSpec("odin3-flow")).command(_run(), self.dir, s)

    def test_top_missing(self) -> None:
        with self.assertRaisesRegex(ValueError, "shell"):
            self._cmd(["echo", "{top}"], top=None)

    def test_single_pass_expansion(self) -> None:
        run = RunSpec(Design("d", (Path("/a.v"),), "{step_dir}"), "k6", Recipe("r", ()))
        got, _ = get_step(StepSpec("shell", {"argv": ["echo", "{top}"]})).command(
            run, self.dir, _settings()
        )
        self.assertEqual(got, ["echo", "{step_dir}"])

    def test_files_inside_word(self) -> None:
        with self.assertRaisesRegex(ValueError, "whole argv word"):
            self._cmd(["echo", "-I{files}"])

    def test_collect_bad_values(self) -> None:
        step = get_step(StepSpec("shell", {"argv": ["true"]}))
        (self.dir / "metrics.json").write_text(
            '{"a": 1, "n": NaN, "i": Infinity, "big": 1e999, "huge": %s, "t": true}' % ("9" * 400),
            encoding="utf-8",
        )
        self.assertEqual([m.name for m in step.collect(self.dir)], ["a"])
        (self.dir / "metrics.json").write_text("{bad", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "metrics.json"):
            step.collect(self.dir)

    def test_flow_collect_bad_values(self) -> None:
        self.assertEqual(get_step(StepSpec("odin3-flow")).collect(self.dir), [])
        self._write_summary({"luts": 1, "x": float("nan"), "y": True, "z": {"w": float("inf")}})
        self.assertEqual(
            [m.name for m in get_step(StepSpec("odin3-flow")).collect(self.dir)], ["luts"]
        )
        (self.dir / "out" / "summary.json").write_text("[oops", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "summary.json"):
            get_step(StepSpec("odin3-flow")).collect(self.dir)

    def test_flow_vpr_must_be_bool(self) -> None:
        for bad in ("no", 0, None):
            with self.assertRaisesRegex(ValueError, "vpr"):
                get_step(StepSpec("odin3-flow", {"vpr": bad}))

    def test_get_step_unknown(self) -> None:
        with self.assertRaises(KeyError):
            get_step(StepSpec("nope"))

    def test_tool_paths(self) -> None:
        s = _settings()
        self.assertEqual(tool_path(s, "vpr"), "/vtr/vpr/vpr")
        self.assertEqual(tool_path(s, "abc"), "/vtr/build/abc/abc")
        self.assertEqual(tool_path(s, "odin3"), "odin3")
        self.assertEqual(arch_xml(s, "k6"), Path("/vtr/vtr_flow/arch/timing/k6.xml"))

    def test_tool_versions(self) -> None:
        s = _settings()
        with mock.patch("wyrd.steps.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="odin3 1.0\n")
            self.assertEqual(tool_versions(s, ["odin3"]), {"odin3": "odin3 1.0"})
            run.side_effect = FileNotFoundError("x")
            self.assertEqual(tool_versions(s, ["odin3"]), {"odin3": "unknown"})

    def test_tool_versions_relative_path_from_root(self) -> None:
        base = _settings()
        s = settings.Settings(**{**base.__dict__, "tools": {"odin3": "bin/odin3"}})
        root = Path("/proj")
        with mock.patch("wyrd.steps.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout="v1\n")
            tool_versions(s, ["odin3"], root)
            self.assertEqual(run.call_args.args[0][0], "/proj/bin/odin3")
            tool_versions(s, ["odin3"])
            self.assertEqual(run.call_args.args[0][0], "bin/odin3")
            s2 = settings.Settings(**{**base.__dict__, "tools": {"odin3": "odin3"}})
            tool_versions(s2, ["odin3"], root)
            self.assertEqual(run.call_args.args[0][0], "odin3")

    def test_fake_flow_end_to_end(self) -> None:
        run = _run()
        base = _settings()
        s = settings.Settings(**{**base.__dict__, "tools": {**base.tools, "odin3_flow": str(FAKE)}})
        step = get_step(run.recipe.steps[0])
        argv, env = step.command(run, self.dir, s)
        subprocess.run(argv, check=True, env=env)
        got = {m.name: m.value for m in step.collect(self.dir)}
        self.assertEqual(got["hard_blocks.multiply"], 2.0)
        self.assertNotIn("min_chan_width", got)
