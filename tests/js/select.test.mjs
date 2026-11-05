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
