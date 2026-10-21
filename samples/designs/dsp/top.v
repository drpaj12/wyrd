// Multiply-accumulate feeding a small RAM, with registered outputs. Part of the wyrd samples (MIT).
module top (
    input  wire               clk,
    input  wire               rst,
    input  wire               en,
    input  wire               we,
    input  wire [4:0]         addr,
    input  wire signed [7:0]  a,
    input  wire signed [7:0]  b,
    output reg  signed [19:0] acc_q,
    output reg  [15:0]        ram_q
);
    wire signed [19:0] acc;
    wire [15:0]        dout;

    mac u_mac (.clk(clk), .rst(rst), .en(en), .a(a), .b(b), .acc(acc));
    buf_ram u_ram (.clk(clk), .we(we), .addr(addr), .din(acc[15:0]), .dout(dout));

    always @(posedge clk) begin
        if (rst) begin
            acc_q <= 20'sd0;
            ram_q <= 16'd0;
        end else begin
            acc_q <= acc;
            ram_q <= dout;
        end
    end
endmodule
