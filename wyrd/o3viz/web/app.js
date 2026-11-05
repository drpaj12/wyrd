// o3viz viewer: one benchmark as a stack of planes (three.js, vendored, no network).
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { parse, evaluate, varsOf } from "./expr.js";
import { spearman, mutualInfo } from "./stats.js";
import { parseSpan, innermost, hdlCovering, reachDown, cone as coneOf } from "./select.js";

const BUNDLE = "./bundle/";
const GREY = new THREE.Color("#5b6572");
const BG = new THREE.Color("#14171c");
const SEQ = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"].map((c) => new THREE.Color(c));
const DIV = ["#d7301f", "#f7f7f7", "#2166ac"].map((c) => new THREE.Color(c));
const $ = (id) => document.getElementById(id);

const S = { man: null, planes: {}, order: [], links: [], up: new Map(), down: new Map(), pos: {},
  bounds: [0, 0, 1, 1], colour: "", size: "", sel: null, core: new Set(), gap: 6, byId: new Map(), ranges: {},
  height: "", fade: "", slot: {}, anchor: "", brush: null, vis: {}, view: "stack",
  lineSel: null, mode: { type: "none" }, focus: null, solo: null, cone: null, coneOn: false, path: null, paths: [], texts: {},
  srcFile: "", morph: { a: "", b: "", m: 0 }, group: { mode: "", expanded: new Set(), keys: {}, blobs: {} }, edges: null, edgeOn: false };

async function getJson(path) {
  const r = await fetch(BUNDLE + path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export async function loadBundle() {
  S.man = await getJson("manifest.json");
  S.order = S.man.planes;
  for (const p of S.order) S.planes[p] = await getJson(`planes/${p}.json`);
  const lj = await getJson("links.json");
  const all = S.order.flatMap((p) => S.planes[p].ids);
  S.links = lj.rows.map(([a, b]) => [all[a], all[b]]);
  for (const [a, b] of S.links) {
    (S.down.get(a) ?? S.down.set(a, []).get(a)).push(b);
    (S.up.get(b) ?? S.up.set(b, []).get(b)).push(a);
  }
  for (const p of S.order) S.planes[p].ids.forEach((id, i) => S.byId.set(id, { plane: p, i }));
  if (S.man.paths > 0) S.paths = (await getJson("paths.json")).paths;
  const files = new Set(Object.keys(S.man.inputs ?? {}));
  for (const p of S.order) for (const srcs of S.planes[p].src) for (const [f] of srcs) files.add(f);
  for (const f of [...files].sort()) {
    const r = await fetch(BUNDLE + "hdl/" + f);
    S.texts[f] = r.ok ? (await r.text()).split("\n") : null;
  }
  await loadAnchor(S.man.anchors.includes("placement") ? "placement" : S.man.anchors[0]);
}

async function loadAnchor(name) {
  const a = await getJson(`anchors/${name}.json`);
  S.pos = a.pos;
  S.bounds = a.bounds;
  S.anchor = name;
  const span = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  S.gap = Math.min(24, Math.max(6, span * 0.5));
  const gs = document.getElementById("gap");
  if (gs) gs.value = String(S.gap);
  S.unanchored = new Set(a.unanchored);
}

// ---- scales ----
function metricRange(name) {
  if (S.ranges[name]) return S.ranges[name];
  let lo = Infinity, hi = -Infinity;
  for (const p of S.order) {
    const col = S.planes[p].metrics[name];
    if (!col) continue;
    for (const v of col) if (v !== null) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  }
  if (lo === Infinity) { lo = 0; hi = 1; }
  if (hi === lo) hi = lo + 1;
  return (S.ranges[name] = [lo, hi]);
}
const meta = (name) => S.man.metrics.find((m) => m.name === name);

function ramp(stops, t) {
  const x = Math.min(Math.max(t, 0), 1) * (stops.length - 1);
  const i = Math.min(Math.floor(x), stops.length - 2);
  return stops[i].clone().lerp(stops[i + 1], x - i);
}
function colourOf(name, v) {
  if (v === null || v === undefined) return GREY.clone();
  const [lo, hi] = metricRange(name);
  if (meta(name).scale === "div") {
    const m = Math.max(Math.abs(lo), Math.abs(hi));
    return ramp(DIV, (v + m) / (2 * m));
  }
  return ramp(SEQ, (v - lo) / (hi - lo));
}

// ---- scene ----
let renderer, scene, camera, controls, group, raycaster, meshes = {}, quads = {}, lines = null;
const dummy = new THREE.Object3D();
const cx = () => (S.bounds[0] + S.bounds[2]) / 2;
const cz = () => (S.bounds[1] + S.bounds[3]) / 2;
const planeY = (k) => (S.order.length - 1 - k) * S.gap;

// One shape per object kind inside a plane (shape channel): the kinds of a plane are sorted and take the
// shapes in this order.
const SHAPES = [
  () => new THREE.SphereGeometry(1, 10, 8), () => new THREE.BoxGeometry(1.5, 1.5, 1.5),
  () => new THREE.OctahedronGeometry(1.2), () => new THREE.ConeGeometry(1, 2, 8),
  () => new THREE.TetrahedronGeometry(1.3), () => new THREE.DodecahedronGeometry(1.1),
];
const CONE_COL = { seed: "#ffb454", in: "#5fe0ff", out: "#ff6fd8" };
const RADIUS = { hdl: 0.22, lut: 0.17, clb: 0.2, placed: 0.11 };

function label(text) {
  const c = document.createElement("canvas");
  c.width = 256; c.height = 64;
  const g = c.getContext("2d");
  g.fillStyle = "#d8dee6"; g.font = "bold 34px sans-serif"; g.fillText(text, 6, 44);
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthTest: false }));
  s.scale.set(4, 1, 1);
  return s;
}

