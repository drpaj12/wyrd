import test from "node:test";
import assert from "node:assert/strict";
import { khopEdges, nodeEdges, propagate, isGraph, KEYS } from "../../wyrd/o3viz/web/graphview.js";

const E = [["a", "b", "data", "", 0, []], ["b", "c", "data", "", 0, []], ["c", "d", "control", "", 1, []], ["x", "y", "data", "", 0, []]];

test("k-hop keeps the edges within k hops, both directions", () => {
  assert.deepEqual([...khopEdges(E, ["b"], 1)].sort(), [0, 1]);
  assert.deepEqual([...khopEdges(E, ["b"], 2)].sort(), [0, 1, 2]);
  assert.deepEqual([...khopEdges(E, ["d"], 1)], [2]);
});
test("no seeds: no edges", () => {
  assert.equal(khopEdges(E, [], 3).size, 0);
});
test("edges of a node with direction", () => {
  assert.deepEqual(nodeEdges(E, "b"), [{ dir: "in", other: "a", idx: 0 }, { dir: "out", other: "c", idx: 1 }]);
});
test("graph plane names and keys", () => {
  assert.ok(isGraph("stg") && isGraph("ddg") && !isGraph("hdl"));
  assert.equal(KEYS.c, "cfg");
});
test("propagate fills unmeasured planes from linked objects", () => {
  const ids = { lut: ["l1", "l2"], hdl: ["h1", "h2"], cfg: ["c1"] };
  const cols = { lut: [4, 8], hdl: [null, null], cfg: [null] };
  const links = { h1: ["l1", "l2"], h2: [], c1: ["h1"], l1: ["h1"], l2: ["h1"] };
  const at = (id) => { for (const p of Object.keys(ids)) { const i = ids[p].indexOf(id); if (i >= 0) return [p, i]; } return [null, -1]; };
  const nbrs = (id) => links[id] ?? [];
  const mean = propagate(cols, ids, nbrs, at, "mean");
  assert.deepEqual(mean.hdl, [6, null]);
  assert.deepEqual(mean.cfg, [6]);
  assert.deepEqual(propagate(cols, ids, nbrs, at, "max").hdl, [8, null]);
  assert.deepEqual(mean.lut, [4, 8]);
});
