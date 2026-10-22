import unittest

from wyrd.bifrost.diagnostics import parse_log
from wyrd.bifrost.errors import (
    CompileError,
    NoSuchSignal,
    SessionClosed,
    ValueRangeError,
    VectorError,
)
from wyrd.bifrost.types import Diagnostic

PARSE_ERR = "/tmp/x/bad.v:2:39: error: syntax: unexpected ';'"


class ParseLogTest(unittest.TestCase):
    def test_parse_error_located(self) -> None:
        records = [
            (0, PARSE_ERR),
            (0, "pass read_verilog: failed: ODIN3_ERR_PARSE"),
            (2, "pass read_verilog: 0.123 ms"),
            (0, "python: command 1: pass 'read_verilog' failed: ODIN3_ERR_PARSE"),
        ]
        self.assertEqual(
            parse_log(records),
            (Diagnostic("error", "syntax: unexpected ';'", "/tmp/x/bad.v", 2, 39, raw=PARSE_ERR),),
        )

    def test_warning(self) -> None:
        raw = "/tmp/x/bad.v:2:13: warning: 'b' is implicitly declared"
        (d,) = parse_log([(1, raw)])
        self.assertEqual(
            (d.severity, d.message, d.line, d.col), ("warning", "'b' is implicitly declared", 2, 13)
        )

    def test_missing_port(self) -> None:
        raw = (
            "Lv0/VerilogFiles/Traffic_signal_set_0.v:4:14: error: 'debug_port' is declared as a "
            "port but is not in the port list"
        )
        (d,) = parse_log([(0, raw)])
        self.assertEqual(d.file, "Lv0/VerilogFiles/Traffic_signal_set_0.v")
        self.assertEqual((d.line, d.col), (4, 14))
        self.assertEqual(
            d.message, "'debug_port' is declared as a port but is not in the port list"
        )

    def test_line_without_col(self) -> None:
        (d,) = parse_log([(0, "a.blif:7: cover mixes on-set and off-set rows")])
        self.assertEqual((d.file, d.line, d.col), ("a.blif", 7, None))

    def test_level_decides_severity(self) -> None:
        (d,) = parse_log([(1, "f.v:3:4: something odd")])
        self.assertEqual((d.severity, d.message), ("warning", "something odd"))

    def test_unlocated_kept(self) -> None:
        (d,) = parse_log([(0, "the design has no top module"), (2, "info text")])
        self.assertEqual((d.file, d.line, d.col, d.severity), (None, None, None, "error"))
        self.assertEqual(d.message, "the design has no top module")

    def test_path_with_space(self) -> None:
        (d,) = parse_log([(0, "/a b/c.v:9:1: error: x")])
        self.assertEqual(d.file, "/a b/c.v")

    def test_error_texts(self) -> None:
        (first,) = parse_log([(0, PARSE_ERR)])
        self.assertEqual(str(CompileError([first])), "/tmp/x/bad.v:2:39: syntax: unexpected ';'")
        (unlocated,) = parse_log([(0, "the design has no top module")])
        self.assertEqual(str(CompileError([unlocated])), "the design has no top module")
        self.assertEqual(
            str(NoSuchSignal("dead_r")),
            "dead_r: not in the simulated netlist (a pass may have removed it: mark it "
            "(* keep *) in the HDL, or see BifrostSession.signals())",
        )
        self.assertEqual(str(VectorError(3, "bad")), "3: bad")
        self.assertTrue(issubclass(ValueRangeError, ValueError))
        self.assertTrue(issubclass(SessionClosed, RuntimeError))

    def test_compile_error_message_override(self) -> None:
        self.assertEqual(str(CompileError([], "custom")), "custom")
        self.assertEqual(str(CompileError([])), "compile failed")


if __name__ == "__main__":
    unittest.main()