function buildScene() {
  const canvas = $("view");
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
  renderer.setClearColor(BG);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 4000);
  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.autoRotateSpeed = 1.2;
  controls.enableZoom = false; // the wheel is handled by wheelZoom (towards the cursor)
  group = new THREE.Group();
  scene.add(group);
  raycaster = new THREE.Raycaster();
  const W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  S.order.forEach((p) => {
    const d = S.planes[p];
    const kinds = [...new Set(d.kind)].sort();
    meshes[p] = kinds.map((kind, ki) => {
      const idx = d.ids.map((_, i) => i).filter((i) => d.kind[i] === kind);
      const m = new THREE.InstancedMesh(SHAPES[ki % SHAPES.length](), new THREE.MeshBasicMaterial(), idx.length);
      m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(idx.length * 3), 3);
      m.userData = { plane: p, kind, idx };
      idx.forEach((i, j) => { (S.slot[p] ??= [])[i] = [m, j]; });
      group.add(m);
      return m;
    });
    const q = new THREE.Mesh(new THREE.PlaneGeometry(W, H), new THREE.MeshBasicMaterial({
      color: 0x4a5a70, transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
    q.rotation.x = -Math.PI / 2;
    const edge = new THREE.LineSegments(new THREE.EdgesGeometry(q.geometry), new THREE.LineBasicMaterial({ color: 0x6d7f99 }));
    edge.rotation.x = -Math.PI / 2;
    const lab = label(`${p}  (${d.ids.length})`);
    quads[p] = { q, edge, lab };
    group.add(q, edge, lab);
  });
  layout();
  resetCamera();
}

function resizeQuads() {
  const W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  S.order.forEach((p) => {
    const { q, edge } = quads[p];
    q.geometry.dispose(); edge.geometry.dispose();
    q.geometry = new THREE.PlaneGeometry(W, H);
    edge.geometry = new THREE.EdgesGeometry(q.geometry);
  });
}

function layout() {
  S.order.forEach((p, k) => {
    const y = planeY(k);
    const { q, edge, lab } = quads[p];
    q.position.set(0, y - 0.01, 0); edge.position.copy(q.position);
    lab.position.set(-(S.bounds[2] - S.bounds[0]) / 2 + 2, y + 0.4, (S.bounds[3] - S.bounds[1]) / 2 + 0.5);
    refreshPlane(p);
  });
  drawLines();
}

function stateOf(id) {
  if (S.cone?.nodes.has(id)) return 3;
  if (S.brush) return S.brush.has(id) ? 2 : S.core.has(id) ? 1 : -1;
  if (!S.sel) return S.cone ? -1 : 0;
  if (id === S.sel) return 2;
  return S.core.has(id) ? 1 : -1;
}

const norm = (name, v) => { const [lo, hi] = metricRange(name); return (v - lo) / (hi - lo); };

function heightOf(d, i) {
  if (!S.height) return 0;
  const v = d.metrics[S.height]?.[i];
  return v === null || v === undefined ? 0 : norm(S.height, v) * S.gap * 0.45;
}

function morphTarget(p, i) {
  const { a, b, m } = S.morph;
  if (p !== b || !m || !a || S.order.indexOf(a) >= S.order.indexOf(b)) return null;
  const id = S.planes[p].ids[i];
  const ups = (S.up.get(id) ?? []).filter((u) => S.byId.get(u)?.plane === a);
  if (!ups.length) return { y: m, x: null, z: null };
  const xs = ups.map((u) => S.pos[a][u]);
  return { y: m, x: xs.reduce((t, q) => t + q[0], 0) / xs.length, z: xs.reduce((t, q) => t + q[1], 0) / xs.length };
}

function hiddenByGroup(p, i) {
  const keys = S.group.keys[p];
  return !!keys && keys[i] !== null && keys[i] !== undefined && !S.group.expanded.has(keys[i]);
}

function refreshPlane(p) {
  const d = S.planes[p], k = S.order.indexOf(p);
  const col = S.colour ? d.metrics[S.colour] : null;
  const sz = S.size ? d.metrics[S.size] : null;
  const fd = S.fade ? d.metrics[S.fade] : null;
  const r0 = unitR(p);
  d.ids.forEach((id, i) => {
    const [m, j] = S.slot[p][i];
    const pos = S.pos[p][id];
    let x = pos[0] - cx(), z = pos[1] - cz(), y = planeY(k) + heightOf(d, i);
    const mt = morphTarget(p, i);
    if (mt) {
      const ya = planeY(S.order.indexOf(S.morph.a));
      y = y + (ya - y) * mt.y;
      if (mt.x !== null) { x += (mt.x - cx() - x) * mt.y; z += (mt.z - cz() - z) * mt.y; }
    }
    dummy.position.set(x, y, z);
    let s = r0;
    if (sz) s *= sz[i] === null ? 0.5 : 0.6 + 1.8 * norm(S.size, sz[i]);
    const st = stateOf(id);
    if (st === 2) s *= S.brush ? 1.5 : 2.4; else if (st === 3) s *= 1.3; else if (st === 1) s *= S.brush ? 1.15 : 1.5; else if (st === -1) s *= 0.55;
    if (hiddenByGroup(p, i)) s = 1e-4;
    dummy.scale.setScalar(s);
    dummy.updateMatrix();
    m.setMatrixAt(j, dummy.matrix);
    let c = col ? colourOf(S.colour, col[i]) : new THREE.Color("#8fc1ff");
    if (fd) c.lerp(BG, 0.85 * (1 - (fd[i] === null ? 0 : norm(S.fade, fd[i]))));
    if (st === 3) c = new THREE.Color(CONE_COL[S.cone.nodes.get(id)] ?? "#5fe0ff");
    else if (st === 2) c = new THREE.Color("#ffb454");
    else if (st === -1) c.lerp(BG, 0.82);
    m.setColorAt(j, c);
  });
  for (const m of meshes[p]) {
    m.instanceMatrix.needsUpdate = true;
    m.instanceColor.needsUpdate = true;
    m.computeBoundingSphere();
  }
  refreshBlobs(p);
}
const unitR = (p) => (RADIUS[p] ?? 0.15) * Math.max(1, Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]) / 12);

// ---- grouping: one blob per group (HDL module or VPR cluster); click a blob to expand it ----
function groupKeys(mode) {
  const keys = {};
  if (!mode) return keys;
  for (const p of ["lut", "placed"]) {
    if (!S.planes[p]) continue;
    keys[p] = S.planes[p].ids.map((id) => {
      const lut = p === "lut" ? id : (S.up.get(id) ?? []).find((u) => S.byId.get(u)?.plane === "lut");
      if (mode === "cluster") {
        const links = p === "lut" ? S.down.get(id) ?? [] : S.up.get(id) ?? [];
        const c = links.find((u) => S.byId.get(u)?.plane === "clb");
        return c ? S.planes.clb.name[S.byId.get(c).i] : null;
      }
      const m = (lut ? S.up.get(lut) ?? [] : []).find((u) => { const o = S.byId.get(u); return o?.plane === "hdl" && S.planes.hdl.type[o.i] === "module"; });
      return m ? S.planes.hdl.name[S.byId.get(m).i] : null;
    });
  }
  return keys;
}

function setGroupMode(mode) {
  $("grouping").value = mode;
  for (const p of Object.keys(S.group.blobs)) { group.remove(S.group.blobs[p].mesh); S.group.blobs[p].mesh.dispose(); }
  S.group = { mode, expanded: new Set(), keys: groupKeys(mode), blobs: {} };
  for (const p of Object.keys(S.group.keys)) {
    const gs = new Map();
    S.group.keys[p].forEach((key, i) => { if (key !== null) (gs.get(key) ?? gs.set(key, []).get(key)).push(i); });
    const list = [...gs.entries()].sort((x, y) => (x[0] < y[0] ? -1 : 1)).map(([key, members]) => ({ key, members }));
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 14, 10), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.85 }), Math.max(1, list.length));
    mesh.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(1, list.length) * 3), 3);
    mesh.userData = { blob: p, list };
    mesh.count = list.length;
    group.add(mesh);
    S.group.blobs[p] = { mesh, list };
  }
  refreshAll();
}

function refreshBlobs(p) {
  const bl = S.group.blobs[p];
  if (!bl) return;
  const d = S.planes[p], k = S.order.indexOf(p);
  const col = S.colour ? d.metrics[S.colour] : null;
  bl.list.forEach((g, n) => {
    const open = S.group.expanded.has(g.key);
    let x = 0, z = 0, sum = 0, cnt = 0;
    for (const i of g.members) {
      const q = S.pos[p][d.ids[i]];
      x += q[0]; z += q[1];
      if (col && col[i] !== null) { sum += col[i]; cnt++; }
    }
    dummy.position.set(x / g.members.length - cx(), planeY(k), z / g.members.length - cz());
    dummy.scale.setScalar(open ? 1e-4 : Math.min(unitR(p) * (0.8 + 0.3 * Math.cbrt(g.members.length)), Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]) / 9));
    dummy.updateMatrix();
    bl.mesh.setMatrixAt(n, dummy.matrix);
    bl.mesh.setColorAt(n, col && cnt ? colourOf(S.colour, sum / cnt) : new THREE.Color("#8fc1ff"));
  });
  bl.mesh.instanceMatrix.needsUpdate = true;
  bl.mesh.instanceColor.needsUpdate = true;
  bl.mesh.visible = S.vis[p] !== false && (S.view === "stack" || S.view === p);
  bl.mesh.computeBoundingSphere();
}

