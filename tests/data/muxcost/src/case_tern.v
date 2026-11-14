module case_tern(input clk, input [1:0] sel, input [3:0] a, b, c, input en,
                 output reg [3:0] y, output reg [3:0] z);
  reg [3:0] ny;
  always @(*) begin
    case (sel)
      2'd0: ny = a;
      2'd1: ny = b;
      2'd2: ny = c;
      default: ny = 4'd0;
    endcase
  end
  always @(posedge clk) begin
    y <= ny;
    z <= en ? a : b;
  end
endmodule
