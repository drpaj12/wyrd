"""Bifrost power estimation: VCD activity, BLIF netlist, report parsing."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from wyrd.bifrost.power import actfile, blifnet, crosscheck, sim, sta
from wyrd.bifrost.power.flow import asic_by_line, fpga_by_line, read_prov_csv
from wyrd.bifrost.power.vcdact import NetAct, read_activity, sample_rising

VCD = """$timescale 1ns $end
$scope module tb $end
$var wire 1 ! clk $end
$var wire 1 " q $end
$var wire 2 # v [1:0] $end
$upscope $end
$enddefinitions $end
#0
0!
0"
b00 #
#5
1!
#10
0!
1"
b01 #
#15
1!
#20
0!
0"
b11 #
#25
1!
#30
0!
"""

BLIF = """.model top
.inputs clk a[0] a[1]
.outputs y[0] q
.names a[0] a[1] n1
11 1
.names n1 y[0]
0 1
.names vcc
1
.latch n1 q re clk 2
.end
"""

POWER = """----------------------------------- Summary ------------------------------------
Critical Path: 2.5e-09

----------------------------------- Warnings -----------------------------------
No dynamic power defined for BLIF model: .subckt adder

------------------------------- Power Breakdown --------------------------------
Component                       Power (W)   %-Total     %-Dynamic   Method

Total                           0.004       1           0.75
 Routing                        0.001       0.25        0.7
 PB Types                       0.002       0.5         0.8
 Clock                          0.0005      0.125       1

---------------------------- Power Breakdown by PB -----------------------------
"""


class VcdActivity(unittest.TestCase):
    def test_scalar_and_vector_bits(self) -> None:
        acts = read_activity(VCD.splitlines(), "clk")
        self.assertEqual(acts["tb.clk"].toggles, 6)
        self.assertAlmostEqual(acts["tb.q"].activity, 2 / 3)  # 3 rising edges, 2 toggles
        self.assertAlmostEqual(acts["tb.v[0]"].activity, 1 / 3)
        self.assertAlmostEqual(acts["tb.v[1]"].activity, 1 / 3)
        self.assertAlmostEqual(acts["tb.q"].p1, 10 / 30)

    def test_missing_clock_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            read_activity(VCD.splitlines(), "nope")

    def test_sample_before_rising_edge(self) -> None:
        rows = sample_rising(VCD.splitlines(), "tb.clk", {"tb.v": 2, "tb.q": 1})
        self.assertEqual([r["tb.v"] for r in rows], [0, 1, 3])
        self.assertEqual([r["tb.q"] for r in rows], [0, 1, 0])


class BlifNetlist(unittest.TestCase):
    def test_parse_and_write(self) -> None:
        b = blifnet.parse_blif(BLIF)
        self.assertEqual((len(b.names), len(b.latches)), (3, 1))
        text = blifnet.verilog_netlist(b, "top_nl")
        self.assertIn("assign \\n1  = ((\\a[0]  & \\a[1] ));", text)
        self.assertIn("assign \\y[0]  = ((~\\n1 ));", text)
        self.assertIn("always @(posedge \\clk ) \\q  <= \\n1 ;", text)
        self.assertIn("output reg \\q ", text)

    def test_wrapper_groups_bits(self) -> None:
        b = blifnet.parse_blif(BLIF)
        w = blifnet.wrapper(b, "top_nl", "top")
        self.assertIn("input [1:0] a", w)
        self.assertIn("output q", w)
        self.assertEqual(blifnet.port_groups(["a[0]", "a[3]", "c"]), {"a": 4, "c": 1})

    def test_names_file(self) -> None:
        text = (
            "# odin3-names 2\nO\tm\tnet\th1\tm/$n1@/x/f.v:7\tm\t/x/f.v\t7\tr1\tlut\n"
            "N\tm\tnet\ta\tr2\tstmt\n"
        )
        prov = blifnet.parse_names(text)
        self.assertEqual(prov["h1"].line, 7)
        self.assertEqual(len(prov), 1)

    def test_nets_in_file_order(self) -> None:
        b = blifnet.parse_blif(BLIF)
        self.assertEqual(b.nets()[:3], ["clk", "a[0]", "a[1]"])


class ActFiles(unittest.TestCase):
    def test_default_activity_is_mean_of_matched(self) -> None:
        found = {"a": NetAct(0.5, 0.2, 2, 10), "b": NetAct(0.1, 0.4, 4, 10)}
        act, s = actfile.build_act(["a", "b", "c", "clk"], found, skip=["clk"])
        self.assertEqual((s.nets, s.matched), (3, 2))
        self.assertAlmostEqual(act["c"][1], 0.3)
        self.assertAlmostEqual(s.matched_fraction, 2 / 3)

    def test_write_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.act"
            actfile.write_act(p, {"n": (0.25, 0.5)})
            self.assertEqual(actfile.read_act(p), {"n": (0.25, 0.5)})

    def test_parse_vpr_power(self) -> None:
        p = actfile.parse_power(POWER)
        self.assertAlmostEqual(p.total_w, 0.004)
        self.assertAlmostEqual(p.dynamic_w, 0.003)
        self.assertAlmostEqual(p.static_w, 0.001)
        self.assertAlmostEqual(p.clock_w, 0.0005)
        self.assertAlmostEqual(p.critical_path_s, 2.5e-9)
        self.assertEqual(len(p.warnings), 1)


class StaReport(unittest.TestCase):
    OUT = """Group  Internal Switching Leakage Total
