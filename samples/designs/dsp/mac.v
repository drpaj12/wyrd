// Multiply-accumulate: 8x8 signed multiply into a 20-bit accumulator.
// Synchronous reset, enable. Part of the wyrd samples (MIT).
module mac (
    input  wire               clk,
    input  wire               rst,
    input  wire               en,
    input  wire signed [7:0]  a,
    input  wire signed [7:0]  b,
    output reg  signed [19:0] acc
);
    wire signed [15:0] prod = a * b;

    always @(posedge clk) begin
        if (rst)
            acc <= 20'sd0;
        else if (en)
            acc <= acc + {{4{prod[15]}}, prod};
    end
endmodule
