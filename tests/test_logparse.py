import tempfile
import unittest
from pathlib import Path

from wyrd.guimodel.logparse import (
    Message,
    parse_lines,
    parse_log,
    resolve_location,
    step_messages,
)

LOGS = Path(__file__).parent / "data" / "logs"


class LogParseTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_odin3_sample(self) -> None:
        log = LOGS / "odin3_sample.log"
        msgs = parse_log(log)
        self.assertEqual(len(msgs), 6)
        first = "cover mixes on-set and off-set rows (output 0 after 1)"
        self.assertEqual(
            msgs[0], Message("error", "odin3", first, "neg_e8_mixed.in.blif", 7, None, log, 3)
        )
        self.assertEqual(
            (msgs[1].file, msgs[1].line, msgs[1].col, msgs[1].severity),
            ("tri_out.v", 5, 10, "warning"),
        )
        self.assertTrue(msgs[1].text.startswith("tri-state driver"))
        self.assertEqual((msgs[2].file, msgs[2].line), ("neg_e1_fe.in.blif", 5))
        self.assertTrue(msgs[2].text.startswith("write_blif: --vtr: "))
        self.assertEqual((msgs[3].file, msgs[3].line), ("script.abc", 3))
        self.assertIsNone(msgs[4].file)
        self.assertEqual(msgs[4].severity, "warning")
        last = (msgs[5].severity, msgs[5].tool, msgs[5].text)
        self.assertEqual(last, ("warning", "odin3", "something"))
        self.assertFalse(any("pass proc" in m.text for m in msgs))

    def test_vpr_sample(self) -> None:
        msgs = parse_log(LOGS / "vpr_sample.log")
        self.assertEqual(len(msgs), 2)
        self.assertEqual((msgs[0].tool, msgs[0].severity), ("vpr", "warning"))
        self.assertIsNone(msgs[0].file)
        self.assertEqual(msgs[1].severity, "error")
        self.assertEqual(msgs[1].text, "Packing: text here (vpr/src/pack/x.cpp:120)")
        self.assertIsNone(msgs[1].file)
        self.assertEqual(msgs[1].log_line, 3)

    def test_not_a_location(self) -> None:
        lines = [
            "odin3: error: write_blif: --vtr: bad option",
            "odin3: warning: took 10:30 minutes",
            "odin3: error: C:\\x\\y.v:3: oops",
        ]
        msgs = parse_lines(lines, Path("l.log"))
        for m in msgs[:2]:
            self.assertIsNone(m.file)
            self.assertIsNone(m.line)
        self.assertFalse(any(m.line == 30 for m in msgs))

    def test_vpr_blank_line_before_fields(self) -> None:
        lines = ["Error 2: ", "", "Type: Route", "Message: boom"]
        msgs = parse_lines(lines, Path("l.log"))
        self.assertEqual([m.text for m in msgs], ["Route: boom"])

    def test_unreadable_log(self) -> None:
        self.assertEqual(parse_log(self.dir / "missing.log"), [])

    def test_dedupe(self) -> None:
        line = "odin3: error: a.v:3: broken\n"
        (self.dir / "out" / "odin3").mkdir(parents=True)
        (self.dir / "stderr.log").write_text(line, encoding="utf-8")
        (self.dir / "out" / "odin3" / "odin3.log").write_text(line, encoding="utf-8")
        self.assertEqual(len(step_messages(self.dir)), 1)

    def test_resolve(self) -> None:
        (self.dir / "sub").mkdir()
        src = self.dir / "sub" / "a.v"
        src.write_text("x", encoding="utf-8")
        log = Path("l.log")

        def msg(file: str) -> Message:
            return Message("error", "odin3", "t", file, 4, None, log, 9)

        self.assertEqual(resolve_location(msg("sub/a.v"), [self.dir]), (src, 4))
        self.assertEqual(resolve_location(msg(str(src)), []), (src, 4))
        one = [self.dir / "sub" / "a.v"]
        self.assertEqual(resolve_location(msg("zzz/a.v"), [], one), (src, 4))
        two = [*one, self.dir / "other" / "a.v"]
        self.assertEqual(resolve_location(msg("zzz/a.v"), [], two), (log, 9))
        self.assertEqual(resolve_location(msg("gone.v"), [self.dir]), (log, 9))


if __name__ == "__main__":
    unittest.main()
