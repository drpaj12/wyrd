module t(input clk, input a, input b, output y);
  reg q;
  always @(posedge clk) q <= a & b;
  assign y = q ^ a;
endmodule
