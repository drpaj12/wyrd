import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from wyrd import cli, settings
from wyrd.units import parse_bytes

OPTIONAL = {"vtr_root", "vpr_gui"}


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

    def test_machine_file_param(self) -> None:
        p = self.dir / "other.toml"
        p.write_text("[resources]\njobs = 3\n", encoding="utf-8")
        s = settings.load(None, {}, machine_file=p)
        self.assertEqual(s.jobs, 3)
        self.assertEqual(s.sources["jobs"], "machine")

    def test_default_values_and_layout(self) -> None:
        self.assertEqual(settings.default_values()["launcher"], "systemd")
        layout = settings.machine_layout()
        self.assertEqual(layout["tools"], ("odin3", "odin3_flow", "vtr_root", "vpr_gui"))
        out = self.dir / "w.toml"
        settings.write_machine_file(out)
        data = tomllib.loads(out.read_text(encoding="utf-8"))
        written = {k for sub in data.values() for k in sub}
        wanted = {k for keys in layout.values() for k in keys}
        self.assertEqual(wanted - OPTIONAL, written - OPTIONAL)

    def _gui_file(self, mode: int = 0o755) -> Path:
        gui = self.dir / "gfx" / "vpr"
        gui.parent.mkdir(exist_ok=True)
        gui.write_text("#!/bin/sh\n", encoding="utf-8")
        gui.chmod(mode)
        return gui

    def test_vpr_gui_default_none(self) -> None:
        self.assertIsNone(settings.load(None, {}).vpr_gui)

    def test_vpr_gui_set_and_listed(self) -> None:
        gui = self._gui_file()
        p = self.dir / "g.toml"
        p.write_text(f'[tools]\nvpr_gui = "{gui}"\n', encoding="utf-8")
        s = settings.load(None, {}, machine_file=p)
        self.assertEqual(s.vpr_gui, gui)
        self.assertEqual(s.sources["vpr_gui"], "machine")
        self.assertIn("vpr_gui", settings.field_names())
        self.assertNotIn("vpr_gui", s.tools)

    def test_vpr_gui_expands_home(self) -> None:
        gui = self._gui_file()
        p = self.dir / "g.toml"
        p.write_text('[tools]\nvpr_gui = "~/gfx/vpr"\n', encoding="utf-8")
        with mock.patch.dict("os.environ", {"HOME": str(self.dir)}):
            s = settings.load(None, {}, machine_file=p)
        self.assertEqual(s.vpr_gui, gui)

    def test_vpr_gui_must_be_executable_file(self) -> None:
        p = self.dir / "g.toml"
        for bad in (str(self.dir / "absent"), str(self.dir), str(self._gui_file(0o644))):
            p.write_text(f'[tools]\nvpr_gui = "{bad}"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "vpr_gui"):
                settings.load(None, {}, machine_file=p)

    def test_defaults(self) -> None:
        s = settings.load(None, {})
        self.assertEqual(s.tools, {"odin3": "odin3", "odin3_flow": "odin3-flow"})
        self.assertIsNone(s.vtr_root)
        self.assertEqual(s.mem_budget, settings.total_memory() * 60 // 100)
        self.assertEqual(s.jobs, max(1, (os.cpu_count() or 2) // 2))
        self.assertEqual(s.launcher, "systemd")
        self.assertEqual(s.disk_min_free, 20 * 2**30)
        want = "/mnt/c" if settings.is_wsl() else "/"
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

    def _bad(self, text: str, key: str) -> None:
        self.machine.write_text(text)
        with self.assertRaises(ValueError) as cm:
            settings.load(None, {})
        self.assertIn(key, str(cm.exception))

    def test_parse_bytes_rejects_bad_percent_and_huge(self) -> None:
        for bad in ("-5%", "101%", "nan%", "inf%", "1e3%", "9" * 400 + "G", "9" * 400 + "%"):
            with self.assertRaises(ValueError, msg=bad):
                parse_bytes(bad, 100)

    def test_range_checks(self) -> None:
        for key, val, table in [
            ("mem_budget", '"0"', "resources"),
            ("disk_min_free", "0", "resources"),
            ("vpr_mem", "-1", "defaults"),
            ("other_mem", '"0G"', "defaults"),
            ("step_timeout", "0", "defaults"),
            ("history_factor", "0.5", "defaults"),
            ("oom_retry_factor", "0.9", "defaults"),
            ("jobs", "0", "resources"),
        ]:
            self._bad(f"[{table}]\n{key} = {val}\n", key)

    def test_cli_jobs_zero_errors(self) -> None:
        with self.assertRaises(ValueError) as cm:
            settings.load(None, {"jobs": 0})
        self.assertIn("jobs", str(cm.exception))

    def test_tool_named_like_resource_key(self) -> None:
        self.machine.write_text('[tools]\njobs = "/bin/jobs"\nmem_budget = "x"\n')
        s = settings.load(None, {})
        self.assertEqual(s.tools["jobs"], "/bin/jobs")
        self.assertEqual(s.sources["jobs"], "default")
        self.assertEqual(s.sources["mem_budget"], "default")

    def test_unknown_table_and_key(self) -> None:
        self._bad("[bogus]\na = 1\n", "bogus")
        self._bad("[resources]\nnope = 1\n", "nope")
        self._bad("[defaults]\njobs = 1\n", "jobs")

    def test_disk_min_free_percent_rejected(self) -> None:
        self._bad('[resources]\ndisk_min_free = "10%"\n', "disk_min_free")

    def test_config_init_write_error(self) -> None:
        with mock.patch.object(settings, "write_machine_file", side_effect=OSError("denied")):
            self.assertEqual(cli.main(["config", "init"]), 2)

    def test_vtr_root_from_env(self) -> None:
        with mock.patch.dict(os.environ, {"VTR_ROOT": "/opt/vtr"}):
            s = settings.load(None, {})
        self.assertEqual(s.vtr_root, Path("/opt/vtr"))
        self.assertEqual(s.sources["vtr_root"], "default")