Combinational  1e-4 2e-4 1e-9 3e-4  50%
Total          4.67e-04   1.03e-04   1.82e-09   5.70e-04 100.0%
ACT set=5 nets=8
INST_BEGIN
   Internal  Switching    Leakage      Total
      Power      Power      Power      Power
--------------------------------------------
  2.0e-07  3.0e-08  4.0e-12  2.3e-07 o3__c14
  1.0e-07  1.0e-08  1.0e-12  1.1e-07 clkbuf_1
"""

    def test_parse(self) -> None:
        p = sta.parse_sta_power(self.OUT)
        self.assertAlmostEqual(p.dynamic_w, 5.7e-4, places=6)
        self.assertEqual((p.activity_set, p.nets), (5, 8))
        self.assertEqual(set(p.instances), {"o3__c14", "clkbuf_1"})
        self.assertAlmostEqual(p.clock_w, 1.1e-7 + 1e-12, places=12)

    def test_driver_pins_use_the_raw_command(self) -> None:
        # `set_power_activity -pins` skips output pins silently (OpenSTA keeps input pins only),
        # which left every net but the input ports at the default activity (bug found 2026-11-06).
        tcl = sta.sta_script(Path("l.lib"), Path("d.odb"), "clk", 20.0, Path("t.txt"))
        self.assertIn("sta::set_power_pin_activity $drv $act $duty", tcl)
        self.assertNotIn("set_power_activity -pins", tcl)
        self.assertIn("set_power_activity -input_ports", tcl)

    def test_table_skips_clock_like_nets(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / "t.txt"
            n = sta.write_activity_table(
                t, {"a": NetAct(0.5, 0.2, 1, 1), "ck": NetAct(0.5, 2.0, 1, 1)}, set()
            )
            self.assertEqual(n, 1)


class Rollups(unittest.TestCase):
    def test_cross_check(self) -> None:
        a = {"x": NetAct(0.5, 0.2, 1, 1), "y": NetAct(0.5, 0.1, 1, 1), "z": NetAct(0, 0, 0, 1)}
        b = {"x": NetAct(0.5, 0.2, 1, 1), "y": NetAct(0.4, 0.3, 1, 1)}
        cc = crosscheck.compare(a, b)
        self.assertEqual((cc.compared, cc.identical, cc.only_a, cc.only_b), (2, 1, 1, 0))
        self.assertAlmostEqual(cc.activity_diff.max, 0.2)

    def test_asic_by_line_groups_physical(self) -> None:
        rows = asic_by_line(
            {"i1": (2.0, 0.1), "i2": (1.0, 0.1), "tap": (0.5, 0.0)},
            {"i1": ("d.v", 3), "i2": ("d.v", 3)},
        )
        self.assertEqual(rows[0]["line"], 3)
        self.assertAlmostEqual(rows[0]["asic_dyn_w"], 3.0)
        self.assertEqual(rows[1]["file"], "<physical>")

    def test_prov_csv(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "prov.csv"
            p.write_text(
                "inst,odin_name,master,src_chain,tie\ni1,$c1,m,x/d.v:10.1-10.5|d.v:20.1-20.3,\n"
            )
            self.assertEqual(read_prov_csv(p), {"i1": ("d.v", 10)})

    def test_fpga_by_line_totals(self) -> None:
        b = blifnet.parse_blif(BLIF)
        prov = {"n1": blifnet.Provenance("n1", "m/$n1", "/x/f.v", 7)}
        act = {"n1": (0.5, 0.5), "a[0]": (0.5, 0.5)}
        rows = fpga_by_line(b, act, prov, dynamic_w=1.0, clock_w=0.2)
        self.assertAlmostEqual(sum(r["fpga_dyn_w"] for r in rows), 0.8)
        self.assertEqual(rows[0]["file"], "f.v")


@unittest.skipIf(shutil.which("iverilog") is None, "iverilog not installed")
class IverilogRun(unittest.TestCase):
    TB = """`timescale 1ns/1ns
module tb; reg clk = 0; reg [1:0] c = 0; wire q;
  top dut(.clk(clk), .c(c), .q(q));
  always #5 clk = ~clk;
  initial begin #100; $display("PASS"); $finish; end
endmodule
"""
    DUT = (
        "module top(input clk, input [1:0] c, output reg q); initial q = 0;\n"
        "always @(posedge clk) q <= ~q; endmodule\n"
    )

    def test_activity_through_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            w = Path(d)
            (w / "tb.v").write_text(self.TB)
            (w / "dut.v").write_text(self.DUT)
            run = sim.TbRun([w / "dut.v", w / "tb.v"], "tb", "dut", "clk", "tb.dut.")
            res = sim.activity_run(run, w / "run")
            self.assertTrue(res.passed, res.log)
            self.assertEqual(res.cycles, 10)
            self.assertAlmostEqual(res.acts["q"].activity, 1.0, places=1)


if __name__ == "__main__":
    unittest.main()
