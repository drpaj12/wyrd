// Pure selection logic for the o3viz viewer (no DOM, no three.js): HDL line -> constructs -> objects on the
// planes below, spans -> source lines, and combinational cones in the LUT netlist.

// "73.1-292.10" -> {l0, c0, l1, c1}, or null
export function parseSpan(span) {
  const m = /^(\d+)\.(\d+)-(\d+)\.(\d+)$/.exec(span ?? "");
  return m ? { l0: +m[1], c0: +m[2], l1: +m[3], c1: +m[4] } : null;
}

const before = (l0, c0, l1, c1) => l0 < l1 || (l0 === l1 && c0 <= c1);
// a contains b (equal spans contain each other)
const contains = (a, b) => before(a.l0, a.c0, b.l0, b.c0) && before(b.l1, b.c1, a.l1, a.c1);
const same = (a, b) => a.l0 === b.l0 && a.c0 === b.c0 && a.l1 === b.l1 && a.c1 === b.c1;

// Keep the spans that contain no other span of the list strictly inside them. Equal spans all stay.
export function innermost(items) {
  return items.filter((a) => !items.some((b) => b !== a && !same(a.span, b.span) && contains(a.span, b.span)));
}

// Indices of the HDL constructs of `hdl` (a plane: src per object) whose span in `file` covers some line of
// l0..l1. By default only the innermost covering constructs of each line; `enclosing` keeps all of them.
export function hdlCovering(hdl, file, l0, l1, enclosing = false) {
  const spans = [];
  hdl.src.forEach((s, i) => {
    const sp = s[0] && s[0][0] === file ? parseSpan(s[0][1]) : null;
    if (sp) spans.push({ i, span: sp });
  });
  const out = new Set();
  for (let line = Math.min(l0, l1); line <= Math.max(l0, l1); line++) {
    const cov = spans.filter((s) => s.span.l0 <= line && line <= s.span.l1);
    for (const s of enclosing ? cov : innermost(cov)) out.add(s.i);
  }
  return out;
}

// From a set of start ids on `order`, the objects below on every later plane. Each plane is reached from the
// earliest plane that has direct links into it (so a cluster does not drag its sibling atoms in).
export function reachDown(startIds, order, planeOf, down) {
  const sel = Object.fromEntries(order.map((p) => [p, new Set()]));
  for (const id of startIds) sel[planeOf(id)]?.add(id);
  const first = Math.min(...[...startIds].map((id) => order.indexOf(planeOf(id))));
  for (let k = first + 1; k < order.length; k++) {
    for (let j = first; j < k; j++) {
      const got = new Set();
      for (const s of sel[order[j]]) for (const t of down.get(s) ?? []) if (planeOf(t) === order[k]) got.add(t);
      if (got.size) { sel[order[k]] = got; break; }
    }
  }
  return sel;
}

// spans [[file, "l.c-l.c"], ...] -> Map file -> Set of line numbers
export function linesOf(spans) {
  const out = new Map();
  for (const [file, span] of spans) {
    const sp = parseSpan(span);
    if (!sp) continue;
    const set = out.get(file) ?? out.set(file, new Set()).get(file);
    for (let l = sp.l0; l <= sp.l1; l++) set.add(l);
  }
  return out;
}

// Combinational cone of `seeds` in the LUT netlist. `edges` are [driver, sink]; a node is expanded only if
// `through(node)` is true (a LUT output), so the cone stops at flip-flops, I/O and hard blocks (they are
// included as its boundary). dir: "in" (fan-in), "out" (fan-out) or "both". At most `depth` hops.
export function cone(edges, seeds, dir, depth, through) {
  const outs = new Map(), ins = new Map();
  for (const [a, b] of edges) {
    (outs.get(a) ?? outs.set(a, []).get(a)).push(b);
    (ins.get(b) ?? ins.set(b, []).get(b)).push(a);
  }
  const nodes = new Map(), used = [];
  for (const s of seeds) nodes.set(s, "seed");
  for (const [d, adj, tag] of [["in", ins, "in"], ["out", outs, "out"]]) {
    if (dir !== d && dir !== "both") continue;
    const seen = new Set(seeds);
    let frontier = [...seeds];
    for (let h = 0; h < depth && frontier.length; h++) {
      const next = [];
      for (const n of frontier) {
        for (const t of adj.get(n) ?? []) {
          used.push(d === "in" ? [t, n, tag] : [n, t, tag]);
          if (seen.has(t)) continue;
          seen.add(t);
          if (!nodes.has(t)) nodes.set(t, tag);
          if (through(t)) next.push(t);
        }
      }
      frontier = next;
    }
  }
  return { nodes, edges: used };
}
