import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wyrd import settings
from wyrd.guimodel import machine
from wyrd.guimodel.machine import FIELDS, MachineValues


class MachineTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"WYRD_CONFIG": str(self.dir / "none.toml")})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("VTR_ROOT", None)

    def test_fields_match_layout(self) -> None:
        want = {f"{t}.{k}" for t, keys in settings.machine_layout().items() for k in keys}
        self.assertEqual({f"{f.table}.{f.key}" for f in FIELDS}, want)

    def test_roundtrip(self) -> None:
        p = self.dir / "m.toml"
        settings.write_machine_file(p)
        first = machine.read_values(p)
        p2 = self.dir / "m2.toml"
        p2.write_text(machine.render(first), encoding="utf-8")
        second = machine.read_values(p2)
        self.assertEqual(first.values, second.values)
        self.assertIsNone(machine.validate(first))

    def test_missing_file_gives_defaults(self) -> None:
        v = machine.read_values(self.dir / "absent.toml")
        self.assertEqual(v.values["resources.launcher"], "systemd")
        self.assertEqual(v.values["tools.vtr_root"], "")
        self.assertNotIn("vtr_root", machine.render(v))

    def test_extra_tools_kept(self) -> None:
        p = self.dir / "m.toml"
        p.write_text('[tools]\nfoo = "bar"\n[resources]\njobs = 3\n', encoding="utf-8")
        v = machine.read_values(p)
        self.assertEqual(v.extra_tools, {"foo": "bar"})
        self.assertEqual(v.values["resources.jobs"], "3")
        self.assertIn('foo = "bar"', machine.render(v))
        self.assertLess(machine.render(v).index("odin3_flow"), machine.render(v).index("foo"))

    def test_validate_bad(self) -> None:
        v = machine.read_values(self.dir / "absent.toml")
        v.values["resources.jobs"] = "x"
        err = machine.validate(v)
        self.assertIsInstance(err, str)
        assert err
        v.values["resources.jobs"] = "2"
        v.values["resources.mem_budget"] = "lots"
        self.assertIsInstance(machine.validate(v), str)
        v.values["resources.mem_budget"] = "60%"
        v.values["resources.launcher"] = "docker"
        self.assertIsInstance(machine.validate(v), str)

    def _base(self) -> MachineValues:
        return machine.read_values(self.dir / "absent.toml")

    def test_render_refuses_bad_numbers(self) -> None:
        for bad in ("", "  ", "abc", "1 2", "1\nx = 2", "0x10", "007"):
            v = self._base()
            v.values["resources.jobs"] = bad
            with self.assertRaises(ValueError, msg=repr(bad)):
                machine.render(v)
            self.assertIsInstance(machine.validate(v), str)
        v = self._base()
        v.values["defaults.history_factor"] = ""
        self.assertIsInstance(machine.validate(v), str)

    def test_render_refuses_newline_and_quote(self) -> None:
        for bad in ('a"b', "a\nb", "a\rb", "a'b"):
            v = self._base()
            v.values["tools.odin3"] = bad
            with self.assertRaises(ValueError, msg=repr(bad)):
                machine.render(v)
            err = machine.validate(v)
            assert err
            self.assertNotIn("TOML", err)
            w = self._base()
            w.extra_tools["foo"] = bad
            with self.assertRaises(ValueError):
                machine.render(w)

    def test_launcher_error_text(self) -> None:
        v = self._base()
        v.values["resources.launcher"] = "docker"
        self.assertEqual(machine.validate(v), "launcher: must be one of systemd, plain")

    def test_save_creates_dir(self) -> None:
        target = self.dir / "new" / "sub" / "machine.toml"
        v = machine.read_values(target)
        machine.save(target, v)
        self.assertTrue(target.is_file())
        self.assertEqual(machine.read_values(target).values, v.values)

    def test_save_refuses_bad_values(self) -> None:
        target = self.dir / "machine.toml"
        v = MachineValues(machine.read_values(target).values)
        v.values["resources.jobs"] = "0"
        with self.assertRaises(ValueError):
            machine.save(target, v)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
