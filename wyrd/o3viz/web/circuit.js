// Hutton / Kundarewich circuit measures on the lut plane (pure: no DOM, no three.js).
// Definitions: Kundarewich, "Synthetic Circuit Generation Using Clustering and Iteration", MASc, U. Toronto,
// 2002, sections 2.1 and 3.1-3.3. They match wyrd/o3viz/hutton.py; tests/js/circuit.test.mjs and
// tests/test_o3viz_hutton.py use the same hand-computed circuit.

const bump = (h, at, by = 1) => { while (h.length <= at) h.push(0); h[at] += by; };

// Edge length: delay_level(sink) - delay_level(source) for an edge into a LUT; 0 for a DFF edge (into a
// flip-flop) and for an edge into a hard block. `kind` is the sink's driver kind from edges/lut.json.
export const edgeLength = (kind, la, lb) => (kind === "names" ? lb - la : 0);

// d: the lut plane (columns), idx: indices of the objects in the set, edges: [[a, b, kind]], ids of the plane.
// Objects without a delay level (logic_level null) are not part of the circuit measure.
export function characterize(d, idx, edges) {
  const lv = d.metrics.logic_level, fin = d.metrics.fanin, fo = d.metrics.fanout, po = d.metrics.is_po, cf = d.metrics.fanout_comb;
  const at = new Map(idx.map((i) => [d.ids[i], i]));
  const shape = { node: [0], input: [0], output: [0], po: [0] };
  const fanout = [0], edgeLen = [0];
  let dff = 0, block = 0, pis = 0, nodes = 0;
  for (const i of idx) {
    const l = lv[i];
    if (l === null || l === undefined) continue;
    nodes++;
    bump(shape.node, l);
    bump(fanout, cf?.[i] ?? 0);
    if (d.type[i] === "net" && d.kind[i] === "net") pis++;
    if ((fo[i] ?? 0) > 0) bump(shape.output, l);
    if (po?.[i] === 1) bump(shape.po, l);
    if (d.type[i] === "names") bump(shape.input, l, fin[i] ?? 0);
  }
  for (const [a, b, kind] of edges) {
    const ia = at.get(a), ib = at.get(b);
    if (ia === undefined || ib === undefined || lv[ia] == null || lv[ib] == null) continue;
    if (kind === "latch") dff++;
    else if (kind === "subckt") block++;
    else bump(edgeLen, edgeLength(kind, lv[ia], lv[ib]));
  }
  const dmax = Math.max(0, ...shape.node.keys());
  for (const h of Object.values(shape)) while (h.length <= dmax) h.push(0);
  return { nodes, dmax, pis, node_shape: shape.node, input_shape: shape.input, output_shape: shape.output,
    po_shape: shape.po, fanout, edge_length: edgeLen, dff_edges: dff, block_edges: block };
}

// Edges of Comb (sink is not a flip-flop) or Latched (sink is a flip-flop) from cluster i to cluster j.
// `of` is the cluster of each lut-plane object (by index), `at` maps id -> index.
export function cellEdges(edges, of, at, i, j, which) {
  return edges.filter(([a, b, kind]) => of[at.get(a)] === i && of[at.get(b)] === j && (kind === "latch") === (which === "latched"));
}

// Comb or Latched from the edge list, for a cluster assignment (the exporter writes the same matrices).
export function matrixOf(edges, of, at, k, which) {
  const m = Array.from({ length: k }, () => new Array(k).fill(0));
  for (const [a, b, kind] of edges) {
    if ((kind === "latch") !== (which === "latched")) continue;
    const i = of[at.get(a)], j = of[at.get(b)];
    if (i !== undefined && j !== undefined) m[i][j]++;
  }
  return m;
}

// heat colour 0..1 on a log scale of the count (0 stays background)
export const heat = (v, max) => (v <= 0 || max <= 0 ? 0 : Math.log1p(v) / Math.log1p(max));

// the shape arrays folded to at most n bars (the tail summed into the last bar)
export function fold(arr, n) {
  if (arr.length <= n) return arr.slice();
  return [...arr.slice(0, n - 1), arr.slice(n - 1).reduce((t, v) => t + v, 0)];
}
