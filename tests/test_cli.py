import contextlib
import io
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.helpers import make_project, shell
from wyrd import cli
from wyrd.model import Metric
from wyrd.project import load_project
from wyrd.store import Store

FAKES = Path(__file__).parent / "fakes"
ARCH = "k6_frac_N10_frac_chain_mem32K_40nm"


def wyrd(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliBase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.vtr = self.tmp / "vtr"
        arch = self.vtr / "vtr_flow" / "arch" / "timing"
        arch.mkdir(parents=True)
        (arch / f"{ARCH}.xml").write_text("<arch/>", encoding="utf-8")
        (self.vtr / "vpr").mkdir()
        shutil.copy(FAKES / "odin3-flow", self.vtr / "vpr" / "vpr")
        machine = self.tmp / "machine.toml"
        machine.write_text(
            f'[tools]\nodin3 = "{FAKES / "odin3-flow"}"\nodin3_flow = "{FAKES / "odin3-flow"}"\n'
            f'vtr_root = "{self.vtr}"\n[resources]\nlauncher = "plain"\njobs = 1\n'
            f'disk_min_free = "1K"\ndisk_check_path = "{self.tmp}"\n',
            encoding="utf-8",
        )
        patch = mock.patch.dict(os.environ, {"WYRD_CONFIG": str(machine)})
        patch.start()
        self.addCleanup(patch.stop)

    def init_project(self, name: str = "proj") -> Path:
        root = self.tmp / name
        self.assertEqual(wyrd("init", str(root))[0], 0)
        toml = root / "wyrd.toml"
        toml.write_text(
            toml.read_text(encoding="utf-8").replace("CHANGE_ME.v", "a.v"), encoding="utf-8"
        )
        (root / "a.v").write_text("module a; endmodule\n", encoding="utf-8")
        return root

    def seed(self, root: Path, luts: float, status: str = "ok", key: str = "") -> str:
        project = make_project(root, {"d": 4}, [shell("true")], arch="k6")
        spec = project.runs[0]
        store = Store(root / "wyrd.db")
        key = key or f"{luts:06.0f}" + "ab" * 29
        store.begin(key, spec, root / "runs" / key[:12])
        store.add_metrics(key, "s", [Metric("luts", luts), Metric("crit_path_ns", 4.56789)])
        store.finish(key, status)
        return key


class InitRunTest(CliBase):
    def test_init_then_run_ok(self) -> None:
        root = self.init_project()
        code, out, err = wyrd("run", "--project", str(root))
        self.assertEqual(code, 0, err)
        self.assertRegex(out, rf"^ok mydesign {ARCH} [0-9a-f]{{12}}$")
        self.assertEqual(wyrd("run", "--project", str(root))[0], 0)  # reuse of an ok run

    def test_init_loads_after_edit_and_refuses_overwrite(self) -> None:
        root = self.init_project()
        self.assertEqual(len(load_project(root / "wyrd.toml").runs), 1)
        code, _, err = wyrd("init", str(root))
        self.assertEqual(code, 2)
        self.assertIn("already exists", err)

    def test_run_exit_1_on_fail(self) -> None:
        root = self.init_project()
        toml = root / "wyrd.toml"
        toml.write_text(
            toml.read_text(encoding="utf-8").replace(
                'steps = [{ use = "odin3-flow", target = "vtr", vpr = true }]',
                'steps = [{ use = "shell", argv = ["false"] }]',
            ),
            encoding="utf-8",
        )
        code, out, _ = wyrd("run", "--project", str(root))
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith("fail mydesign"))

    def test_run_exit_2_on_config_error(self) -> None:
        root = self.tmp / "bad"
        root.mkdir()
        (root / "wyrd.toml").write_text("[project\n", encoding="utf-8")
        code, _, err = wyrd("run", "--project", str(root))
        self.assertEqual(code, 2)
        self.assertIn("wyrd.toml:1", err)

    def test_run_exit_2_on_preflight_and_lock(self) -> None:
        root = self.init_project()
        shutil.rmtree(self.vtr / "vtr_flow")
        code, _, err = wyrd("run", "--project", str(root))
        self.assertEqual(code, 2)
        self.assertIn("arch file not found", err)
        from wyrd.preflight import acquire_lock

        fd = acquire_lock(root)
        self.addCleanup(os.close, fd)
        code, _, err = wyrd("run", "--project", str(root))
        self.assertEqual((code, "locked" in err), (2, True))

    def test_run_exit_2_on_bad_settings(self) -> None:
        root = self.init_project()
        code, _, _ = wyrd("run", "--project", str(root), "--mem-budget", "lots")
        self.assertEqual(code, 2)

    def test_lock_released_after_run(self) -> None:
        root = self.init_project()
        wyrd("run", "--project", str(root))
        from wyrd.preflight import acquire_lock

        os.close(acquire_lock(root))


