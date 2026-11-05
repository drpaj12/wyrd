// Pure helpers for the graph planes (STG, CFG, DDG) of the o3viz viewer: no DOM, no three.js.
export const GRAPHS = ["stg", "cfg", "ddg"];
export const KEYS = { s: "stg", c: "cfg", d: "ddg" };
export const isGraph = (p) => GRAPHS.includes(p);

// Edge rows are [from, to, kind, label, seq, src]. Indices of the edges within k hops of `seeds`
// (ignoring direction), or null when `seeds` is empty and `all` is false (nothing selected: nothing drawn).
export function khopEdges(edges, seeds, k) {
  const adj = new Map();
  edges.forEach(([a, b], i) => {
    (adj.get(a) ?? adj.set(a, []).get(a)).push([b, i]);
    (adj.get(b) ?? adj.set(b, []).get(b)).push([a, i]);
  });
  const seen = new Set(seeds), out = new Set();
  let frontier = [...seeds];
  for (let h = 0; h < k && frontier.length; h++) {
    const next = [];
    for (const n of frontier) {
      for (const [m, i] of adj.get(n) ?? []) {
        out.add(i);
        if (!seen.has(m)) { seen.add(m); next.push(m); }
      }
    }
    frontier = next;
  }
  return out;
}

// edges into and out of `id`: [{dir: "in"|"out", other, idx}]
export function nodeEdges(edges, id) {
  const out = [];
  edges.forEach(([a, b], i) => {
    if (b === id) out.push({ dir: "in", other: a, idx: i });
    if (a === id) out.push({ dir: "out", other: b, idx: i });
  });
  return out;
}

// edge colour class: ddg data / control, cfg control / seq, stg transition
export const edgeClass = (kind) => (kind === "control" ? "control" : kind === "transition" ? "transition" : kind === "seq" ? "seq" : "data");

// Fill a metric on planes that have no value of their own: a plane object takes op (min, max, mean) over the
// values of the objects it is linked to (up and down, direct links) that already have one; repeated `rounds`
// times so the value travels from the measured planes (lut, placed, ddg) through cell and hdl to stg and cfg.
// cols: plane -> array of values (null = none); ids: plane -> ids; nbrs(id) -> linked ids; at(id) -> [plane, i].
export function propagate(cols, ids, nbrs, at, op, rounds = 3) {
  const AGG = { min: (v) => Math.min(...v), max: (v) => Math.max(...v), mean: (v) => v.reduce((a, b) => a + b, 0) / v.length };
  const own = new Set(Object.keys(cols).filter((p) => cols[p].some((v) => v !== null)));
  const out = Object.fromEntries(Object.keys(cols).map((p) => [p, cols[p].slice()]));
  for (let r = 0; r < rounds; r++) {
    const snap = Object.fromEntries(Object.keys(out).map((p) => [p, out[p].slice()]));
    for (const p of Object.keys(out)) {
      if (own.has(p)) continue;
      ids[p].forEach((id, i) => {
        if (snap[p][i] !== null) return;
        const vals = [];
        for (const t of nbrs(id)) { const [q, j] = at(t); const v = snap[q]?.[j]; if (v !== null && v !== undefined) vals.push(v); }
        if (vals.length) out[p][i] = AGG[op](vals);
      });
    }
  }
  return out;
}