const refreshAll = () => { S.order.forEach(refreshPlane); drawLines(); drawEdges(); drawPathLines(); legend(); };

function worldPos(plane, id) {
  const k = S.order.indexOf(plane), i = S.byId.get(id).i, p = S.pos[plane][id];
  return new THREE.Vector3(p[0] - cx(), planeY(k) + heightOf(S.planes[plane], i), p[1] - cz());
}

function drawLines() {
  if (lines) { group.remove(lines); lines.geometry.dispose(); lines = null; }
  if (!S.sel) return;
  const pts = [];
  const a = S.byId.get(S.sel);
  const from = worldPos(a.plane, S.sel);
  let n = 0;
  for (const id of [...(S.up.get(S.sel) ?? []), ...(S.down.get(S.sel) ?? [])]) {
    const b = S.byId.get(id);
    if (!b || n++ > 400) continue;
    pts.push(from, worldPos(b.plane, id));
  }
  if (!pts.length) return;
  lines = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color: 0xffb454, transparent: true, opacity: 0.55 }));
  group.add(lines);
}

function resize() {
  const r = $("stage").getBoundingClientRect();
  renderer.setSize(r.width, r.height, false);
  camera.aspect = r.width / r.height;
  camera.updateProjectionMatrix();
}
function resetCamera() {
  S.focus = null; markFocus();
  const W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  const h = (S.order.length - 1) * S.gap;
  controls.target.set(0, h / 2, 0);
  const dist = Math.max(h * 1.1, W * 1.5) * 1.9;
  camera.position.set(dist * 0.5, h / 2 + dist * 0.42, dist * 0.75);
  controls.update();
}

// ---- selection ----
function closure(start, dir) {
  const seen = new Set(), planes = new Set();
  let frontier = [start];
  const step = dir === "down" ? S.down : S.up;
  const sign = dir === "down" ? 1 : -1;
  while (frontier.length) {
    const next = [];
    for (const id of frontier) {
      const a = S.byId.get(id), ka = S.order.indexOf(a.plane);
      for (const t of step.get(id) ?? []) {
        const b = S.byId.get(t);
        if (!b || seen.has(t)) continue;
        const kb = S.order.indexOf(b.plane);
        if (sign * (kb - ka) <= 0) continue;
        // expand only into planes not yet reached from the start, so a cluster does not drag its siblings in
        if (id !== start && planes.has(b.plane)) continue;
        seen.add(t); next.push(t);
      }
    }
    for (const t of next) planes.add(S.byId.get(t).plane);
    frontier = next;
  }
  return seen;
}

export function select(id) {
  if (!S.byId.has(id)) return;
  S.sel = id;
  S.brush = null;
  S.lineSel = null; S.path = null;
  S.mode = { type: "obj" };
  for (const p of Object.keys(S.group.keys)) {
    const k = S.group.keys[p][S.byId.get(id).plane === p ? S.byId.get(id).i : -1];
    if (k) S.group.expanded.add(k);
  }
  S.core = new Set([...closure(id, "up"), ...closure(id, "down")]);
  afterSelection();
}
function clearSel() {
  S.sel = null; S.brush = null; S.core = new Set(); S.lineSel = null; S.path = null; S.cone = null;
  S.mode = { type: "none" };
  $("pathinfo").textContent = "no path drawn";
  document.querySelectorAll("#pathlist div.on").forEach((e) => e.classList.remove("on"));
  refreshAll(); markLines();
  $("sel").textContent = "Click an HDL line or a node. Everything linked to it is highlighted."; $("sel").className = "sub";
}
async function afterSelection() {
  if (S.coneOn) await updateCone(); else refreshAll();
  markLines();
  showSelection();
}

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
const fmt = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(3));

function infoRows(id) {
  const { plane, i } = S.byId.get(id), d = S.planes[plane];
  const rows = [["id", id], ["plane", plane], ["kind", d.kind[i]], ["type", d.type[i]], ["origin", d.origin[i]], ["name", d.name[i]]];
  for (const m of S.man.metrics) {
    const v = d.metrics[m.name]?.[i];
    if (v !== null && v !== undefined) rows.push([m.name, `${fmt(v)} ${m.unit}`]);
  }
  return rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
}

// objects highlighted (selected, brushed, drawn path or linked) per plane
function highlighted() {
  return new Set([...(S.sel ? [S.sel] : []), ...(S.brush ?? []), ...S.core]);
}
export function planeCounts() {
  const c = Object.fromEntries(S.order.map((p) => [p, 0]));
  for (const id of highlighted()) c[S.byId.get(id).plane]++;
  return c;
}

function showSelection() {
  const m = S.mode;
  let html = "";
  if (m.type === "obj" && S.sel) html += `<table>${infoRows(S.sel)}</table>`;
  else if (m.type === "line") {
    html += `<div><b>HDL ${esc(m.file)} line${m.a === m.b ? " " + m.a : "s " + m.a + "-" + m.b}</b>: ` +
      (m.n ? `${m.n} ${$("enclosing").checked ? "covering" : "innermost covering"} construct${m.n === 1 ? "" : "s"}` : "no construct covers it") + "</div>";
  } else if (m.type === "path") html += `<div><b>Path</b>: ${esc(S.pathInfo ?? "")}</div>`;
  else if (m.type === "brush") html += `<div><b>Brush</b>: ${m.n} objects of ${m.plane}</div>`;
  const c = planeCounts();
  html += '<h2>Linked objects per plane</h2><div class="col">' + S.order.map((p) =>
    `<div class="prow${S.focus === p ? " on" : ""}"><b>${p}</b><span>${c[p]}</span><button data-focus="${p}">focus</button></div>`).join("") + "</div>";
  $("sel").className = "";
  $("sel").innerHTML = html;
  $("sel").querySelectorAll("button[data-focus]").forEach((b) => b.addEventListener("click", () => focusPlane(b.dataset.focus)));
}

// ---- source pane: the whole HDL file, line numbers; click or drag lines to select what they produced ----
const RANK = { hitw: 1, hit: 2, sel: 3 };
let rows = [], marks = new Map(), dragging = false;

function showFile(file) {
  S.srcFile = file;
  const text = S.texts[file];
  const box = $("srclines");
  box.innerHTML = "";
  rows = [];
  if (!text) { box.innerHTML = `<div class="sub" style="padding:8px">${esc(file)} is not in the bundle (export with --src)</div>`; }
  else {
    const frag = document.createDocumentFragment();
    const n = text.length && text[text.length - 1] === "" ? text.length - 1 : text.length;
    for (let i = 0; i < n; i++) {
      const row = document.createElement("div");
      row.className = "ln"; row.dataset.n = String(i + 1);
      row.innerHTML = `<span class="no">${i + 1}</span><span class="tx">${esc(text[i])}</span>`;
      rows[i + 1] = row;
      frag.appendChild(row);
    }
    box.appendChild(frag);
  }
  document.querySelectorAll("#srctabs button").forEach((b) => b.classList.toggle("on", b.dataset.f === file));
  paintLines();
}

