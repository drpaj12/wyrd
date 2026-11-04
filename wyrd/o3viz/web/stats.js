// Association measures for the discovery panel. Pairs with a missing value on either side are left out.

export function pairs(x, y) {
  const a = [], b = [];
  for (let i = 0; i < x.length; i++) if (x[i] !== null && y[i] !== null) { a.push(x[i]); b.push(y[i]); }
  return [a, b];
}

export function ranks(v) {
  const idx = v.map((_, i) => i).sort((i, j) => v[i] - v[j]);
  const r = new Array(v.length);
  for (let s = 0; s < idx.length;) {
    let e = s;
    while (e + 1 < idx.length && v[idx[e + 1]] === v[idx[s]]) e++;
    const avg = (s + e) / 2 + 1;
    for (let k = s; k <= e; k++) r[idx[k]] = avg;
    s = e + 1;
  }
  return r;
}

export function pearson(a, b) {
  const n = a.length;
  if (n < 3) return null;
  const ma = a.reduce((s, v) => s + v, 0) / n, mb = b.reduce((s, v) => s + v, 0) / n;
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < n; i++) { sab += (a[i] - ma) * (b[i] - mb); saa += (a[i] - ma) ** 2; sbb += (b[i] - mb) ** 2; }
  return saa === 0 || sbb === 0 ? null : sab / Math.sqrt(saa * sbb);
}

export function spearman(x, y) {
  const [a, b] = pairs(x, y);
  if (a.length < 3) return null;
  return pearson(ranks(a), ranks(b));
}

function bins(v, k) {
  const lo = Math.min(...v), hi = Math.max(...v);
  if (hi === lo) return v.map(() => 0);
  return v.map((x) => Math.min(k - 1, Math.floor(((x - lo) / (hi - lo)) * k)));
}

// Mutual information in bits, equal-width bins.
export function mutualInfo(x, y, k = 8) {
  const [a, b] = pairs(x, y);
  const n = a.length;
  if (n < 3) return null;
  const ba = bins(a, k), bb = bins(b, k);
  const joint = new Map(), pa = new Map(), pb = new Map();
  for (let i = 0; i < n; i++) {
    const key = ba[i] * k + bb[i];
    joint.set(key, (joint.get(key) ?? 0) + 1);
    pa.set(ba[i], (pa.get(ba[i]) ?? 0) + 1);
    pb.set(bb[i], (pb.get(bb[i]) ?? 0) + 1);
  }
  let mi = 0;
  for (const [key, c] of joint) {
    const i = Math.floor(key / k), j = key % k;
    mi += (c / n) * Math.log2((c * n) / (pa.get(i) * pb.get(j)));
  }
  return Math.max(0, mi);
}

export function matrix(cols, names, fn) {
  return names.map((a) => names.map((b) => (a === b ? null : fn(cols[a], cols[b]))));
}
