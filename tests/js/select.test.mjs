import test from "node:test";
import assert from "node:assert/strict";
import { parseSpan, innermost, hdlCovering, reachDown, linesOf, cone } from "../../wyrd/o3viz/web/select.js";

const hdl = { src: [[["t.v", "1.1-5.10"]], [["t.v", "3.1-3.30"]], [["t.v", "3.10-3.20"]], [["t.v", "4.1-4.20"]], [["u.v", "3.1-3.5"]], []] };

test("parseSpan", () => {
  assert.deepEqual(parseSpan("73.1-292.10"), { l0: 73, c0: 1, l1: 292, c1: 10 });
  assert.equal(parseSpan("x"), null);
});

test("line -> innermost covering constructs, per file", () => {
  assert.deepEqual([...hdlCovering(hdl, "t.v", 3, 3)], [2]);
  assert.deepEqual([...hdlCovering(hdl, "t.v", 4, 4)], [3]);
  assert.deepEqual([...hdlCovering(hdl, "t.v", 2, 2)], [0]);
  assert.deepEqual([...hdlCovering(hdl, "u.v", 3, 3)], [4]);
  assert.deepEqual([...hdlCovering(hdl, "t.v", 9, 9)], []);
});

test("line -> all enclosing constructs when asked, and a dragged range is the union", () => {
  assert.deepEqual([...hdlCovering(hdl, "t.v", 3, 3, true)].sort(), [0, 1, 2]);
  assert.deepEqual([...hdlCovering(hdl, "t.v", 3, 4)].sort(), [2, 3]);
  assert.deepEqual([...hdlCovering(hdl, "t.v", 4, 3)].sort(), [2, 3]);
});

test("innermost keeps equal spans", () => {
  const sp = parseSpan("1.1-2.2");
  assert.equal(innermost([{ span: sp }, { span: { ...sp } }]).length, 2);
});

test("reachDown follows links plane by plane without sibling atoms", () => {
  const order = ["hdl", "lut", "clb", "placed"];
  const planeOf = (id) => id.split(":")[0];
  const link = (pairs) => { const m = new Map(); for (const [a, b] of pairs) (m.get(a) ?? m.set(a, []).get(a)).push(b); return m; };
  const down = link([["hdl:a", "lut:1"], ["hdl:a", "lut:2"], ["lut:1", "clb:A"], ["lut:2", "clb:A"], ["lut:1", "placed:1"], ["lut:2", "placed:2"],
    ["clb:A", "placed:1"], ["clb:A", "placed:2"], ["clb:A", "placed:ff"]]);
  const r = reachDown(["hdl:a"], order, planeOf, down);
  assert.deepEqual([...r.lut].sort(), ["lut:1", "lut:2"]);
  assert.deepEqual([...r.clb], ["clb:A"]);
  assert.deepEqual([...r.placed].sort(), ["placed:1", "placed:2"]);
  assert.equal(reachDown(["hdl:zz"], order, planeOf, down).lut.size, 0);
});

test("linesOf merges spans per file", () => {
  const m = linesOf([["t.v", "2.1-4.3"], ["t.v", "4.1-5.1"], ["u.v", "1.1-1.4"], ["t.v", "bad"]]);
  assert.deepEqual([...m.get("t.v")], [2, 3, 4, 5]);
  assert.deepEqual([...m.get("u.v")], [1]);
});

// a -> b -> c -> d, plus ff -> c and c -> ff2; ff, ff2 are not LUTs
const edges = [["a", "b"], ["b", "c"], ["c", "d"], ["ff", "c"], ["c", "ff2"], ["ff2", "e"]];
const through = (n) => ["a", "b", "c", "d"].includes(n);

test("cone: fan-in stops at a flip-flop, fan-out stops at a flip-flop", () => {
  const i = cone(edges, ["c"], "in", 9, through);
  assert.deepEqual([...i.nodes.keys()].sort(), ["a", "b", "c", "ff"]);
  const o = cone(edges, ["c"], "out", 9, through);
  assert.deepEqual([...o.nodes.keys()].sort(), ["c", "d", "ff2"]);
  assert.ok(!o.nodes.has("e"));
});

test("cone: depth limit and both directions", () => {
  assert.deepEqual([...cone(edges, ["c"], "in", 1, through).nodes.keys()].sort(), ["b", "c", "ff"]);
  const b = cone(edges, ["c"], "both", 1, through);
  assert.deepEqual([...b.nodes.keys()].sort(), ["b", "c", "d", "ff", "ff2"]);
  assert.equal(b.nodes.get("b"), "in");
  assert.equal(b.nodes.get("d"), "out");
  assert.ok(b.edges.some(([x, y]) => x === "b" && y === "c"));
});