function paintLines() {
  const mk = marks.get(S.srcFile), ls = S.lineSel && S.lineSel.file === S.srcFile ? S.lineSel : null;
  const lo = ls ? Math.min(ls.a, ls.b) : 0, hi = ls ? Math.max(ls.a, ls.b) : -1;
  for (let n = 1; n < rows.length; n++) {
    const cls = ls && n >= lo && n <= hi ? "sel" : mk?.get(n);
    rows[n].className = "ln" + (cls ? " " + cls : "");
  }
}

// lines behind the current selection: innermost HDL constructs among the linked ones, plus the own span of
// the primary non-HDL objects; the user's own lines stay "sel"
function markLines() {
  marks = new Map();
  const put = (file, line, cls) => {
    const m = marks.get(file) ?? marks.set(file, new Map()).get(file);
    if (!m.has(line) || RANK[cls] > RANK[m.get(line)]) m.set(line, cls);
  };
  const prim = (id) => id === S.sel || S.brush?.has(id);
  const hdlItems = [], own = [];
  for (const id of highlighted()) {
    const o = S.byId.get(id), src = S.planes[o.plane].src[o.i];
    if (o.plane === "hdl") {
      const sp = src[0] && parseSpan(src[0][1]);
      if (sp) hdlItems.push({ file: src[0][0], span: sp });
    } else if (prim(id) && src.length) {
      const last = src[src.length - 1], sp = parseSpan(last[1]);
      if (sp) own.push({ file: last[0], span: sp });
    }
  }
  if (S.cone) for (const id of S.cone.nodes.keys()) {
    const o = S.byId.get(id), src = o && S.planes[o.plane].src[o.i];
    const last = src?.[src.length - 1], sp = last && parseSpan(last[1]);
    if (sp) for (let l = sp.l0; l <= sp.l1; l++) put(last[0], l, "hitw");
  }
  const strong = S.mode.type === "line" ? "hitw" : "hit";
  for (const file of new Set(hdlItems.map((x) => x.file))) {
    for (const it of innermost(hdlItems.filter((x) => x.file === file))) for (let l = it.span.l0; l <= it.span.l1; l++) put(file, l, strong);
  }
  for (const it of own) for (let l = it.span.l0; l <= it.span.l1; l++) put(it.file, l, "hit");
  // scroll to the first marked line, unless the user is working in the pane
  if (S.mode.type !== "line" && marks.size) {
    let best = null, bestN = -1;
    for (const [f, m] of marks) if (m.size > bestN) { best = f; bestN = m.size; }
    if (best !== S.srcFile) showFile(best);
    const first = Math.min(...marks.get(best).keys());
    const box = $("srclines");
    if (rows[first]) box.scrollTop = Math.max(0, rows[first].offsetTop - box.clientHeight / 3);
  }
  paintLines();
  const nl = [...marks.values()].reduce((t, m) => t + m.size, 0);
  $("srcinfo").firstChild.textContent = S.mode.type === "none" || !marks.size && S.mode.type !== "line"
    ? (S.mode.type === "none" ? "Click a line, drag or shift-click for a range. " : "No HDL lines behind this selection. ")
    : `${nl} HDL line${nl === 1 ? "" : "s"} highlighted. `;
}

function selectLines(file, a, b) {
  if (!S.planes.hdl) return;
  const hdl = S.planes.hdl;
  const idx = hdlCovering(hdl, file, a, b, $("enclosing").checked);
  const ids = [...idx].map((i) => hdl.ids[i]);
  S.sel = null; S.path = null;
  S.lineSel = { file, a, b };
  S.mode = { type: "line", file, a: Math.min(a, b), b: Math.max(a, b), n: ids.length };
  if (!ids.length) { S.brush = null; S.core = new Set(); }
  else {
    const r = reachDown(ids, S.order, (id) => S.byId.get(id)?.plane, S.down);
    S.brush = new Set(ids);
    S.core = new Set(S.order.slice(1).flatMap((p) => [...r[p]]));
  }
  afterSelection();
}

function buildSource() {
  const files = Object.keys(S.texts);
  $("srctabs").innerHTML = files.map((f) => `<button data-f="${esc(f)}">${esc(f)}</button>`).join("");
  $("srctabs").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => showFile(b.dataset.f)));
  const first = (() => {
    const d = S.planes.hdl;
    return (d && d.src.find((s) => s.length)?.[0][0]) || files[0] || "";
  })();
  showFile(first);
  const box = $("srclines");
  const lineOf = (e) => { const r = e.target.closest?.(".ln"); return r ? Number(r.dataset.n) : null; };
  box.addEventListener("mousedown", (e) => {
    const n = lineOf(e);
    if (n === null || e.button !== 0) return;
    const keep = e.shiftKey && S.lineSel && S.lineSel.file === S.srcFile ? S.lineSel.a : n;
    S.lineSel = { file: S.srcFile, a: keep, b: n };
    dragging = true;
    paintLines();
    e.preventDefault();
  });
  box.addEventListener("mouseover", (e) => {
    const n = lineOf(e);
    if (!dragging || n === null || !S.lineSel) return;
    S.lineSel.b = n;
    paintLines();
  });
  document.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    if (S.lineSel) selectLines(S.lineSel.file, S.lineSel.a, S.lineSel.b);
  });
  $("enclosing").addEventListener("change", () => { if (S.lineSel) selectLines(S.lineSel.file, S.lineSel.a, S.lineSel.b); });
  // resizable split between the source pane and the 3D view
  const split = $("split");
  split.addEventListener("pointerdown", (e) => {
    split.setPointerCapture(e.pointerId); split.classList.add("drag");
    const main = $("main").getBoundingClientRect();
    const move = (ev) => { $("srcpane").style.flexBasis = Math.min(main.width - 200, Math.max(120, ev.clientX - main.left)) + "px"; };
    const up = () => { split.classList.remove("drag"); split.removeEventListener("pointermove", move); split.removeEventListener("pointerup", up); };
    split.addEventListener("pointermove", move); split.addEventListener("pointerup", up);
  });
}

// ---- picking ----
function pick(ev) {
  const r = $("view").getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
  let best = null;
  const take = (hit, what) => { if (hit && (!best || hit.distance < best.distance)) best = { distance: hit.distance, ...what }; };
  for (const p of S.order) {
    for (const m of meshes[p]) {
      if (!m.visible) continue;
      const hit = raycaster.intersectObject(m)[0];
      take(hit, hit && { id: S.planes[p].ids[m.userData.idx[hit.instanceId]] });
    }
    const bl = S.group.blobs[p];
    if (bl?.mesh.visible) {
      const hit = raycaster.intersectObject(bl.mesh)[0];
      take(hit, hit && { blob: bl.list[hit.instanceId], plane: p });
    }
  }
  return best;
}

// ---- edges: k-hop neighbourhood of the selection, or aggregated edges between groups ----
let edgeLines = null;
async function ensureEdges() {
  if (S.edges) return;
  S.edges = await getJson("edges/lut.json");
  S.adj = new Map();
  for (const [a, b] of S.edges) {
    (S.adj.get(a) ?? S.adj.set(a, []).get(a)).push(b);
    (S.adj.get(b) ?? S.adj.set(b, []).get(b)).push(a);
  }
}