class ReportTest(CliBase):
    def test_table_md(self) -> None:
        root = self.tmp / "p"
        self.seed(root, 10)
        code, out, _ = wyrd("table", "--project", str(root), "--metrics", "luts,crit_path_ns")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "| design | arch | status | luts | crit_path_ns |")
        self.assertEqual(lines[2], "| d | k6 | ok | 10 | 4.568 |")
        default = wyrd("table", "--project", str(root))[1].splitlines()[0]
        self.assertEqual(default, "| design | arch | status | crit_path_ns | luts |")

    def test_table_csv_and_missing_metric(self) -> None:
        root = self.tmp / "p"
        self.seed(root, 10)
        _, out, _ = wyrd("table", "--project", str(root), "--format", "csv", "--metrics", "luts,x")
        self.assertEqual(out.splitlines(), ["design,arch,status,luts,x", "d,k6,ok,10,"])

    def test_table_without_db_exit_2(self) -> None:
        self.assertEqual(wyrd("table", "--project", str(self.tmp))[0], 2)

    def test_compare_ratio(self) -> None:
        a, b = self.tmp / "a", self.tmp / "b"
        self.seed(a, 10)
        self.seed(b, 12)
        code, out, _ = wyrd("compare", str(a), str(b), "--metrics", "luts", "--format", "csv")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), ["design,arch,metric,A,B,B/A", "d,k6,luts,10,12,1.2"])

    def test_status_counts(self) -> None:
        root = self.tmp / "p"
        self.seed(root, 10)
        self.seed(root, 11, "fail")
        self.assertEqual(wyrd("status", "--project", str(root))[1].splitlines(), ["fail 1", "ok 1"])


class ScriptTest(CliBase):
    def test_script_replays(self) -> None:
        root = self.init_project()
        wyrd("run", "--project", str(root))
        summary = next(root.glob("runs/*/*/*/0-odin3-flow/out/summary.json"))
        key = next(root.glob("runs/*/*/*")).name
        summary.unlink()
        code, out, _ = wyrd("script", key[:8], "--project", str(root))
        self.assertEqual(code, 0)
        replay = Path(out.strip())
        self.assertEqual(subprocess.run([str(replay)], check=False).returncode, 0)
        self.assertTrue(summary.is_file())

    def test_script_key_errors(self) -> None:
        root = self.init_project()
        wyrd("run", "--project", str(root))
        key = next(root.glob("runs/*/*/*")).name
        self.assertEqual(wyrd("script", key[:3], "--project", str(root))[0], 2)
        self.assertEqual(wyrd("script", "zzzzzzzz", "--project", str(root))[0], 2)
        db = self.tmp / "p"
        self.seed(db, 10, key="abcdef1" + "0" * 57)
        self.seed(db, 11, key="abcdef2" + "0" * 57)
        code, _, err = wyrd("script", "abcdef", "--project", str(db))
        self.assertEqual((code, "ambiguous" in err), (2, True))


class TimingCliTest(CliBase):
    def test_timing_summary(self) -> None:
        root = self.tmp / "p"
        key = self.seed(root, 10)
        step = root / "runs" / key[:12] / "0-odin3-flow"
        shutil.copytree(Path(__file__).parent / "data" / "timing" / "out", step / "out")
        code, out, _ = wyrd("timing", key[:8], "--project", str(root), "--top", "2")
        self.assertEqual(code, 0)
        self.assertIn("Fmax 216.48 MHz", out)
        self.assertIn("bm_DL_BCD_adder.v:15", out)

    def test_timing_errors(self) -> None:
        root = self.tmp / "p"
        key = self.seed(root, 10)
        code, _, err = wyrd("timing", key[:8], "--project", str(root))
        self.assertEqual((code, "no timing attribution" in err), (2, True))
        out = root / "runs" / key[:12] / "0-odin3-flow" / "out" / "timing"
        out.mkdir(parents=True)
        (out / "attribution.json").write_text('{"schema_version": 7}', encoding="utf-8")
        code, _, err = wyrd("timing", key[:8], "--project", str(root))
        self.assertEqual((code, "schema_version 7" in err), (2, True))
        self.assertEqual(wyrd("timing", "zzzzzzzz", "--project", str(root))[0], 2)


