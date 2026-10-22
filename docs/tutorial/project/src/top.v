// The counter value plus a step you choose: total = count + step.
module top (input clk, input rst, input [3:0] step, output [4:0] total);
  wire [3:0] count;
  counter u_counter (.clk(clk), .rst(rst), .count(count));
  add4    u_add      (.a(count), .b(step), .sum(total));
endmodule