function drawEdges() {
  if (edgeLines) { group.remove(edgeLines); edgeLines.geometry.dispose(); edgeLines = null; }
  if (!S.edges || !S.edgeMode || !S.planes.lut) return;
  const pts = [], cols = [];
  if (S.edgeMode === "groups") {
    const bl = S.group.blobs.lut;
    if (!bl) return;
    const of = new Map();
    bl.list.forEach((g, n) => g.members.forEach((i) => of.set(S.planes.lut.ids[i], n)));
    const cen = bl.list.map((g) => {
      let x = 0, z = 0;
      for (const i of g.members) { const q = S.pos.lut[S.planes.lut.ids[i]]; x += q[0]; z += q[1]; }
      return new THREE.Vector3(x / g.members.length - cx(), planeY(S.order.indexOf("lut")), z / g.members.length - cz());
    });
    const cnt = new Map();
    for (const [a, b] of S.edges) {
      const ga = of.get(a), gb = of.get(b);
      if (ga === undefined || gb === undefined || ga === gb) continue;
      const key = ga < gb ? `${ga}|${gb}` : `${gb}|${ga}`;
      cnt.set(key, (cnt.get(key) ?? 0) + 1);
    }
    const mx = Math.max(1, ...cnt.values());
    for (const [key, c] of cnt) {
      const [ga, gb] = key.split("|").map(Number);
      pts.push(cen[ga], cen[gb]);
      const t = 0.25 + 0.75 * (c / mx);
      cols.push(t, t * 0.8, 0.2, t, t * 0.8, 0.2);
    }
  } else {
    const start = new Set();
    const ids = S.brush ? [...S.brush, ...S.core] : S.sel ? [S.sel, ...S.core] : [];
    for (const id of ids) if (S.byId.get(id)?.plane === "lut" && start.size < 300) start.add(id);
    let seen = new Set(start), frontier = [...start];
    for (let h = 0; h < S.hops; h++) {
      const next = [];
      for (const id of frontier) for (const t of S.adj.get(id) ?? []) if (!seen.has(t)) { seen.add(t); next.push(t); }
      frontier = next;
    }
    let n = 0;
    for (const [a, b] of S.edges) {
      if (!seen.has(a) || !seen.has(b) || n++ > 4000) continue;
      pts.push(worldPos("lut", a), worldPos("lut", b));
      cols.push(0.3, 0.9, 1, 0.3, 0.9, 1);
    }
  }
  if (!pts.length) return;
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  g.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
  edgeLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.7 }));
  group.add(edgeLines);
}

// ---- views: the 3D stack, or one plane seen from above ----
function applyVisibility() {
  for (const p of S.order) {
    const v = S.vis[p] !== false && (S.view === "stack" || S.view === p);
    meshes[p].forEach((m) => { m.visible = v; });
    quads[p].q.visible = quads[p].edge.visible = quads[p].lab.visible = v;
    if (S.group.blobs[p]) S.group.blobs[p].mesh.visible = v;
  }
}
function setView(v) {
  S.view = v;
  $("viewmode").value = v;
  applyVisibility();
  if (v === "stack") { controls.enableRotate = true; resetCamera(); return; }
  const y = planeY(S.order.indexOf(v)), W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  controls.enableRotate = false;
  controls.autoRotate = false; $("rotate").checked = false;
  controls.target.set(0, y, 0);
  camera.position.set(0, y + W * 1.5, 0.001);
  controls.update();
}

// ---- brush: shift + drag a rectangle on the screen; objects of the brush plane inside it are selected ----
function brushSelect(x0, y0, x1, y1) {
  const p = $("brushplane").value, d = S.planes[p], r = $("view").getBoundingClientRect(), hit = new Set();
  d.ids.forEach((id, i) => {
    if (hiddenByGroup(p, i)) return;
    const v = worldPos(p, id).project(camera);
    const sx = ((v.x + 1) / 2) * r.width + r.left, sy = ((1 - v.y) / 2) * r.height + r.top;
    if (sx >= Math.min(x0, x1) && sx <= Math.max(x0, x1) && sy >= Math.min(y0, y1) && sy <= Math.max(y0, y1)) hit.add(id);
  });
  if (!hit.size) return;
  const core = new Set();
  let n = 0;
  for (const id of hit) { if (n++ > 600) break; for (const t of [...closure(id, "up"), ...closure(id, "down")]) core.add(t); }
  S.sel = null; S.brush = hit; S.core = core; S.lineSel = null; S.path = null;
  S.mode = { type: "brush", n: hit.size, plane: p };
  afterSelection();
}

// ---- discovery: Spearman and mutual information between the metrics of one plane ----
function discover() {
  const p = $("dplane").value, d = S.planes[p], kind = $("dkind").value;
  const names = Object.keys(d.metrics).filter((n) => {
    const v = d.metrics[n].filter((x) => x !== null);
    return v.length >= 10 && new Set(v).size > 1;
  });
  const fn = kind === "mi" ? mutualInfo : spearman;
  let html = `<div class="sub">${names.length} metrics with 10 or more values on ${p} (${d.ids.length} objects); click a cell: colour = row, size = column</div><table><tr><td></td>${names.map((n, j) => `<td title="${esc(n)}">${j + 1}</td>`).join("")}</tr>`;
  names.forEach((a, i) => {
    html += `<tr><td title="${esc(a)}">${i + 1} ${esc(a.slice(0, 14))}</td>`;
    names.forEach((b) => {
      const v = a === b ? null : fn(d.metrics[a], d.metrics[b]);
      const t = v === null ? 0 : kind === "mi" ? Math.min(1, v / 2) : Math.abs(v);
      const hue = kind === "mi" ? 40 : v !== null && v < 0 ? 5 : 210;
      const sh = v === null ? "" : kind === "mi" ? v.toFixed(2) : v.toFixed(2);
      html += `<td data-a="${esc(a)}" data-b="${esc(b)}" style="background:hsla(${hue},70%,50%,${(0.1 + 0.8 * t).toFixed(2)});cursor:pointer;text-align:center">${sh}</td>`;
    });
    html += "</tr>";
  });
  $("dmat").innerHTML = html + "</table>";
  $("dmat").querySelectorAll("td[data-a]").forEach((c) => c.addEventListener("click", () => {
    if (c.dataset.a === c.dataset.b) return;
    S.colour = c.dataset.a; S.size = c.dataset.b; $("colour").value = S.colour; $("size").value = S.size; refreshAll();
  }));
}
export const discoverMatrix = (plane, kind) => {
  const d = S.planes[plane], fn = kind === "mi" ? mutualInfo : spearman;
  const names = Object.keys(d.metrics).filter((n) => d.metrics[n].filter((x) => x !== null).length >= 10);
  return { names, m: names.map((a) => names.map((b) => (a === b ? null : fn(d.metrics[a], d.metrics[b])))) };
};

// ---- plane control: focus (camera on a plane), zoom towards the cursor, solo ----
function setColour(n) {
  if (!meta(n)) return;
  S.colour = n; $("colour").value = n; refreshAll();
}

function markFocus() {
  document.querySelectorAll("#sel .prow").forEach((r) => r.classList.toggle("on", r.querySelector("button")?.dataset.focus === S.focus));
  if (!quads) return;
  for (const p of S.order) if (quads[p]) quads[p].edge.material.color.set(p === S.focus ? 0xffb454 : 0x6d7f99);
}

export function focusPlane(p) {
  if (!p) { S.focus = null; if (S.view === "stack") resetCamera(); markFocus(); return; }
  if (!S.order.includes(p)) return;
  if (S.view !== "stack") { setView(p); S.focus = p; markFocus(); return; }
  S.focus = p;
  const y = planeY(S.order.indexOf(p)), W = Math.max(S.bounds[2] - S.bounds[0], S.bounds[3] - S.bounds[1]);
  const off = camera.position.clone().sub(controls.target);
  if (off.length() < 1e-6) off.set(0.3, 0.8, 0.5);
  off.y = Math.max(off.y, off.length() * 0.6);
  off.setLength(Math.max(W * 1.35, 8));
  controls.target.set(0, y, 0);
  camera.position.copy(controls.target).add(off);
  controls.update();
  markFocus();
}