import { chainFor, tiers, parseBus, busHue, bitLight, declLine } from "../../wyrd/o3viz/web/select.js";

// module m > always a > case c > items i1 (with inner stmt s1), i2, i3
const H = {
  ids: ["m", "a", "c", "i1", "s1", "i2", "i3"],
  type: ["block", "block", "stmt", "branch", "stmt", "branch", "branch"],
  parent: [null, "m", "a", "c", "i1", "c", "c"],
};

test("chainFor finds the case and the item of an inner statement", () => {
  const ch = chainFor(H, "s1");
  assert.equal(ch.chain, "c");
  assert.equal(ch.item, "i1");
  assert.deepEqual(ch.items, ["i1", "i2", "i3"]);
  assert.equal(chainFor(H, "a"), null);
});

test("three tiers on a three-item case: own, shared, context", () => {
  const ch = chainFor(H, "i1");
  const links = {
    mux1: ["m", "a", "c", "i1"], // only item 1
    sel: ["m", "a", "c", "i1", "i2", "i3"], // the case select
    mux2: ["m", "a", "c", "i2"], // only item 2
    ctl: ["m", "a", "c"], // case logic, no item
    other: ["m"],
  };
  const t = tiers(ch, H.ids, (id) => links[id] ?? [], [["cell", Object.keys(links)]], () => []);
  assert.equal(t.get("mux1"), "A");
  assert.equal(t.get("sel"), "B");
  assert.equal(t.get("ctl"), "B");
  assert.equal(t.get("mux2"), "C");
  assert.equal(t.has("other"), false);
  assert.equal(t.get("i1"), "A");
  assert.equal(t.get("s1"), "A");
  assert.equal(t.get("c"), "B");
  assert.equal(t.get("i3"), "C");
});

test("a plane without hdl links takes the best tier of what links above it", () => {
  const ch = chainFor(H, "i1");
  const up = { clb1: ["lutA", "lutC"], clb2: ["lutC"] };
  const hl = { lutA: ["c", "i1"], lutC: ["c", "i2"] };
  const t = tiers(ch, H.ids, (id) => hl[id] ?? [], [["lut", ["lutA", "lutC"]], ["clb", ["clb1", "clb2"]]], (id) => up[id] ?? []);
  assert.equal(t.get("clb1"), "A");
  assert.equal(t.get("clb2"), "C");
});

test("bus names, colours and declaration lines", () => {
  assert.deepEqual(parseBus("return_val[24]"), { base: "return_val", bit: 24 });
  assert.deepEqual(parseBus("clk"), { base: "clk", bit: null });
  assert.notEqual(busHue(0), busHue(1));
  assert.ok(bitLight(0, 32) < bitLight(31, 32));
  assert.equal(bitLight(null, 32), 0.55);
  assert.equal(declLine(["x", "reg [31:0] var0;", "wire a;"], "var0"), 2);
  assert.equal(declLine(["x"], "var0"), 0);
});

import { mixOf, meanMix, mixRGB, mixText } from "../../wyrd/o3viz/web/select.js";

test("graded ownership: shares of the cells, mean over LUTs, colour mix", () => {
  const m = mixOf(["A", "B", "B", undefined]);
  assert.deepEqual(m, { A: 0.25, B: 0.5, C: 0, n: 4 });
  assert.equal(mixOf([]), null);
  assert.deepEqual(meanMix([m, null, mixOf(["A", "A"])]), { A: 0.625, B: 0.25, C: 0, n: 2 });
  const cols = { A: [1, 0.5, 0], B: [0, 0.8, 0.7], C: [0.6, 0.5, 1] }, bg = [0.1, 0.1, 0.1];
  assert.deepEqual(mixRGB({ A: 0, B: 0, C: 0 }, cols, bg), bg);
  const pureA = mixRGB({ A: 1, B: 0, C: 0 }, cols, bg);
  assert.deepEqual(pureA, [1, 0.5, 0]);
  const half = mixRGB({ A: 0.5, B: 0, C: 0 }, cols, bg);
  assert.ok(half[0] < pureA[0] && half[0] > bg[0]);
  assert.equal(mixText(m), "A 25%  B 50%  C 0%  (of 4 cells)");
});
