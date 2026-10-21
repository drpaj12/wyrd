import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wyrd import cli, settings
from wyrd.units import parse_bytes


class SettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.machine = self.dir / "machine.toml"
        env = mock.patch.dict(os.environ, {"WYRD_CONFIG": str(self.machine)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("VTR_ROOT", None)

    def test_parse_bytes(self) -> None:
        self.assertEqual(parse_bytes("4G"), 4 * 2**30)
        self.assertEqual(parse_bytes("512M"), 512 * 2**20)
        self.assertEqual(parse_bytes("60%", 100), 60)
        with self.assertRaises(ValueError):
            parse_bytes("4X")

    def test_defaults(self) -> None:
        s = settings.load(None, {})
        self.assertEqual(s.tools, {"odin3": "odin3", "odin3_flow": "odin3-flow"})
        self.assertIsNone(s.vtr_root)
        self.assertEqual(s.mem_budget, settings.total_memory() * 60 // 100)
        self.assertEqual(s.jobs, max(1, (os.cpu_count() or 2) // 2))
        self.assertEqual(s.launcher, "systemd")
        self.assertEqual(s.disk_min_free, 20 * 2**30)
        want = "/mnt/c" if "microsoft" in Path("/proc/version").read_text().lower() else "/"
        self.assertEqual(s.disk_check_path, Path(want))
        self.assertEqual(s.vpr_mem, 4 * 2**30)
        self.assertEqual(s.other_mem, 2 * 2**30)
        self.assertEqual(s.history_factor, 1.25)
        self.assertEqual(s.oom_retry_factor, 2.0)
        self.assertEqual(s.step_timeout, 3600)
        self.assertEqual(set(s.sources.values()), {"default"})

    def test_machine_overrides_default(self) -> None:
        self.machine.write_text('[resources]\njobs = 8\n[defaults]\nvpr_mem = "6G"\n')
        s = settings.load(None, {})
        self.assertEqual(s.jobs, 8)
        self.assertEqual(s.vpr_mem, 6 * 2**30)
        self.assertEqual(s.sources["jobs"], "machine")
        self.assertEqual(s.sources["other_mem"], "default")

    def test_project_run_only_step_timeout(self) -> None:
        s = settings.load({"step_timeout": 10}, {})
        self.assertEqual((s.step_timeout, s.sources["step_timeout"]), (10, "project"))
        with self.assertRaises(ValueError) as cm:
            settings.load({"jobs": 3}, {})
        self.assertIn("jobs", str(cm.exception))

    def test_cli_wins(self) -> None:
        self.machine.write_text("[resources]\njobs = 8\n")
        s = settings.load(None, {"jobs": 2})
        self.assertEqual((s.jobs, s.sources["jobs"]), (2, "cli"))

    def test_config_init_roundtrip(self) -> None:
        before = settings.load(None, {})
        settings.write_machine_file(self.machine)
        after = settings.load(None, {})
        for name in settings.field_names():
            self.assertEqual(getattr(before, name), getattr(after, name), name)
        self.assertEqual(after.sources["jobs"], "machine")

    def test_cli_config_commands(self) -> None:
        self.assertEqual(cli.main(["config", "init"]), 0)
        self.assertTrue(self.machine.is_file())
        self.assertEqual(cli.main(["config", "init"]), 2)
        self.assertEqual(cli.main(["config", "show"]), 0)
