import dataclasses
import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import make_project, make_settings, shell, sleepy
from wyrd.model import StepSpec
from wyrd.preflight import ProjectLocked, acquire_lock, preflight


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_ok(self) -> None:
        project = make_project(self.root, {"a": 1}, [sleepy()])
        self.assertEqual(preflight(project, make_settings()), [])

    def test_preflight_missing_tool(self) -> None:
        project = make_project(self.root, {"a": 1}, [StepSpec("odin3", {"argv": ["odin3", "x"]})])
        s = make_settings(tools={"odin3": "no-such-tool-xyz", "odin3_flow": "odin3-flow"})
        problems = preflight(project, s)
        self.assertEqual(len(problems), 1)
        self.assertIn("no-such-tool-xyz", problems[0])
        self.assertFalse((self.root / "runs").exists())

    def test_existing_path_tool_resolves(self) -> None:
        exe = self.root / "mytool"
        exe.write_text("#!/bin/sh\n")
        exe.chmod(0o755)
        project = make_project(self.root, {"a": 1}, [StepSpec("odin3", {"argv": ["odin3"]})])
        s = make_settings(tools={"odin3": str(exe), "odin3_flow": "odin3-flow"})
        self.assertEqual(preflight(project, s), [])

    def test_bad_recipe_args_reported(self) -> None:
        project = make_project(self.root, {"a": 1}, [StepSpec("shell", {}), StepSpec("nope", {})])
        problems = preflight(project, make_settings())
        self.assertEqual(len(problems), 1)
        self.assertIn("argv", problems[0])

    def test_unknown_step_reported(self) -> None:
        project = make_project(self.root, {"a": 1}, [StepSpec("nope", {})])
        problems = preflight(project, make_settings())
        self.assertEqual(len(problems), 1)
        self.assertIn("nope", problems[0])

    def test_vtr_root_and_arch_missing(self) -> None:
        step = shell("echo", "{arch_xml}")
        project = make_project(self.root, {"a": 1}, [step])
        self.assertTrue(any("vtr_root" in p for p in preflight(project, make_settings())))
        vtr = self.root / "vtr"
        vtr.mkdir()
        problems = preflight(project, make_settings(vtr_root=vtr))
        self.assertEqual(len(problems), 1)
        self.assertIn("k6.xml", problems[0])
        arch = vtr / "vtr_flow" / "arch" / "timing" / "k6.xml"
        arch.parent.mkdir(parents=True)
        arch.write_text("<arch/>")
        self.assertEqual(preflight(project, make_settings(vtr_root=vtr)), [])

    def test_disk_check(self) -> None:
        project = make_project(self.root, {"a": 1}, [sleepy()])
        s = make_settings(disk_min_free=2**62, disk_check_path=self.root)
        problems = preflight(project, s)
        self.assertEqual(len(problems), 1)
        self.assertIn("free", problems[0])

    def test_systemd_launcher_needs_systemd_run(self) -> None:
        project = make_project(self.root, {"a": 1}, [sleepy()])
        s = dataclasses.replace(make_settings(), launcher="systemd")
        problems = preflight(project, s)
        self.assertTrue(all("systemd-run" in p for p in problems))

    def test_second_run_is_locked(self) -> None:
        fd = acquire_lock(self.root)
        self.addCleanup(os.close, fd)
        with self.assertRaisesRegex(ProjectLocked, "project is locked"):
            acquire_lock(self.root)


if __name__ == "__main__":
    unittest.main()
