import test from "node:test";
import assert from "node:assert/strict";
import { characterize, edgeLength, cellEdges, matrixOf, heat, fold } from "../../wyrd/o3viz/web/circuit.js";
import { cellAt } from "../../wyrd/o3viz/web/circuitdraw.js";

// tests/data/o3viz/hutton/s.blif as a lut plane (the same hand-computed values as tests/test_o3viz_hutton.py)
const names = ["a", "b", "c", "n1", "n2", "q1", "n3", "n4", "q2", "z"];
const type = ["net", "net", "net", "names", "names", "latch", "names", "names", "latch", "names"];
const lv = [0, 0, 0, 1, 2, 0, 1, 2, 0, 1];
const fin = [null, null, null, 3, 2, 1, 1, 2, 1, 2];
const fo = [1, 1, 1, 1, 1, 3, 1, 1, 2, 0];
const cf = [1, 1, 1, 1, 0, 3, 1, 0, 2, 0];
const d = { ids: names, type, kind: type.map((t) => (t === "net" ? "net" : "lut")),
  metrics: { logic_level: lv, fanin: fin, fanout: fo, fanout_comb: cf, is_po: names.map((n) => (n === "z" ? 1 : null)) } };
const edges = [["a", "n1", "names"], ["b", "n1", "names"], ["q2", "n1", "names"], ["n1", "n2", "names"], ["c", "n2", "names"],
  ["n2", "q1", "latch"], ["q1", "n3", "names"], ["q1", "n4", "names"], ["n3", "n4", "names"], ["n4", "q2", "latch"],
  ["q2", "z", "names"], ["q1", "z", "names"]];
const all = names.map((_, i) => i);

test("whole circuit shapes", () => {
  const c = characterize(d, all, edges);
  assert.equal(c.nodes, 10); assert.equal(c.dmax, 2); assert.equal(c.pis, 3);
  assert.deepEqual(c.node_shape, [5, 3, 2]);
  assert.deepEqual(c.input_shape, [0, 6, 4]);
  assert.deepEqual(c.output_shape, [5, 2, 2]);
  assert.deepEqual(c.po_shape, [0, 1, 0]);
  assert.deepEqual(c.fanout, [3, 5, 1, 1]);
  assert.deepEqual(c.edge_length, [0, 8, 2]);
  assert.equal(c.dff_edges, 2);
});

test("a selection counts only its own objects and the edges between them", () => {
  const sel = ["n1", "n2", "q2"].map((n) => names.indexOf(n));
  const c = characterize(d, sel, edges);
  assert.deepEqual(c.node_shape, [1, 1, 1]);
  assert.deepEqual(c.edge_length, [0, 2]);
  assert.equal(c.dff_edges, 0);
});

test("edge length: DFF and block edges are 0", () => {
  assert.equal(edgeLength("names", 0, 2), 2);
  assert.equal(edgeLength("latch", 2, 0), 0);
  assert.equal(edgeLength("subckt", 1, 0), 0);
});

test("Comb and Latched matrices, and the edges of one cell", () => {
  const of = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1];            // clusters: {a b c n1 n2}, {q1 n3 n4 q2 z}
  const at = new Map(names.map((n, i) => [n, i]));
  assert.deepEqual(matrixOf(edges, of, at, 2, "comb"), [[4, 0], [1, 5]]);
  assert.deepEqual(matrixOf(edges, of, at, 2, "latched"), [[0, 1], [0, 1]]);
  assert.deepEqual(cellEdges(edges, of, at, 1, 0, "comb"), [["q2", "n1", "names"]]);
  assert.deepEqual(cellEdges(edges, of, at, 0, 1, "latched"), [["n2", "q1", "latch"]]);
});

test("heat, fold, cell hit test", () => {
  assert.equal(heat(0, 10), 0); assert.equal(heat(10, 10), 1);
  assert.deepEqual(fold([1, 2, 3, 4, 5], 3), [1, 2, 12]);
  assert.deepEqual(cellAt(0, 0, 4, 100), [0, 0]); assert.deepEqual(cellAt(99, 51, 4, 100), [2, 3]);
});