export function soloPlane(p) {
  const off = S.solo === p;
  for (const q of S.order) S.vis[q] = off ? true : q === p;
  S.solo = off ? null : p;
  $("planes").querySelectorAll("input[data-p]").forEach((c) => { c.checked = S.vis[c.dataset.p] !== false; });
  applyVisibility();
}

// the wheel zooms towards the point under the cursor on the focused plane (or on the nearest plane under the
// cursor when none is focused): the camera and the orbit target both move towards that point
function wheelZoom(ev) {
  ev.preventDefault();
  const r = $("view").getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
  const ray = raycaster.ray, W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  let best = null;
  for (const p of S.focus ? [S.focus] : S.order) {
    if (!S.focus && S.vis[p] === false) continue;
    const y = planeY(S.order.indexOf(p));
    if (Math.abs(ray.direction.y) < 1e-6) continue;
    const t = (y - ray.origin.y) / ray.direction.y;
    if (t <= 0) continue;
    const hit = ray.origin.clone().addScaledVector(ray.direction, t);
    if (!S.focus && (Math.abs(hit.x) > W / 2 || Math.abs(hit.z) > H / 2)) continue;
    if (!best || t < best.t) best = { t, hit };
  }
  const P = best ? best.hit : controls.target.clone();
  const dy = ev.deltaMode === 1 ? ev.deltaY * 16 : ev.deltaY;
  let f = Math.exp(dy * 0.0013);
  const dist = camera.position.distanceTo(P);
  if (dist * f < 0.6) f = 0.6 / Math.max(dist, 1e-6);
  if (dist * f > 1500) f = 1500 / dist;
  const dc = camera.position.clone().sub(P), dt = controls.target.clone().sub(P);
  camera.position.copy(P).addScaledVector(dc, f);
  controls.target.copy(P).addScaledVector(dt, f);
  controls.update();
}

// ---- paths: VPR's reported setup paths, and the combinational cone of the selection in the LUT netlist ----
let pathLines = null;
const PATH_COL = { vpr: [1, 0.42, 0.42], in: [0.37, 0.88, 1], out: [1, 0.44, 0.85] };

function drawPathLines() {
  if (pathLines) { group.remove(pathLines); pathLines.geometry.dispose(); pathLines = null; }
  const pts = [], cols = [], seen = new Set();
  const seg = (plane, a, b, c) => {
    if (!S.pos[plane]?.[a] || !S.pos[plane]?.[b]) return;
    const key = plane + a + "|" + b;
    if (seen.has(key) || pts.length > 24000) return;
    seen.add(key);
    pts.push(worldPos(plane, a), worldPos(plane, b));
    cols.push(...c, ...c);
  };
  if (S.path) {
    for (const list of [S.path.lut, S.path.placed]) for (let i = 1; i < list.length; i++) seg(S.byId.get(list[i])?.plane, list[i - 1], list[i], PATH_COL.vpr);
  }
  if (S.cone) {
    const placedOf = (id) => {
      const o = S.byId.get(id);
      const pid = o && S.planes.placed ? "placed:" + S.planes.lut.name[o.i] : null;
      return pid && S.byId.has(pid) ? pid : null;
    };
    for (const [a, b, tag] of S.cone.edges) {
      seg("lut", a, b, PATH_COL[tag]);
      const pa = placedOf(a), pb = placedOf(b);
      if (pa && pb) seg("placed", pa, pb, PATH_COL[tag]);
    }
  }
  if (!pts.length) return;
  const g = new THREE.BufferGeometry().setFromPoints(pts);
  g.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
  pathLines = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, depthTest: false }));
  pathLines.renderOrder = 5;
  group.add(pathLines);
}

export function showPath(i) {
  const P = S.paths[i];
  if (!P) return;
  S.sel = null; S.lineSel = null; S.cone = null; S.coneOn = false;
  $("pathsrc").value = "vpr"; showPathPanel();
  const ids = [...P.lut, ...P.placed].filter((x) => S.byId.has(x));
  const core = new Set();
  for (const l of P.lut) {
    for (const u of S.up.get(l) ?? []) if (S.byId.get(u)?.plane === "hdl" && core.size < 3000) core.add(u);
    for (const d of S.down.get(l) ?? []) if (S.byId.get(d)?.plane === "clb") core.add(d);
  }
  S.path = { lut: P.lut, placed: P.placed, i };
  S.brush = new Set(ids); S.core = core;
  S.pathInfo = `source: VPR report_timing.setup.rpt, path #${P.n}, slack ${fmt(P.slack)} ns, ${P.lut.length} LUT-plane and ${P.placed.length} placed objects`;
  S.mode = { type: "path" };
  $("pathinfo").innerHTML = `<span class="tag">source: VPR report_timing.setup.rpt</span>, path #${P.n}, slack ${fmt(P.slack)} ns, ${P.lut.length} LUT-plane and ${P.placed.length} placed objects. ${esc(P.start)} to ${esc(P.end)}`;
  document.querySelectorAll("#pathlist div").forEach((e) => e.classList.toggle("on", Number(e.dataset.i) === i));
  afterSelection();
}

function coneSeeds() {
  const out = new Set();
  const add = (id) => {
    const o = S.byId.get(id);
    if (!o || out.size >= 300) return;
    if (o.plane === "lut") out.add(id);
    else if (o.plane === "placed") { const l = `luts:${S.man.top}/${S.planes.placed.name[o.i]}`; if (S.byId.has(l)) out.add(l); }
  };
  if (S.sel) add(S.sel);
  for (const id of S.brush ?? []) add(id);
  for (const id of S.core) add(id);
  return out;
}

export async function updateCone() {
  await ensureEdges();
  const seeds = [...coneSeeds()], dir = $("conedir").value, depth = Math.max(1, Number($("conedepth").value) || 6);
  if (!seeds.length) {
    S.cone = null;
    $("pathinfo").textContent = "cone: select an HDL line or an object that has LUT-plane objects first";
    refreshAll();
    return;
  }
  const lut = S.planes.lut;
  S.cone = coneOf(S.edges, seeds, dir, depth, (id) => lut.type[S.byId.get(id)?.i] === "names");
  const nodes = S.cone.nodes.size, label = { in: "fan-in", out: "fan-out", both: "fan-in and fan-out" }[dir];
  $("pathinfo").innerHTML = `<span class="tag">source: netlist cone (edges/lut.json)</span>, ${label}, depth limit ${depth}, from ${seeds.length} seed${seeds.length === 1 ? "" : "s"}: ${nodes} objects, ${S.cone.edges.length} edges. Stops at flip-flops, I/O and hard blocks.`;
  refreshAll();
}

function showPathPanel() {
  const cone = $("pathsrc").value === "cone";
  $("pathvpr").style.display = cone ? "none" : "";
  $("pathcone").style.display = cone ? "" : "none";
}

