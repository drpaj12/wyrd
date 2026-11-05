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

// ---- case / if-chain tiers ----
// hdl: the hdl plane (ids, type = construct level, kind, parent). A chain is a construct with two or more
// children of level "branch" (a case or an if/else chain); its items are those children.
export function chainFor(hdl, id) {
  const idx = new Map(hdl.ids.map((x, i) => [x, i]));
  const parentOf = (x) => hdl.parent?.[idx.get(x)] ?? null;
  const kids = new Map();
  hdl.ids.forEach((x, i) => {
    const p = hdl.parent?.[i];
    if (p && hdl.type[i] === "branch") (kids.get(p) ?? kids.set(p, []).get(p)).push(x);
  });
  for (let x = id, guard = 0; x && guard < 10000; x = parentOf(x), guard++) {
    const p = parentOf(x);
    if (p && hdl.type[idx.get(x)] === "branch" && (kids.get(p)?.length ?? 0) >= 2) {
      return { chain: p, item: x, items: kids.get(p), parentOf };
    }
  }
  return null;
}

const itemOf = (x, items, parentOf) => {
  for (let g = 0; x && g < 10000; x = parentOf(x), g++) if (items.has(x)) return x;
  return null;
};

// Tier per object id. A: reaches the clicked item and no sibling item. B: reaches the clicked item and also a
// sibling or the case selector, or is logic of the chain itself (select/mux). C: reaches only other items.
// hdlOf(id) -> hdl ids the object links to; planeOrder: [[plane, ids]] after hdl in stack order; upOf(id) -> ids
// linked above (used by planes without direct hdl links).
export function tiers(ch, hdlIds, hdlOf, planeOrder, upOf) {
  const items = new Set(ch.items), out = new Map();
  const under = (x, it) => itemOf(x, new Set([it]), ch.parentOf) === it;
  for (const x of hdlIds) {
    if (x === ch.chain) out.set(x, "B");
    else if (under(x, ch.item)) out.set(x, "A");
    else if (itemOf(x, items, ch.parentOf)) out.set(x, "C");
  }
  const rank = { A: 3, B: 2, C: 1 };
  for (const [, ids] of planeOrder) {
    for (const id of ids) {
      const hs = hdlOf(id);
      if (hs.length) {
        const touched = new Set(hs.map((h) => itemOf(h, items, ch.parentOf)).filter(Boolean));
        if (touched.has(ch.item)) out.set(id, touched.size === 1 ? "A" : "B");
        else if (touched.size) out.set(id, "C");
        else if (hs.includes(ch.chain)) out.set(id, "B");
      } else {
        let best = null;
        for (const u of upOf(id)) { const t = out.get(u); if (t && (!best || rank[t] > rank[best])) best = t; }
        if (best) out.set(id, best);
      }
    }
  }
  return out;
}

// ---- buses ----
// "return_val[24]" -> {base: "return_val", bit: 24}
export function parseBus(name) {
  const m = /^(.+)\[(\d+)\]$/.exec(name ?? "");
  return m ? { base: m[1], bit: +m[2] } : { base: name, bit: null };
}
// hue (degrees) of bus number k: golden-angle steps keep neighbours apart
export const busHue = (k) => (k * 137.508) % 360;
// lightness of a bit: the low bit is dark, the high bit light; a whole word (bit null) sits in the middle
export const bitLight = (bit, width) => (bit === null || bit === undefined || width <= 1 ? 0.55 : 0.32 + 0.4 * (bit / (width - 1)));

// First line of `lines` (array of text) that declares `name` (reg, wire, input, output), or 0
export function declLine(lines, name) {
  const rx = new RegExp(String.raw`\b(reg|wire|input|output|inout)\b[^;]*\b${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\b`);
  const i = lines.findIndex((l) => rx.test(l));
  return i < 0 ? 0 : i + 1;
}
