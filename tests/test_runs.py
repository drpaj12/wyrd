import tempfile
import unittest
from pathlib import Path

from tests.helpers_results import make_results
from wyrd import report
from wyrd.guimodel import runs
from wyrd.guimodel.runs import StepDir


class RunsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_missing_db(self) -> None:
        self.assertIsNone(runs.load_rows(self.root))

    def test_run_infos(self) -> None:
        make_results(self.root)
        rows = runs.load_rows(self.root)
        assert rows is not None
        infos = runs.run_infos(rows)
        self.assertEqual([(i.label, i.status) for i in infos], [("single / EArch", "ok")])

    def test_summary_rows(self) -> None:
        run_dir = make_results(self.root)
        rows = runs.load_rows(self.root)
        assert rows is not None
        self.assertEqual(
            runs.summary_rows(runs.run_infos(rows)[0].row),
            [
                ("Status", "ok"),
                ("LUTs", "56"),
                ("CLBs", "6"),
                ("mult_36", "1"),
                ("Fmax (MHz)", report.number(1000 / 5.5)),
                ("Min channel width", "32"),
                ("Critical path (ns)", "5.5"),
                ("Run directory", str(run_dir)),
                ("Run key", "a" * 64),
            ],
        )
        self.assertEqual(report.number(1000 / 5.5), "181.8")

    def test_summary_missing(self) -> None:
        got = dict(runs.summary_rows({"status": "fail", "key": "k", "run_dir": "d"}))
        for label in ("LUTs", "CLBs", "Min channel width", "Critical path (ns)", "Fmax (MHz)"):
            self.assertEqual(got[label], "n/a")
        self.assertEqual(got["Hard blocks"], "none")
        zero = dict(runs.summary_rows({"status": "ok", "crit_path_ns": 0}))
        self.assertEqual(zero["Fmax (MHz)"], "n/a")
        for bad in (0, -1, None, "x", True, float("nan")):
            self.assertIsNone(runs.fmax_mhz(bad))
        self.assertEqual(runs.fmax_mhz(4.0), 250.0)

    def test_step_dirs_and_logs(self) -> None:
        run_dir = make_results(self.root)
        step = run_dir / "0-odin3-flow"
        self.assertEqual(runs.step_dirs(run_dir), [StepDir(0, "odin3-flow", step)])
        (run_dir / "10-x").mkdir()
        (run_dir / "2-y").mkdir()
        (run_dir / "note.txt").write_text("x", encoding="utf-8")
        self.assertEqual([s.n for s in runs.step_dirs(run_dir)], [0, 2, 10])
        self.assertEqual(
            runs.log_files(step),
            [step / "out" / "odin3" / "odin3.log", step / "out" / "vpr" / "run" / "vpr_stdout.log"],
        )

    def test_many_recipes_and_params_in_label(self) -> None:
        base: dict[str, object] = {
            "design": "d", "arch": "a", "recipe": "r1", "params": "{}",
            "key": "k1", "status": "ok", "run_dir": "x", "started": "1",
        }  # fmt: skip
        other = {**base, "recipe": "r2", "key": "k2", "params": '{"seed": 1}'}
        labels = [i.label for i in runs.run_infos([base, other])]
        self.assertEqual(labels, ['d / a / r1', 'd / a / r2 {"seed": 1}'])


if __name__ == "__main__":
    unittest.main()