function buildPathsUi() {
  const list = $("pathlist");
  list.innerHTML = S.paths.length ? S.paths.map((P, i) =>
    `<div data-i="${i}" title="${esc(P.start)} to ${esc(P.end)}">#${P.n}  ${P.slack.toFixed(3)} ns  ${esc(P.start.split(" ")[0])} &gt; ${esc(P.end.split(" ")[0])}  (${P.lut.length} LUT-plane)</div>`).join("")
    : '<div class="sub">no setup-report paths in this bundle (re-export with a VPR run that kept report_timing.setup.rpt)</div>';
  list.querySelectorAll("div[data-i]").forEach((d) => d.addEventListener("click", () => showPath(Number(d.dataset.i))));
  const clearPath = () => {
    S.path = null; S.cone = null; $("pathinfo").textContent = "no path drawn";
    document.querySelectorAll("#pathlist div.on").forEach((e) => e.classList.remove("on"));
    if (S.mode.type === "path") clearSel(); else { refreshAll(); markLines(); }
  };
  $("pathclear").addEventListener("click", clearPath);
  $("pathsrc").addEventListener("change", async () => {
    showPathPanel();
    S.coneOn = $("pathsrc").value === "cone";
    if (S.coneOn) { S.path = null; await updateCone(); markLines(); } else { S.cone = null; $("pathinfo").textContent = "no path drawn"; refreshAll(); markLines(); }
  });
  for (const id of ["conedir", "conedepth"]) $(id).addEventListener("change", async () => { await updateCone(); markLines(); });
}

// ---- UI ----
function fillSelect(sel, names, withNone) {
  sel.innerHTML = (withNone ? '<option value="">(none)</option>' : "") +
    names.map((n) => `<option value="${n}">${n}${meta(n) ? "  [" + meta(n).unit + "]" : ""}</option>`).join("");
}
function legend() {
  const name = S.colour;
  $("legend").style.display = name ? "block" : "none";
  if (!name) { coverLegend(); return; }
  const [lo, hi] = metricRange(name), div = meta(name).scale === "div";
  const stops = div ? DIV : SEQ;
  $("bar").style.background = `linear-gradient(90deg, ${stops.map((c) => "#" + c.getHexString()).join(",")})`;
  const m = Math.max(Math.abs(lo), Math.abs(hi));
  $("lo").textContent = div ? fmt(-m) : fmt(lo);
  $("hi").textContent = div ? fmt(m) : fmt(hi);
  $("mid").textContent = div ? "0" : "";
  coverLegend();
  $("unit").textContent = `${meta(name).unit}; grey = not measured. ${meta(name).measurer}`;
}
// per plane: how many objects have a measured value for the colour metric (grey = none); never invented
export function coverage(name) {
  return S.order.map((p) => {
    const col = S.planes[p].metrics[name], total = S.planes[p].ids.length;
    const n = col ? col.filter((v) => v !== null).length : 0;
    return { plane: p, measured: n, total, range: n ? [Math.min(...col.filter((v) => v !== null)), Math.max(...col.filter((v) => v !== null))] : null };
  });
}
function coverLegend() {
  const el = $("cover");
  if (!S.colour) { el.innerHTML = ""; return; }
  el.innerHTML = coverage(S.colour).map((c) => c.measured
    ? `${c.plane}: ${c.measured}/${c.total} measured, ${fmt(c.range[0])} to ${fmt(c.range[1])}`
    : `${c.plane}: <span class="err" style="color:#ffb454">no measured value (grey)</span>`).join("<br>");
}

// ---- derived metrics: expressions and cross-plane aggregation ----
function fillMetricSelects() {
  const names = S.man.metrics.map((m) => m.name);
  for (const [id, none] of [["colour", true], ["size", true], ["height", true], ["fade", true], ["aggmetric", false]]) {
    const el = $(id), cur = el.value;
    fillSelect(el, names, none);
    if (names.includes(cur)) el.value = cur;
  }
}

function addMetric(name, scale, measurer, cols) {
  S.man.metrics = S.man.metrics.filter((m) => m.name !== name);
  S.man.metrics.push({ name, unit: "derived", planes: Object.keys(cols), scale, measurer, source: "o3viz editor" });
  for (const p of S.order) S.planes[p].metrics[name] = cols[p] ?? S.planes[p].ids.map(() => null);
  delete S.ranges[name];
  fillMetricSelects();
}

export function addExpr(name, text, scale = "seq") {
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) throw new Error("name: letters, digits, underscore");
  const ast = parse(text), vars = [...varsOf(ast)];
  for (const v of vars) if (!meta(v)) throw new Error(`unknown metric "${v}"`);
  if (vars.includes(name)) throw new Error("a metric cannot use its own name");
  const cols = {};
  for (const p of S.order) {
    const d = S.planes[p];
    if (vars.every((v) => d.metrics[v])) cols[p] = d.ids.map((_, i) => evaluate(ast, (n) => d.metrics[n][i]));
  }
  if (!Object.keys(cols).length) throw new Error("no plane has all of these metrics");
  addMetric(name, scale, `expression: ${text}`, cols);
}

const AGG = {
  sum: (v) => v.reduce((a, b) => a + b, 0), mean: (v) => v.reduce((a, b) => a + b, 0) / v.length,
  min: (v) => Math.min(...v), max: (v) => Math.max(...v), count: (v) => v.length,
};

export function addAgg(metric, dir, op) {
  if (!meta(metric) || !AGG[op] || !["below", "above"].includes(dir)) throw new Error("bad aggregation");
  const name = `${op}_${dir}_${metric}`, adj = dir === "below" ? S.down : S.up, cols = {};
  for (const p of S.order) {
    cols[p] = S.planes[p].ids.map((id) => {
      const vals = [];
      for (const t of adj.get(id) ?? []) {
        const b = S.byId.get(t), v = S.planes[b.plane].metrics[metric]?.[b.i];
        if (v !== null && v !== undefined) vals.push(v);
      }
      return vals.length ? AGG[op](vals) : null;
    });
  }
  addMetric(name, meta(metric).scale, `${op} of ${metric} over the objects linked ${dir}`, cols);
  return name;
}