class RobustnessTest(CliBase):
    def test_run_prints_each_run_once(self) -> None:
        root = self.init_project()
        code, out, err = wyrd("run", "--project", str(root))
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 1)
        self.assertEqual(err, "")

    def test_run_progress(self) -> None:
        root = self.init_project()
        code, out, _ = wyrd("run", "--project", str(root), "--progress")
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "plan: 1 to run, 0 reused")
        run_line = re.compile(r"^\S+/\S+ \[[0-9a-f]{12}\] ok$")
        idx = [i for i, ln in enumerate(lines) if run_line.match(ln)]
        self.assertEqual(len(idx), 1)
        self.assertLess(idx[0], len(lines) - 1)
        _, plain, _ = wyrd("run", "--project", str(root), "--force")
        self.assertNotIn("plan:", plain)

    def test_unexpected_load_error_exit_2(self) -> None:
        root = self.init_project()
        with mock.patch.object(cli, "load_project", side_effect=RuntimeError("boom")):
            code, _, err = wyrd("run", "--project", str(root))
        self.assertEqual((code, "boom" in err), (2, True))

    def test_run_all_errors_exit_2_and_release_lock(self) -> None:
        root = self.init_project()
        for exc in (OSError("disk"), sqlite3.OperationalError("locked")):
            with mock.patch.object(cli, "run_all", side_effect=exc):
                code, _, err = wyrd("run", "--project", str(root))
            self.assertEqual((code, str(exc) in err), (2, True))
        from wyrd.preflight import acquire_lock

        os.close(acquire_lock(root))

    def test_interrupted_run_exit_1(self) -> None:
        root = self.init_project()
        with mock.patch.object(cli, "run_all", return_value={}):
            self.assertEqual(wyrd("run", "--project", str(root))[0], 1)

    def test_empty_sweep_exit_2(self) -> None:
        root = self.init_project()
        project = load_project(root / "wyrd.toml")
        empty = type(project)(
            project.root, project.name, project.designs, project.recipes, project.run, ()
        )
        with mock.patch.object(cli, "load_project", return_value=empty):
            code, _, err = wyrd("run", "--project", str(root))
        self.assertEqual((code, "no runs in the sweep" in err), (2, True))

    def test_read_only_store_cannot_write(self) -> None:
        root = self.tmp / "p"
        self.seed(root, 10)
        ro = Store.open_readonly(root / "wyrd.db")
        self.assertEqual(len(ro.rows()), 1)
        with self.assertRaises(sqlite3.OperationalError):
            ro.finish(str(ro.rows()[0]["key"]), "fail")

    def test_corrupt_db_exit_2(self) -> None:
        root = self.tmp / "p"
        root.mkdir()
        (root / "wyrd.db").write_text("not a database" * 100, encoding="utf-8")
        for cmd in ("status", "table"):
            code, _, err = wyrd(cmd, "--project", str(root))
            self.assertEqual((code, "cannot read" in err), (2, True))
        self.assertEqual(wyrd("compare", str(root), str(root))[0], 2)

    def test_compare_reports_unmatched_on_stderr(self) -> None:
        a, b = self.tmp / "a", self.tmp / "b"
        self.seed(a, 10)
        self.seed(b, 12)
        con = sqlite3.connect(b / "wyrd.db")
        with con:
            con.execute("UPDATE runs SET arch = 'other'")
        con.close()
        code, _, err = wyrd("compare", str(a), str(b))
        self.assertEqual(code, 0)
        self.assertIn("only in A: d k6", err)
        self.assertIn("only in B: d other", err)

    def test_script_orders_numerically_and_skips_strays(self) -> None:
        root = self.tmp / "p"
        key = self.seed(root, 10)
        directory = root / "runs" / key[:12]
        for name in ("2-b", "10-c", "1-a", "x-skip", "3x-skip", "notes"):
            (directory / name).mkdir(parents=True)
            (directory / name / "cmd.sh").write_text("true\n", encoding="utf-8")
        code, out, _ = wyrd("script", key[:8], "--project", str(root))
        self.assertEqual(code, 0)
        text = Path(out.strip()).read_text(encoding="utf-8")
        self.assertLess(text.index("/1-a/"), text.index("/2-b/"))
        self.assertLess(text.index("/2-b/"), text.index("/10-c/"))
        self.assertNotIn("skip", text)
        self.assertNotIn("notes", text)
        self.assertIn("overwrites", text.splitlines()[1])
