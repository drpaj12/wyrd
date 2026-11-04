import test from "node:test";
import assert from "node:assert/strict";
import { spearman, mutualInfo, ranks } from "../../wyrd/o3viz/web/stats.js";

const close = (a, b, e = 1e-9) => assert.ok(Math.abs(a - b) < e, `${a} vs ${b}`);

test("ranks average ties", () => assert.deepEqual(ranks([10, 20, 20, 5]), [2, 3.5, 3.5, 1]));
test("spearman monotone and anti", () => {
  close(spearman([1, 2, 3, 4], [1, 4, 9, 16]), 1);
  close(spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1);
});
test("spearman skips missing and handles constants", () => {
  close(spearman([1, null, 2, 3, 4], [2, 9, 4, 6, 8]), 1);
  assert.equal(spearman([1, 1, 1, 1], [1, 2, 3, 4]), null);
  assert.equal(spearman([1, 2], [1, 2]), null);
});
test("mutual information", () => {
  const x = Array.from({ length: 80 }, (_, i) => i);
  assert.ok(mutualInfo(x, x) > 2.5);
  const flat = x.map(() => 1);
  close(mutualInfo(x, flat), 0);
  const nonmono = x.map((v) => (v - 40) ** 2);
  assert.ok(mutualInfo(x, nonmono) > 1);
  assert.ok(Math.abs(spearman(x, nonmono)) < 0.2);
});
