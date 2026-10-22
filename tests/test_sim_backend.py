import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.fakes_sim import TRAFFIC_SIGNALS, FakeBackend, make_fake_odin3
from wyrd.bifrost.backend import Odin3Backend, default_backend, odin3_available
from wyrd.bifrost.errors import CompileError, SimUnavailable


class Odin3BackendTest(unittest.TestCase):
    def test_missing_odin3(self) -> None:
        with mock.patch.dict(sys.modules, {"odin3": None}):
            with self.assertRaises(SimUnavailable) as cm:
                Odin3Backend()
            self.assertIn('pip install "wyrd[sim]"', str(cm.exception))
            self.assertFalse(odin3_available())

    def test_too_old(self) -> None:
        with mock.patch.dict(sys.modules, {"odin3": make_fake_odin3(has_simulation=False)}):
            with self.assertRaises(SimUnavailable) as cm:
                Odin3Backend()
            self.assertIn("1.0.3", str(cm.exception))
            self.assertFalse(odin3_available())

    def test_compile_script(self) -> None:
        fake = make_fake_odin3()
        with mock.patch.dict(sys.modules, {"odin3": fake}):
            Odin3Backend().compile([Path("/a b/x.v"), Path("/y.v")])
            self.assertEqual(
                fake.Design.scripts, ['read_verilog "/a b/x.v" "/y.v"; proc; opt; lower']
            )
            with self.assertRaises(CompileError):
                Odin3Backend().compile([Path('/a"b.v')])

    def test_compile_failure_gives_diagnostics(self) -> None:
        records = [
            (0, "/y.v:3:1: error: syntax: unexpected endmodule"),
            (0, "pass read_verilog: failed: ODIN3_ERR_PARSE"),
        ]
        fake = make_fake_odin3(fail_with=records)
        with mock.patch.dict(sys.modules, {"odin3": fake}), self.assertRaises(CompileError) as cm:
            Odin3Backend().compile([Path("/y.v")])
        (d,) = cm.exception.diagnostics
        self.assertEqual((d.file, d.line), ("/y.v", 3))

    def test_warnings_kept(self) -> None:
        fake = make_fake_odin3(warnings=[(1, "/y.v:1:2: warning: w")])
        with mock.patch.dict(sys.modules, {"odin3": fake}):
            compiled = Odin3Backend().compile([Path("/y.v")])
        self.assertEqual(compiled.diagnostics[0].severity, "warning")

    def test_open_maps_signals(self) -> None:
        with mock.patch.dict(sys.modules, {"odin3": make_fake_odin3()}):
            compiled = Odin3Backend().compile([Path("/y.v")])
            handle = compiled.open(None)
            self.assertEqual(tuple(handle.signals()), TRAFFIC_SIGNALS)
            self.assertIsNone(handle.signal("nope"))
            self.assertEqual(handle.get("light_ns"), 2)
            handle.set("rst", 1)
            handle.step(1)
            self.assertEqual(handle.cycle, 1)
            with self.assertRaises(CompileError):
                compiled.open("nope")
            handle.close()
            handle.close()
            compiled.close()

    def test_default_backend(self) -> None:
        with mock.patch.dict(sys.modules, {"odin3": make_fake_odin3()}):
            self.assertIsInstance(default_backend(), Odin3Backend)
            self.assertTrue(odin3_available())


class FakeBackendTest(unittest.TestCase):
    def test_fake_backend_traffic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "traffic.v"
            path.write_text("module traffic", encoding="utf-8")
            backend = FakeBackend()
            handle = backend.compile([path]).open(None)
        handle.set("rst", 1)
        handle.step(1)
        self.assertEqual(handle.get("light_ns"), 2)
        self.assertEqual(handle.get("light_ew"), 0)
        with self.assertRaises(ValueError):
            handle.set("light_ns", 1)
        with self.assertRaises(KeyError):
            handle.get("nope")


if __name__ == "__main__":
    unittest.main()
