import unittest

from wyrd.guimodel.verilog_lex import KEYWORDS, Span, tokenize_line


class VerilogLexTest(unittest.TestCase):
    def test_keyword_and_line_comment(self) -> None:
        spans, open_ = tokenize_line("module top; // hi", False)
        self.assertEqual(spans, [Span(0, 6, "keyword"), Span(12, 5, "comment")])
        self.assertFalse(open_)

    def test_numbers(self) -> None:
        line = "wire [7:0] x = 8'hFF;"
        spans, _ = tokenize_line(line, False)
        self.assertIn(Span(0, 4, "keyword"), spans)
        numbers = [line[s.start : s.start + s.length] for s in spans if s.kind == "number"]
        self.assertEqual(numbers, ["7", "0", "8'hFF"])

    def test_number_forms(self) -> None:
        line = "'b1 4'sd9 1_000 1.5e-3 3'bx"
        spans, _ = tokenize_line(line, False)
        got = [line[s.start : s.start + s.length] for s in spans if s.kind == "number"]
        self.assertEqual(got, ["'b1", "4'sd9", "1_000", "1.5e-3", "3'bx"])

    def test_string_hides_comment(self) -> None:
        spans, _ = tokenize_line('"a // b"', False)
        self.assertEqual(spans, [Span(0, 8, "string")])

    def test_unterminated_string(self) -> None:
        spans, open_ = tokenize_line('x = "abc', False)
        self.assertEqual(spans, [Span(4, 4, "string")])
        self.assertFalse(open_)

    def test_directive(self) -> None:
        spans, _ = tokenize_line("`define X 1", False)
        self.assertEqual(spans[0], Span(0, 7, "directive"))

    def test_system_task_and_string(self) -> None:
        spans, _ = tokenize_line('$display("x")', False)
        self.assertEqual(spans, [Span(0, 8, "system"), Span(9, 3, "string")])

    def test_block_comment_across_lines(self) -> None:
        self.assertEqual(tokenize_line("/* a", False), ([Span(0, 4, "comment")], True))
        spans, open_ = tokenize_line(" b */ wire x;", True)
        self.assertEqual(spans, [Span(0, 5, "comment"), Span(6, 4, "keyword")])
        self.assertFalse(open_)
        self.assertEqual(tokenize_line(" still", True), ([Span(0, 6, "comment")], True))

    def test_identifier_is_not_keyword(self) -> None:
        self.assertEqual(tokenize_line("module_x", False), ([], False))
        self.assertEqual(tokenize_line("x1 = y;", False), ([], False))

    def test_keyword_set(self) -> None:
        for word in ("module", "endmodule", "always_ff", "logic", "xor"):
            self.assertIn(word, KEYWORDS)


if __name__ == "__main__":
    unittest.main()