function buildUi() {
  fillMetricSelects();
  $("colour").addEventListener("change", (e) => { S.colour = e.target.value; refreshAll(); });
  $("size").addEventListener("change", (e) => { S.size = e.target.value; refreshAll(); });
  $("height").addEventListener("change", (e) => { S.height = e.target.value; refreshAll(); });
  $("fade").addEventListener("change", (e) => { S.fade = e.target.value; refreshAll(); });
  $("anchor").innerHTML = S.man.anchors.map((a) => `<option${a === S.anchor ? " selected" : ""}>${a}</option>`).join("");
  $("anchor").addEventListener("change", async (e) => {
    await loadAnchor(e.target.value); resizeQuads(); layout(); resetCamera(); refreshAll();
  });
  $("addexpr").addEventListener("click", () => {
    try {
      addExpr($("exname").value.trim(), $("extext").value, $("exscale").value);
      S.colour = $("exname").value.trim(); $("colour").value = S.colour; refreshAll();
      $("exmsg").className = "sub"; $("exmsg").textContent = `added ${S.colour}`;
    } catch (err) { $("exmsg").className = "err"; $("exmsg").textContent = err.message; }
  });
  $("addagg").addEventListener("click", () => {
    try {
      const n = addAgg($("aggmetric").value, $("aggdir").value, $("aggop").value);
      S.colour = n; $("colour").value = n; refreshAll();
      $("exmsg").className = "sub"; $("exmsg").textContent = `added ${n}`;
    } catch (err) { $("exmsg").className = "err"; $("exmsg").textContent = err.message; }
  });
  S.hops = 1; S.edgeMode = "";
  $("dplane").innerHTML = S.order.map((p) => `<option value="${p}"${p === "lut" ? " selected" : ""}>${p}</option>`).join("");
  $("brushplane").innerHTML = S.order.map((p) => `<option value="${p}"${p === "placed" ? " selected" : ""}>${p}</option>`).join("");
  $("viewmode").innerHTML = ["stack", ...S.order].map((p) => `<option value="${p}">${p === "stack" ? "3D stack" : "2D: " + p}</option>`).join("");
  $("viewmode").addEventListener("change", (e) => setView(e.target.value));
  $("dgo").addEventListener("click", discover);
  $("grouping").addEventListener("change", (e) => setGroupMode(e.target.value));
  $("edgemode").addEventListener("change", async (e) => { S.edgeMode = e.target.value; if (S.edgeMode) await ensureEdges(); drawEdges(); });
  $("hops").addEventListener("change", (e) => { S.hops = Number(e.target.value); drawEdges(); });
  const pairs = S.order.slice(0, -1).map((p, k) => `<option value="${k}">${p} to ${S.order[k + 1]}</option>`).join("");
  $("morphpair").innerHTML = pairs;
  const setMorph = () => { const k = Number($("morphpair").value); S.morph = { a: S.order[k], b: S.order[k + 1], m: Number($("morph").value) }; refreshAll(); };
  $("morph").addEventListener("input", setMorph);
  $("morphpair").addEventListener("change", () => { $("morph").value = "0"; setMorph(); });
  $("rotate").addEventListener("change", (e) => { controls.autoRotate = e.target.checked; });
  controls.autoRotate = $("rotate").checked;
  $("gap").addEventListener("input", (e) => { S.gap = Number(e.target.value); layout(); resetCamera(); });
  $("reset").addEventListener("click", resetCamera);
  $("clear").addEventListener("click", clearSel);
  $("planes").innerHTML = S.order.map((p, k) =>
    `<div class="prow"><input type="checkbox" data-p="${p}" checked style="width:auto"><b style="color:var(--fg);flex:0 0 52px">${k + 1} ${p}</b>` +
    `<button data-f="${p}">focus</button><button data-s="${p}">solo</button></div>` +
    `<label class="row">opacity<input type="range" data-o="${p}" min="0" max="1" step="0.05" value="0.12"></label>`).join("");
  $("planes").querySelectorAll("input[data-p]").forEach((c) => c.addEventListener("change", () => {
    S.vis[c.dataset.p] = c.checked; S.solo = null;
    applyVisibility();
  }));
  $("planes").querySelectorAll("button[data-f]").forEach((b) => b.addEventListener("click", () => focusPlane(b.dataset.f)));
  $("planes").querySelectorAll("button[data-s]").forEach((b) => b.addEventListener("click", () => soloPlane(b.dataset.s)));
  $("planes").querySelectorAll("input[data-o]").forEach((c) => c.addEventListener("input", () => {
    quads[c.dataset.o].q.material.opacity = Number(c.value);
  }));
  $("depthpreset").addEventListener("click", () => setColour("logic_level"));
  buildPathsUi();
  document.addEventListener("keydown", (e) => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "0") focusPlane(null);
    else if (/^[1-9]$/.test(e.key) && S.order[Number(e.key) - 1]) focusPlane(S.order[Number(e.key) - 1]);
  });
  $("view").addEventListener("wheel", wheelZoom, { passive: false });
  $("title").textContent = S.man.benchmark;
  $("subtitle").textContent = `${S.man.flow} flow, top ${S.man.top}; planes ${S.order.join(" > ")}`;
  const c = S.man.counts;
  $("status").textContent = `${S.order.map((p) => `${p} ${c[p]}`).join(", ")}; ${S.man.links} links; ` +
    `${S.man.unanchored} placed by fallback; not in this bundle: ${S.man.missing_planes.join(", ")}`;
  const cv = $("view"), tip = $("tip"), box = $("brush");
  let down = null, brushing = false;
  cv.addEventListener("pointerdown", (e) => {
    down = [e.clientX, e.clientY];
    brushing = e.shiftKey;
    if (brushing) { controls.enabled = false; box.style.display = "block"; }
  });
  cv.addEventListener("pointerup", (e) => {
    controls.enabled = true; box.style.display = "none";
    if (!down) return;
    if (brushing) { brushing = false; brushSelect(down[0], down[1], e.clientX, e.clientY); return; }
    if (Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const h = pick(e);
    if (h?.blob) {
      if (S.group.expanded.has(h.blob.key)) S.group.expanded.delete(h.blob.key); else S.group.expanded.add(h.blob.key);
      refreshAll();
    } else if (h?.id) select(h.id); else clearSel();
  });
  cv.addEventListener("pointermove", (e) => {
    if (brushing && down) {
      const r = $("stage").getBoundingClientRect();
      Object.assign(box.style, { left: Math.min(down[0], e.clientX) - r.left + "px", top: Math.min(down[1], e.clientY) - r.top + "px",
        width: Math.abs(e.clientX - down[0]) + "px", height: Math.abs(e.clientY - down[1]) + "px" });
      return;
    }
    const h = pick(e), r = $("stage").getBoundingClientRect();
    const text = h?.id ?? (h?.blob ? `${h.plane}: ${h.blob.key} (${h.blob.members.length} objects, click to expand)` : null);
    tip.style.display = text ? "block" : "none";
    if (text) { tip.textContent = text; tip.style.left = e.clientX - r.left + 12 + "px"; tip.style.top = e.clientY - r.top + 12 + "px"; }
  });
}

async function main() {
  await loadBundle();
  buildScene();
  buildUi();
  new ResizeObserver(resize).observe($("stage"));
  resize();
  buildSource();
  refreshAll();
  const loop = () => { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); };
  loop();
  document.body.dataset.ready = "1";
  window.__o3viz = { S, select, selectLines, planeCounts, coverage, focusPlane, soloPlane, showPath, updateCone, markLines, setCone: async (dir, depth) => { $("pathsrc").value = "cone"; showPathPanel(); S.coneOn = true; $("conedir").value = dir; $("conedepth").value = String(depth); await updateCone(); markLines(); }, marksOf: () => Object.fromEntries([...marks].map(([f, m]) => [f, Object.fromEntries(m)])), cam: () => ({ target: controls.target.toArray(), pos: camera.position.toArray() }), wheelAt: (x, y, dy) => wheelZoom({ preventDefault() {}, clientX: x, clientY: y, deltaY: dy, deltaMode: 0 }), discover, setView, setGroupMode, discoverMatrix, brushAll: (p) => { S.brush = new Set(S.planes[p].ids.slice(0, 30)); S.core = new Set(); refreshAll(); },
    setEdges: async (m, h) => { S.edgeMode = m; S.hops = h ?? 1; await ensureEdges(); drawEdges(); }, setMorph: (a, b, m) => { S.morph = { a, b, m }; refreshAll(); }, addExpr, addAgg, setHeight: (n) => { S.height = n; $("height").value = n; refreshAll(); },
    setAnchor: async (n) => { $("anchor").value = n; $("anchor").dispatchEvent(new Event("change")); }, setColour,
    setSize: (n) => { S.size = n; $("size").value = n; refreshAll(); }, stop: () => { controls.autoRotate = false; } };
}
window.addEventListener("error", (e) => { $("status").className = "err"; $("status").textContent = String(e.message); });
main().catch((e) => { $("subtitle").textContent = "failed to load"; $("status").className = "err"; $("status").textContent = String(e); console.error(e); });
