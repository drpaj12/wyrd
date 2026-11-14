module chain(input clk, input s0, s1, s2, input [3:0] a, b, output reg [3:0] y);
  reg [3:0] ny;
  always @(*) begin
    if (s0) ny = a;
    else if (s1) ny = b;
    else if (s2) ny = a;
    else ny = 4'd9;
  end
  always @(posedge clk) y <= ny;
endmodule
