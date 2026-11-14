module index(input clk, input [7:0] v, input [2:0] idx, output reg o);
  always @(posedge clk) o <= v[idx];
endmodule
