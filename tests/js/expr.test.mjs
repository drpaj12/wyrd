import test from "node:test";
import assert from "node:assert/strict";
import { parse, evaluate, varsOf } from "../../wyrd/o3viz/web/expr.js";

const run = (text, vars = {}) => evaluate(parse(text), (n) => (n in vars ? vars[n] : null));

test("arithmetic and precedence", () => {
  assert.equal(run("1 + 2 * 3"), 7);
  assert.equal(run("(1 + 2) * 3"), 9);
  assert.equal(run("2 ^ 3 ^ 2"), 512);
  assert.equal(run("-2 ^ 2"), -4);
  assert.equal(run("10 % 4"), 2);
});
test("variables, functions, comparisons", () => {
  assert.equal(run("fanout * logic_level", { fanout: 3, logic_level: 2 }), 6);
  assert.equal(run("max(a, abs(b))", { a: 1, b: -5 }), 5);
  assert.equal(run("if(a > 0, 1, 2)", { a: 3 }), 1);
  assert.equal(run("clamp(a, 0, 1)", { a: 9 }), 1);
});
test("null propagates and domain errors give null", () => {
  assert.equal(run("a + 1", {}), null);
  assert.equal(run("1 / 0"), null);
  assert.equal(run("sqrt(-1)"), null);
  assert.equal(run("log(0)"), null);
});
test("vars collected", () => {
  assert.deepEqual([...varsOf(parse("a + max(b, c) * a"))].sort(), ["a", "b", "c"]);
});
test("rejects unsafe and malformed input", () => {
  for (const bad of ["a.b", "constructor", "process.exit()", "a = 1", "1 +", "foo(1)", "max(1)", "(1", "1 2", "a[0]", "'x'"]) {
    let threw = false;
    try { run(bad, { a: 1, constructor: 1 }); } catch { threw = true; }
    if (bad === "constructor") assert.equal(run(bad, { constructor: 7 }), 7);
    else assert.ok(threw, bad);
  }
});
