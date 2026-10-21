// Single-port RAM, 32 words x 16 bits, registered read. Part of the wyrd samples (MIT).
module buf_ram (
    input  wire        clk,
    input  wire        we,
    input  wire [4:0]  addr,
    input  wire [15:0] din,
    output reg  [15:0] dout
);
    reg [15:0] mem [0:31];

    always @(posedge clk) begin
        if (we)
            mem[addr] <= din;
        dout <= mem[addr];
    end
endmodule
