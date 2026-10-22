// A combinational 4-bit adder with a carry out.
module add4 (input [3:0] a, input [3:0] b, output [4:0] sum);
  assign sum = a + b;
endmodule
