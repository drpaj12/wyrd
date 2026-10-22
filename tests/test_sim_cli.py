import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fakes_sim import FakeBackend
from wyrd import cli
from wyrd.bifrost.errors import SimUnavailable

ROOT = Path(__file__).parent.parent
VECTORS = "0 100\n1 001\n2 000\n"


def run_cli(args: list[str], backend: FakeBackend | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    be = backend or FakeBackend()
    with (
        mock.patch("wyrd.cli._sim_backend", return_value=be),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


class SimCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.traffic = self.dir / "traffic.v"
        self.traffic.write_text("module traffic", encoding="utf-8")
        self.vec = self.dir / "in.vec"
        self.vec.write_text(VECTORS, encoding="utf-8")

    def test_vectors_run(self) -> None:
        code, out, _ = run_cli(["sim", str(self.traffic), "--vectors", str(self.vec)])
        self.assertEqual(code, 0)
        self.assertEqual(
            out.splitlines(),
            [
                "1: rst=1 car_ns=0 car_ew=0 | light_ns=2 light_ew=0",
                "2: rst=0 car_ns=0 car_ew=1 | light_ns=1 light_ew=0",
                "3: rst=0 car_ns=0 car_ew=0 | light_ns=1 light_ew=0",
            ],
        )

    def test_csv(self) -> None:
        code, out, _ = run_cli(["sim", str(self.traffic), "--vectors", str(self.vec), "--csv"])
        self.assertEqual(code, 0)
        lines = out.splitlines()
        self.assertEqual(lines[0], "cycle,rst,car_ns,car_ew,light_ns,light_ew")
        self.assertEqual(lines[1], "1,1,0,0,2,0")

    def test_random_and_outputs(self) -> None:
        vcd, vec = self.dir / "o.vcd", self.dir / "o.vec"
        args = ["sim", str(self.traffic), "--random", "8", "--seed", "3"]
        code, first, _ = run_cli([*args, "--vcd", str(vcd), "--save-vectors", str(vec)])
        self.assertEqual(code, 0)
        self.assertTrue(vcd.read_text(encoding="utf-8").startswith("$version wyrd sim $end"))
        text = vec.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# wyrd seed 3 cycles 8"))
        rows = [x for x in text.splitlines() if not x.startswith("#")]
        self.assertEqual([len(x.split()) for x in rows], [3] * 8)
        code, again, _ = run_cli(["sim", str(self.traffic), "--vectors", str(vec)])
        self.assertEqual((code, again), (0, first))

    def test_compile_error(self) -> None:
        bad = self.dir / "bad.v"
        bad.write_text("SYNTAX_ERROR", encoding="utf-8")
        code, _, err = run_cli(["sim", str(bad), "--random", "2"])
        self.assertEqual(code, 2)
        self.assertIn(f"{bad}:2:5: error: syntax: unexpected X", err)

    def test_warning_printed(self) -> None:
        warn = self.dir / "warn.v"
        warn.write_text("WARN_ME", encoding="utf-8")
        code, _, err = run_cli(["sim", str(warn), "--random", "1"])
        self.assertEqual(code, 0)
        self.assertIn(f"{warn}:1:1: warning: unused thing", err)

    def test_vector_error(self) -> None:
        self.vec.write_text("0 100\n1 1\n", encoding="utf-8")
        code, _, err = run_cli(["sim", str(self.traffic), "--vectors", str(self.vec)])
        self.assertEqual(code, 2)
        self.assertIn("2: expected 3 input bits of 0 and 1, found `1`", err)

    def test_missing_vector_file(self) -> None:
        code, _, err = run_cli(["sim", str(self.traffic), "--vectors", str(self.dir / "no.vec")])
        self.assertEqual(code, 2)
        self.assertIn("no.vec", err)

    def test_unavailable(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        patch = mock.patch("wyrd.cli._sim_backend", side_effect=SimUnavailable("odin3 is missing"))
        with patch, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(["sim", str(self.traffic), "--random", "1"])
        self.assertEqual(code, 2)
        self.assertIn("odin3 is missing", err.getvalue())

    def test_usage(self) -> None:
        code, _, _ = run_cli(["sim", str(self.traffic)])
        self.assertEqual(code, 2)

    def test_other_commands_unaffected(self) -> None:
        code = "import wyrd.cli, sys; assert 'wyrd.bifrost' not in sys.modules"
        done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=False)
        self.assertEqual(done.returncode, 0)


if __name__ == "__main__":
    unittest.main()
