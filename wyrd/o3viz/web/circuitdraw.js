// Small drawing helpers for the circuit panel: SVG bar charts and canvas heat maps (no three.js).
import { heat, fold } from "./circuit.js";

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// bars: values per x index (index 0 first); xoff shifts the labels (edge length starts at 1 in the plot)
export function barChart(title, values, { w = 150, h = 54, max = 24, tailLabel = true } = {}) {
  const v = fold(values, max), top = Math.max(1, ...v), bw = w / v.length;
  const rects = v.map((n, i) => {
    const bh = (n / top) * (h - 12);
    const lab = `${i}${tailLabel && i === v.length - 1 && values.length > max ? "+" : ""}: ${n}`;
    return `<rect x="${(i * bw + 0.5).toFixed(1)}" y="${(h - 12 - bh).toFixed(1)}" width="${Math.max(1, bw - 1).toFixed(1)}" height="${bh.toFixed(1)}" fill="#8fc1ff"><title>${lab}</title></rect>`;
  }).join("");
  return `<div class="shp"><svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${rects}` +
    `<text x="0" y="${h - 1}" fill="#8b96a3" font-size="9">0</text><text x="${w}" y="${h - 1}" text-anchor="end" fill="#8b96a3" font-size="9">${v.length - 1}${values.length > max ? "+" : ""}</text>` +
    `<text x="${w}" y="9" text-anchor="end" fill="#d8dee6" font-size="9">max ${top}</text></svg><div class="sub">${esc(title)}</div></div>`;
}

// m: rows x cols numbers. Draws into canvas `cv` (size px square); diagonal cells are dim grey.
export function drawMatrix(cv, m, { size = 150, diagonal = true } = {}) {
  const k = m.length, ctx = cv.getContext("2d");
  cv.width = size; cv.height = size;
  ctx.fillStyle = "#10131a"; ctx.fillRect(0, 0, size, size);
  const off = m.flatMap((r, i) => r.filter((_, j) => i !== j)), max = Math.max(1, ...off);
  const c = size / Math.max(1, k);
  for (let i = 0; i < k; i++) for (let j = 0; j < k; j++) {
    const v = m[i][j];
    if (!v) continue;
    if (i === j) { if (!diagonal) continue; ctx.fillStyle = "#3a4350"; }
    else { const t = heat(v, max); ctx.fillStyle = `rgb(${Math.round(60 + 195 * t)},${Math.round(40 + 140 * t)},${Math.round(30 + 20 * t)})`; }
    ctx.fillRect(Math.floor(j * c), Math.floor(i * c), Math.max(1, Math.ceil(c)), Math.max(1, Math.ceil(c)));
  }
  return { k, cell: c, max };
}

// cluster x delay level counts
export function drawShape(cv, m, { size = 150 } = {}) {
  const ctx = cv.getContext("2d"), rows = m.length, cols = m[0]?.length ?? 1;
  cv.width = size; cv.height = size;
  ctx.fillStyle = "#10131a"; ctx.fillRect(0, 0, size, size);
  const max = Math.max(1, ...m.flat()), cw = size / cols, ch = size / Math.max(1, rows);
  m.forEach((r, i) => r.forEach((v, j) => {
    if (!v) return;
    const t = heat(v, max);
    ctx.fillStyle = `rgb(${Math.round(30 + 40 * t)},${Math.round(60 + 170 * t)},${Math.round(90 + 150 * t)})`;
    ctx.fillRect(Math.floor(j * cw), Math.floor(i * ch), Math.max(1, Math.ceil(cw)), Math.max(1, Math.ceil(ch)));
  }));
  return { rows, cols, cw, ch };
}

// canvas position -> [i, j] of a matrix of k x k drawn at `size`
export const cellAt = (x, y, k, size) => [Math.min(k - 1, Math.floor((y / size) * k)), Math.min(k - 1, Math.floor((x / size) * k))];
