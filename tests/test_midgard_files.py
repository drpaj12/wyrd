import os
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from wyrd.midgard.model import ASSETS
from wyrd.midgard.model.scores import ScoreTable, format_time
from wyrd.midgard.model.userdata import UserData, default_data_dir
from wyrd.midgard.model.watch import FileWatcher, editor_command


class ScoreTest(unittest.TestCase):
    def test_score_insert(self) -> None:
        t = ScoreTable()
        self.assertEqual(t.insert(5, 40), 0)
        self.assertEqual(t.insert(7, 50), 0)
        self.assertEqual(t.entries[:3], [(7, 50), (5, 40), (0, 0)])
        self.assertEqual(t.insert(5, 30), 1)
        self.assertIsNone(t.insert(5, 30))
        self.assertIsNone(t.insert(0, 10))
        self.assertEqual(t.entries[:4], [(7, 50), (5, 30), (5, 40), (0, 0)])
        self.assertEqual(len(t.entries), 10)

    def test_score_overflow(self) -> None:
        t = ScoreTable()
        for k in range(1, 12):
            self.assertIsNotNone(t.insert(k, 100))
        self.assertEqual(len(t.entries), 10)
        self.assertEqual(t.entries[0], (11, 100))
        self.assertEqual(t.entries[-1], (2, 100))
        self.assertIsNone(t.insert(1, 5))
        rows = [(9, 1), (8, 1), (7, 1), (6, 1), (5, 1), (4, 1), (4, 2), (4, 3), (4, 4), (3, 9)]
        t2 = ScoreTable(rows)
        self.assertEqual(t2.insert(7, 50), 3)
        self.assertEqual(t2.entries[3], (7, 50))
        self.assertNotIn((3, 9), t2.entries)

    def test_score_text(self) -> None:
        t = ScoreTable()
        for c, k in ((5, 40), (7, 50), (5, 30)):
            t.insert(c, k)
        text = "7 50\n5 30\n5 40\n0 0\n0 0\n0 0\n0 0\n0 0\n0 0\n0 0\n"
        self.assertEqual(t.to_text(), text)
        self.assertEqual(ScoreTable.from_text(text).entries, t.entries)
        self.assertEqual(ScoreTable.from_text("").entries, [(0, 0)] * 10)
        junk = ScoreTable.from_text("garbage\n3 4 5\n-1 7\n9 x\n")
        self.assertEqual(junk.entries, [(0, 0)] * 10)
        self.assertEqual(ScoreTable.from_text("4 10\n9 20\n").entries[:2], [(9, 20), (4, 10)])

    def test_format_time(self) -> None:
        self.assertEqual(format_time(0), "00:00")
        self.assertEqual(format_time(59), "00:00")
        self.assertEqual(format_time(60), "00:01")
        self.assertEqual(format_time(7500), "02:05")
        self.assertEqual(format_time(360000), "100:00")


class UserDataTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def test_default_data_dir(self) -> None:
        home = Path("/h")
        self.assertEqual(default_data_dir({"MIDGARD_HOME": "/x"}, home), Path("/x"))
        self.assertEqual(default_data_dir({"XDG_DATA_HOME": "/y"}, home), Path("/y/midgard"))
        self.assertEqual(default_data_dir({}, home), Path("/h/.local/share/midgard"))

    def test_userdata(self) -> None:
        ud = UserData(self.tmp / "d")
        paths = ud.ensure_level_files(1, 2)
        self.assertEqual(paths, ud.verilog_paths(1, 2))
        self.assertEqual(paths[1], self.tmp / "d/Lv1/VerilogFiles/Traffic_signal_set_1.v")
        starter = (ASSETS / "starter.v").read_text(encoding="utf-8")
        for p in paths:
            self.assertEqual(p.read_text(encoding="utf-8"), starter)
        paths[0].write_text("mine", encoding="utf-8")
        ud.ensure_level_files(1, 2)
        self.assertEqual(paths[0].read_text(encoding="utf-8"), "mine")

    def test_sensors_and_scores_roundtrip(self) -> None:
        ud = UserData(self.tmp)
        sensors = ud.load_sensors(1)
        self.assertTrue(all(not s.placed for s in sensors.sensors))
        sensors.sensors[6].x, sensors.sensors[6].y = 5, 15
        self.assertIsNone(ud.save_sensors(1, sensors))
        again = ud.load_sensors(1)
        self.assertEqual((again.sensors[6].x, again.sensors[6].y), (5, 15))
        table = ScoreTable([(3, 7)])
        self.assertIsNone(ud.save_scores(1, table))
        self.assertEqual(ud.load_scores(1).entries[0], (3, 7))
        (self.tmp / "Lv2").mkdir()
        (self.tmp / "Lv2/high_score.txt").write_bytes(b"\xff\xfe junk\n\x00\n")
        self.assertEqual(ud.load_scores(2).entries, [(0, 0)] * 10)
        self.assertEqual(ud.load_scores(5).entries, [(0, 0)] * 10)
        self.assertEqual(ud.recordings_dir(3), self.tmp / "Lv3/recordings")

    @unittest.skipIf(os.geteuid() == 0, "root ignores permissions")
    def test_save_into_read_only_dir(self) -> None:
        ud = UserData(self.tmp)
        ud.ensure_level_files(1, 1)
        level = self.tmp / "Lv1"
        os.chmod(level, 0o500)
        self.addCleanup(os.chmod, level, 0o700)
        msg = ud.save_sensors(1, ud.load_sensors(1))
        self.assertIsNotNone(msg)


class WatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.files = [self.tmp / f"{k}.v" for k in range(3)]
        for f in self.files:
            f.write_text("a", encoding="utf-8")

    def test_watcher(self) -> None:
        w = FileWatcher(self.files)
        self.assertEqual(w.poll(), [])
        f = self.files[1]
        f.write_text("bb", encoding="utf-8")
        os.utime(f, ns=(10**18, 10**18))
        self.assertEqual(w.poll(), [f])
        self.assertEqual(w.poll(), [])
        f.unlink()
        self.assertEqual(w.poll(), [f])
        self.assertEqual(w.poll(), [])
        f.write_text("c", encoding="utf-8")
        self.assertEqual(w.poll(), [f])

    def test_atomic_replace(self) -> None:
        w = FileWatcher(self.files)
        tmp = self.tmp / "new.tmp"
        tmp.write_text("a", encoding="utf-8")
        os.utime(tmp, ns=(10**18 + 5, 10**18 + 5))
        os.replace(tmp, self.files[0])
        self.assertEqual(w.poll(), [self.files[0]])

    def test_set_paths(self) -> None:
        w = FileWatcher(self.files[:1])
        w.set_paths(self.files)
        self.assertEqual(w.poll(), [])


class EditorCommandTest(unittest.TestCase):
    def test_editor_command(self) -> None:
        p = Path("/p/a.v")

        def finds(*names: str) -> Callable[[str], str | None]:
            return lambda n: f"/bin/{n}" if n in names else None

        self.assertEqual(
            editor_command(p, {"MIDGARD_EDITOR": "myed --wait"}, finds()),
            ["myed", "--wait", "/p/a.v"],
        )
        self.assertEqual(editor_command(p, {}, finds("code")), ["code", "/p/a.v"])
        self.assertEqual(editor_command(p, {}, finds("xdg-open")), ["xdg-open", "/p/a.v"])
        self.assertEqual(editor_command(p, {}, finds("wslview")), ["wslview", "/p/a.v"])
        self.assertIsNone(editor_command(p, {}, finds()))
        self.assertEqual(editor_command(p, {}, finds("code", "xdg-open")), ["code", "/p/a.v"])


if __name__ == "__main__":
    unittest.main()
