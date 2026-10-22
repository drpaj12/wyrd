import tempfile
import unittest
from pathlib import Path

from wyrd.guimodel.floorplan import FloorplanPlan, plan_floorplan

VIEW = ("--disp", "on", "--graphics_pause", "final_stage")


class FloorplanTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vpr = self.root / "bin" / "vpr"
        self.vpr.parent.mkdir()
        self.vpr.write_text("#!/bin/sh\n", encoding="utf-8")
        self.vpr.chmod(0o755)
        self.run_dir = self.root / "run"
        self.step = self.run_dir / "0-odin3-flow"
        self.work = self.step / "out" / "vpr" / "run"
        self.work.mkdir(parents=True)
        self.blif = self.work / "top.pre-vpr.blif"
        self.blif.write_text("x", encoding="utf-8")
        self.write_cmd("odin3-flow a.v --arch /arch/k6.xml --vpr --out OUT")
        self.write_log(
            f"{self.vpr} k6.xml top --circuit_file top.pre-vpr.blif "
            "--max_router_iterations 100 --route --analysis --route_chan_width 42"
        )

    @staticmethod
    def echo(vpr: str, opts: str) -> str:
        return f"{vpr} k6.xml top --circuit_file top.pre-vpr.blif {opts}"

    def write_cmd(self, line: str) -> None:
        text = f"#!/bin/sh\ncd {self.step}\n{line}\n"
        (self.step / "cmd.sh").write_text(text, encoding="utf-8")

    def write_log(self, echo: str) -> None:
        text = f"VPR FPGA Placement and Routing.\n{echo}\nother\n"
        (self.work / "vpr_stdout.log").write_text(text, encoding="utf-8")

    def test_rerun(self) -> None:
        got = plan_floorplan(self.run_dir)
        want = FloorplanPlan(
            str(self.vpr),
            ("/arch/k6.xml", "top", "--circuit_file", str(self.blif),
             "--max_router_iterations", "100", "--pack", "--place", "--route",
             "--route_chan_width", "42", *VIEW),
            self.run_dir / "floorplan",
            "rerun",
        )  # fmt: skip
        self.assertEqual(got, want)
        self.assertFalse((self.run_dir / "floorplan").exists())

    def test_replay(self) -> None:
        for ext in ("net", "place", "route"):
            (self.work / f"top.{ext}").write_text("x", encoding="utf-8")
        got = plan_floorplan(self.run_dir)
        assert isinstance(got, FloorplanPlan)
        w = self.work
        self.assertEqual(got.mode, "replay")
        self.assertEqual(
            got.args,
            ("/arch/k6.xml", "top", "--circuit_file", str(self.blif),
             "--net_file", str(w / "top.net"), "--place_file", str(w / "top.place"),
             "--route_file", str(w / "top.route"), "--route", "--analysis",
             "--route_chan_width", "42", *VIEW),
        )  # fmt: skip

    def test_no_iterations_option(self) -> None:
        self.write_log(self.echo(str(self.vpr), "--route_chan_width 8"))
        got = plan_floorplan(self.run_dir)
        assert isinstance(got, FloorplanPlan)
        self.assertNotIn("--max_router_iterations", got.args)

    def test_last_echo_wins(self) -> None:
        first = self.echo(str(self.vpr), "--route_chan_width 7")
        second = self.echo(str(self.vpr), "--route_chan_width 9")
        (self.work / "vpr_stdout.log").write_text(f"{first}\n{second}\n", encoding="utf-8")
        got = plan_floorplan(self.run_dir)
        assert isinstance(got, FloorplanPlan)
        self.assertIn("9", got.args)

    def test_errors(self) -> None:
        log = self.work / "vpr_stdout.log"
        self.write_log("no echo here")
        self.assertEqual(plan_floorplan(self.run_dir), "no VPR command line in vpr_stdout.log")
        self.write_log(self.echo(str(self.vpr), "--route"))
        self.assertEqual(plan_floorplan(self.run_dir), "no --route_chan_width in the VPR command")
        self.write_log(self.echo("/nope/vpr", "--route_chan_width 4"))
        self.assertEqual(plan_floorplan(self.run_dir), "VPR binary not found: /nope/vpr")
        self.write_log(self.echo(str(self.vpr), "--route_chan_width 4"))
        self.blif.unlink()
        self.assertEqual(plan_floorplan(self.run_dir), f"circuit file not found: {self.blif}")
        self.write_cmd("odin3-flow a.v --vpr")
        self.assertEqual(plan_floorplan(self.run_dir), "arch path not found in cmd.sh")
        log.unlink()
        self.assertEqual(plan_floorplan(self.run_dir), "no VPR log in this run")
        self.assertEqual(plan_floorplan(self.root / "missing"), "no VPR log in this run")


if __name__ == "__main__":
    unittest.main()
