import sys
import unittest
from pathlib import Path

from wyrd.guimodel.flowcmd import FlowProgress, ProgressEvent, exit_text, parse_progress, run_argv


class FlowCmdTest(unittest.TestCase):
    def test_argv(self) -> None:
        self.assertEqual(
            run_argv(Path("/p"), True, 4, "60%"),
            [sys.executable, "-m", "wyrd.cli", "run", "--project", "/p", "--progress",
             "--force", "--jobs", "4", "--mem-budget", "60%"],
        )  # fmt: skip
        self.assertEqual(
            run_argv(Path("/p")),
            [sys.executable, "-m", "wyrd.cli", "run", "--project", "/p", "--progress"],
        )

    def test_parse_progress(self) -> None:
        self.assertEqual(
            parse_progress("plan: 3 to run, 2 reused"), ProgressEvent("plan", to_run=3, reused=2)
        )
        ev = parse_progress("single/EArch [746b2e6ac981] fail: step odin3 failed")
        assert ev is not None
        self.assertEqual(
            (ev.kind, ev.name, ev.key, ev.status, ev.message),
            ("run", "single/EArch", "746b2e6ac981", "fail", "step odin3 failed"),
        )
        ok = parse_progress("a/b [746b2e6ac981] ok")
        assert ok is not None
        self.assertEqual((ok.status, ok.message), ("ok", ""))
        self.assertIsNone(parse_progress("ok single EArch 746b2e6ac981"))

    def test_flow_progress(self) -> None:
        p = FlowProgress()
        self.assertIsNone(p.fraction())
        self.assertIsNone(p.feed("some other line"))
        p.feed("plan: 2 to run, 0 reused")
        self.assertEqual(p.fraction(), 0.0)
        p.feed("a/b [746b2e6ac981] ok")
        self.assertEqual(p.fraction(), 0.5)
        for _ in range(5):
            p.feed("a/b [746b2e6ac981] ok")
        self.assertEqual(p.fraction(), 1.0)
        z = FlowProgress()
        z.feed("plan: 0 to run, 5 reused")
        self.assertEqual(z.fraction(), 1.0)

    def test_exit_text(self) -> None:
        self.assertEqual(exit_text(0), "all runs ok")
        self.assertEqual(exit_text(1), "some runs not ok")
        self.assertEqual(exit_text(2), "configuration error (see log)")
        self.assertEqual(exit_text(-9), "exited with code -9")


if __name__ == "__main__":
    unittest.main()
