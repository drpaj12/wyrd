import unittest

from tests.fakes_sim import TRACE_IN, traffic_session
from wyrd.bifrost.errors import VectorError
from wyrd.bifrost.types import Signal
from wyrd.bifrost.vectors import (
    VectorFile,
    format_vectors,
    parse_vectors,
    random_rows,
    random_vectors,
    session_ports,
)

EXPECTED = """\
# wyrd seed 0 cycles 2
# clock clk 0
# input rst 1
# input car_ns 1
# input car_ew 1
# output light_ns 2
# output light_ew 2
0 100 1000
1 001 0100
"""

VF2 = VectorFile(((1, 0, 0), (0, 0, 1)))


def ports_outs() -> tuple[tuple[Signal, ...], tuple[Signal, ...]]:
    return session_ports(traffic_session())


class VectorFormatTest(unittest.TestCase):
    def test_session_ports(self) -> None:
        ports, outs = ports_outs()
        self.assertEqual([p.name for p in ports], ["clk", "rst", "car_ns", "car_ew"])
        self.assertEqual([o.name for o in outs], ["light_ns", "light_ew"])

    def test_format_exact(self) -> None:
        s = traffic_session()
        ports, outs = session_ports(s)
        rec = s.run_vectors(VF2)
        self.assertEqual(format_vectors(VF2, ports, outs, recording=rec), EXPECTED)
        plain = format_vectors(VF2, ports, outs).splitlines()
        self.assertEqual(plain[-2:], ["0 100", "1 001"])

    def test_roundtrip(self) -> None:
        ports, outs = ports_outs()
        vf = random_vectors(ports, 20, 5)
        self.assertEqual(parse_vectors(format_vectors(vf, ports, outs), ports, outs), vf)

    def test_parse_lenient(self) -> None:
        ports, outs = ports_outs()
        plain = parse_vectors("0 100\n1 001\n", ports, outs)
        messy = "# note\r\n\r\n0 100\r\n\r\n# another note\r\n1\t001 0100\r\n"
        self.assertEqual(parse_vectors(messy, ports, outs), plain)
        self.assertEqual(plain, VF2)
        header = format_vectors(VectorFile(()), ports, outs)
        self.assertEqual(parse_vectors(header, ports, outs).rows, ())

    def check_error(self, text: str, line: int, message: str) -> None:
        ports, outs = ports_outs()
        with self.assertRaises(VectorError) as cm:
            parse_vectors(text, ports, outs)
        self.assertEqual((cm.exception.line, cm.exception.message), (line, message))

    def test_parse_errors(self) -> None:
        self.check_error(
            "# wyrd seed 0 cycles 1\n# clock clk 0\n# input rst 2\n",
            3,
            "port line `# input rst 2` does not match the design: expected `# input rst 1`",
        )
        self.check_error("0 10\n", 1, "expected 3 input bits of 0 and 1, found `10`")
        self.check_error("1 100\n", 1, "expected cycle 0, found `1`")
        self.check_error("\n0 100 00 extra\n", 2, "expected `<cycle> <inputs> [<outputs>]`")
        self.check_error("0 1x0\n", 1, "expected 3 input bits of 0 and 1, found `1x0`")
        self.check_error("0 100\n2 001\n", 2, "expected cycle 1, found `2`")

    def test_port_line_count(self) -> None:
        ports, outs = ports_outs()
        full = format_vectors(VF2, ports, outs).splitlines()
        short = "\n".join(full[:3] + full[-2:]) + "\n"
        self.check_error(short, 4, "the header lists 2 port lines, the design has 6")
        header_only = "\n".join(full[:3]) + "\n"
        self.check_error(header_only, 4, "the header lists 2 port lines, the design has 6")

    def test_error_carries_name(self) -> None:
        ports, outs = ports_outs()
        with self.assertRaises(VectorError) as cm:
            parse_vectors("0 10\n", ports, outs, name="my.vec")
        self.assertEqual(
            str(cm.exception), "my.vec:1: expected 3 input bits of 0 and 1, found `10`"
        )
        with self.assertRaises(VectorError) as cm:
            parse_vectors("0 10\n", ports, outs)
        self.assertTrue(str(cm.exception).startswith("<vectors>:1: "))

    def test_no_data_input(self) -> None:
        ports = (Signal("clk", 1, "clock"),)
        self.assertEqual(parse_vectors("0 -\n", ports).rows, ((),))
        with self.assertRaises(VectorError) as cm:
            parse_vectors("0 1\n", ports)
        self.assertEqual(
            cm.exception.message, "expected `-`: the design has no non-clock input bit"
        )
        self.assertEqual(format_vectors(VectorFile(((),)), ports).splitlines()[-1], "0 -")

    def test_wide_ports(self) -> None:
        ports = (Signal("a", 3, "input"), Signal("b", 2, "input"))
        vf = VectorFile(((5, 2), (0, 3)))
        text = format_vectors(vf, ports)
        self.assertIn("0 10110", text)
        self.assertEqual(parse_vectors(text, ports), vf)

    def test_random_rows_match_random_vectors(self) -> None:
        ports, _ = ports_outs()
        rows = random_rows(ports, 7)
        self.assertEqual(tuple(next(rows) for _ in range(9)), random_vectors(ports, 9, 7).rows)

    def test_headerless_file_is_accepted(self) -> None:
        # S1 (spec SV-2): the header is optional, a hand-written file needs only vector lines.
        ports, outs = ports_outs()
        self.assertEqual(parse_vectors("0 100\n1 011\n", ports, outs).rows, ((1, 0, 0), (0, 1, 1)))

    def test_random_vectors(self) -> None:
        ports, _ = ports_outs()
        a = random_vectors(ports, 4, 7)
        self.assertEqual(a, random_vectors(ports, 4, 7))
        self.assertEqual([len(r) for r in a.rows], [3] * 4)
        self.assertTrue(all(v in (0, 1) for r in a.rows for v in r))
        self.assertNotEqual(random_vectors(ports, 64, 1), random_vectors(ports, 64, 2))
        wide = random_vectors((Signal("w", 70, "input"),), 8, 1)
        self.assertTrue(all(r[0] < 2**70 for r in wide.rows))


class RunTest(unittest.TestCase):
    def test_run_vectors(self) -> None:
        s = traffic_session()
        rec = s.run_vectors(VectorFile(TRACE_IN))
        self.assertEqual(s.recording, rec)
        hand = traffic_session()
        hand.start_recording()
        for rst, car_ns, car_ew in TRACE_IN:
            hand.set_many({"rst": rst, "car_ns": car_ns, "car_ew": car_ew})
            hand.step()
        self.assertEqual(rec, hand.recording)
        r = traffic_session()
        rec2 = r.run_random(16, 3)
        self.assertEqual(len(rec2.samples), 17)
        self.assertEqual(r.cycle, 16)

    def test_run_vectors_checks_width(self) -> None:
        s = traffic_session()
        with self.assertRaises(ValueError):
            s.run_vectors(VectorFile(((1, 0, 0), (1, 0))))
        self.assertEqual(s.cycle, 0)


if __name__ == "__main__":
    unittest.main()
