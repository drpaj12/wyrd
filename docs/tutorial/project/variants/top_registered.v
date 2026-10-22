// The counter value plus a step you choose, registered: total = count + step one cycle later.
module top (input clk, input rst, input [3:0] step, output reg [4:0] total);
  wire [3:0] count;
  wire [4:0] sum;
  counter u_counter (.clk(clk), .rst(rst), .count(count));
  add4    u_add     (.a(count), .b(step), .sum(sum));
  always @(posedge clk) total <= sum;
endmodule
