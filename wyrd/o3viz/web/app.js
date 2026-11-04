// o3viz viewer: one benchmark as a stack of planes (three.js, vendored, no network).
import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";

const BUNDLE = "./bundle/";
const GREY = new THREE.Color("#5b6572");
const BG = new THREE.Color("#14171c");
const SEQ = ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"].map((c) => new THREE.Color(c));
const DIV = ["#d7301f", "#f7f7f7", "#2166ac"].map((c) => new THREE.Color(c));
const $ = (id) => document.getElementById(id);

const S = { man: null, planes: {}, order: [], links: [], up: new Map(), down: new Map(), pos: {},
  bounds: [0, 0, 1, 1], colour: "", size: "", sel: null, core: new Set(), gap: 6, byId: new Map(), ranges: {} };

async function getJson(path) {
  const r = await fetch(BUNDLE + path);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

export async function loadBundle() {
  S.man = await getJson("manifest.json");
  S.order = S.man.planes;
  for (const p of S.order) S.planes[p] = await getJson(`planes/${p}.json`);
  S.links = await getJson("links.json");
  for (const [a, b] of S.links) {
    (S.down.get(a) ?? S.down.set(a, []).get(a)).push(b);
    (S.up.get(b) ?? S.up.set(b, []).get(b)).push(a);
  }
  for (const p of S.order) S.planes[p].ids.forEach((id, i) => S.byId.set(id, { plane: p, i }));
  await loadAnchor(S.man.anchors[0]);
}

async function loadAnchor(name) {
  const a = await getJson(`anchors/${name}.json`);
  S.pos = a.pos;
  S.bounds = a.bounds;
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
const worldPos = (plane, id) => {
  const k = S.order.indexOf(plane), p = S.pos[plane][id];
  return new THREE.Vector3(p[0] - cx(), planeY(k), p[1] - cz());
};

function geometryFor(plane) {
  if (plane === "hdl") return new THREE.OctahedronGeometry(0.26);
  if (plane === "clb") return new THREE.BoxGeometry(0.34, 0.34, 0.34);
  return new THREE.SphereGeometry(plane === "placed" ? 0.13 : 0.18, 10, 8);
}

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
  camera = new THREE.PerspectiveCamera(40, 1, 0.1, 500);
  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.autoRotateSpeed = 1.2;
  group = new THREE.Group();
  scene.add(group);
  raycaster = new THREE.Raycaster();
  const W = S.bounds[2] - S.bounds[0], H = S.bounds[3] - S.bounds[1];
  S.order.forEach((p) => {
    const d = S.planes[p];
    const m = new THREE.InstancedMesh(geometryFor(p), new THREE.MeshBasicMaterial(), d.ids.length);
    m.instanceColor = new THREE.InstancedBufferAttribute(new Float32Array(d.ids.length * 3), 3);
    m.userData.plane = p;
    meshes[p] = m;
    group.add(m);
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
  if (!S.sel) return 0;
  if (id === S.sel) return 2;
  return S.core.has(id) ? 1 : -1;
}

function refreshPlane(p) {
  const d = S.planes[p], m = meshes[p], k = S.order.indexOf(p);
  const col = S.colour ? d.metrics[S.colour] : null;
  const sz = S.size ? d.metrics[S.size] : null;
  const [slo, shi] = S.size ? metricRange(S.size) : [0, 1];
  d.ids.forEach((id, i) => {
    const pos = S.pos[p][id];
    dummy.position.set(pos[0] - cx(), planeY(k), pos[1] - cz());
    let s = 1;
    if (sz) s = sz[i] === null ? 0.5 : 0.6 + 1.8 * ((sz[i] - slo) / (shi - slo));
    const st = stateOf(id);
    if (st === 2) s *= 2.4; else if (st === 1) s *= 1.5; else if (st === -1) s *= 0.55;
    dummy.scale.setScalar(s);
    dummy.updateMatrix();
    m.setMatrixAt(i, dummy.matrix);
    let c = col ? colourOf(S.colour, col[i]) : new THREE.Color("#8fc1ff");
    if (st === 2) c = new THREE.Color("#ffb454");
    else if (st === -1) c.lerp(BG, 0.82);
    m.setColorAt(i, c);
  });
  m.instanceMatrix.needsUpdate = true;
  m.instanceColor.needsUpdate = true;
  m.computeBoundingSphere();
}
const refreshAll = () => { S.order.forEach(refreshPlane); drawLines(); legend(); };

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
  S.core = new Set([...closure(id, "up"), ...closure(id, "down")]);
  refreshAll();
  showSelection();
}
function clearSel() { S.sel = null; S.core = new Set(); refreshAll(); $("sel").textContent = "Click a node."; $("sel").className = "sub"; }

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

function spanLines(span) {
  const m = /^(\d+)\.\d+-(\d+)\.\d+$/.exec(span);
  return m ? [Number(m[1]), Number(m[2])] : null;
}
const srcCache = {};
async function snippet(file, span) {
  const ls = spanLines(span);
  if (!ls) return "";
  srcCache[file] ??= await fetch(BUNDLE + "hdl/" + file).then((r) => (r.ok ? r.text() : "")).then((t) => t.split("\n"));
  const lines = srcCache[file];
  if (!lines.length || lines.length === 1 && !lines[0]) return `<div class="sub">${esc(file)} not in the bundle</div>`;
  const a = Math.max(1, ls[0] - 1), b = Math.min(lines.length, Math.min(ls[1], ls[0] + 12) + 1);
  let out = `<div class="sub">${esc(file)}:${esc(span)}</div><pre>`;
  for (let n = a; n <= b; n++) {
    const hit = n >= ls[0] && n <= ls[1];
    out += `<span class="${hit ? "hit" : ""}">${String(n).padStart(4)}  ${esc(lines[n - 1] ?? "")}</span>\n`;
  }
  return out + "</pre>";
}

async function showSelection() {
  const id = S.sel, { plane, i } = S.byId.get(id);
  let html = `<table>${infoRows(id)}</table><h2>Column (${S.core.size} linked objects)</h2><div class="col">`;
  for (const p of S.order) {
    const ids = [...S.core].filter((x) => S.byId.get(x).plane === p).sort();
    if (p === plane) html += `<div><b>${p}</b>: ${esc(id)}</div>`;
    else if (ids.length) {
      const shown = ids.slice(0, 24).map((x) => `<a data-id="${esc(x)}">${esc(S.planes[p].name[S.byId.get(x).i])}</a>`);
      html += `<div><b>${p}</b> (${ids.length}): ${shown.join(", ")}${ids.length > 24 ? ", ..." : ""}</div>`;
    }
  }
  html += "</div><h2>HDL</h2>";
  let src = S.planes[plane].src[i][0];
  if (!src) {
    const hd = [...S.core].map((x) => S.byId.get(x)).filter((o) => o.plane === "hdl" || S.planes[o.plane].src[o.i].length);
    hd.sort((a, b) => (S.planes[a.plane].metrics.span_lines?.[a.i] ?? 1e9) - (S.planes[b.plane].metrics.span_lines?.[b.i] ?? 1e9));
    src = hd.length ? S.planes[hd[0].plane].src[hd[0].i][0] : null;
  }
  $("sel").className = "";
  $("sel").innerHTML = html + (src ? await snippet(src[0], src[1]) : '<div class="sub">no HDL span in the chain</div>');
  $("sel").querySelectorAll("a[data-id]").forEach((a) => a.addEventListener("click", () => select(a.dataset.id)));
}

// ---- picking ----
function pick(ev) {
  const r = $("view").getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1), camera);
  let best = null;
  for (const p of S.order) {
    if (!meshes[p].visible) continue;
    const hit = raycaster.intersectObject(meshes[p])[0];
    if (hit && (!best || hit.distance < best.distance)) best = { distance: hit.distance, id: S.planes[p].ids[hit.instanceId] };
  }
  return best?.id ?? null;
}

// ---- UI ----
function fillSelect(sel, names, withNone) {
  sel.innerHTML = (withNone ? '<option value="">(none)</option>' : "") +
    names.map((n) => `<option value="${n}">${n}${meta(n) ? "  [" + meta(n).unit + "]" : ""}</option>`).join("");
}
function legend() {
  const name = S.colour;
  $("legend").style.display = name ? "block" : "none";
  if (!name) return;
  const [lo, hi] = metricRange(name), div = meta(name).scale === "div";
  const stops = div ? DIV : SEQ;
  $("bar").style.background = `linear-gradient(90deg, ${stops.map((c) => "#" + c.getHexString()).join(",")})`;
  const m = Math.max(Math.abs(lo), Math.abs(hi));
  $("lo").textContent = div ? fmt(-m) : fmt(lo);
  $("hi").textContent = div ? fmt(m) : fmt(hi);
  $("mid").textContent = div ? "0" : "";
  $("unit").textContent = `${meta(name).unit}; grey = not measured. ${meta(name).measurer}`;
}

function buildUi() {
  const names = S.man.metrics.map((m) => m.name);
  fillSelect($("colour"), names, true);
  fillSelect($("size"), names, true);
  $("colour").addEventListener("change", (e) => { S.colour = e.target.value; refreshAll(); });
  $("size").addEventListener("change", (e) => { S.size = e.target.value; refreshAll(); });
  $("anchor").innerHTML = S.man.anchors.map((a) => `<option>${a}</option>`).join("");
  $("anchor").addEventListener("change", async (e) => { await loadAnchor(e.target.value); refreshAll(); });
  $("rotate").addEventListener("change", (e) => { controls.autoRotate = e.target.checked; });
  controls.autoRotate = $("rotate").checked;
  $("gap").addEventListener("input", (e) => { S.gap = Number(e.target.value); layout(); resetCamera(); });
  $("reset").addEventListener("click", resetCamera);
  $("clear").addEventListener("click", clearSel);
  $("planes").innerHTML = S.order.map((p) =>
    `<label class="row"><input type="checkbox" data-p="${p}" checked> ${p}<input type="range" data-o="${p}" min="0" max="1" step="0.05" value="0.12"></label>`).join("");
  $("planes").querySelectorAll("input[data-p]").forEach((c) => c.addEventListener("change", () => {
    const p = c.dataset.p, v = c.checked;
    meshes[p].visible = quads[p].q.visible = quads[p].edge.visible = quads[p].lab.visible = v;
  }));
  $("planes").querySelectorAll("input[data-o]").forEach((c) => c.addEventListener("input", () => {
    quads[c.dataset.o].q.material.opacity = Number(c.value);
  }));
  $("title").textContent = S.man.benchmark;
  $("subtitle").textContent = `${S.man.flow} flow, top ${S.man.top}; planes ${S.order.join(" > ")}`;
  const c = S.man.counts;
  $("status").textContent = `${S.order.map((p) => `${p} ${c[p]}`).join(", ")}; ${S.man.links} links; ` +
    `${S.man.unanchored} placed by fallback; not in this bundle: ${S.man.missing_planes.join(", ")}`;
  const cv = $("view"), tip = $("tip");
  let down = null;
  cv.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  cv.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
    const id = pick(e);
    if (id) select(id); else clearSel();
  });
  cv.addEventListener("pointermove", (e) => {
    const id = pick(e), r = $("stage").getBoundingClientRect();
    tip.style.display = id ? "block" : "none";
    if (id) { tip.textContent = id; tip.style.left = e.clientX - r.left + 12 + "px"; tip.style.top = e.clientY - r.top + 12 + "px"; }
  });
}

async function main() {
  await loadBundle();
  buildScene();
  buildUi();
  window.addEventListener("resize", resize);
  resize();
  refreshAll();
  const loop = () => { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); };
  loop();
  document.body.dataset.ready = "1";
  window.__o3viz = { S, select, setColour: (n) => { S.colour = n; $("colour").value = n; refreshAll(); },
    setSize: (n) => { S.size = n; $("size").value = n; refreshAll(); }, stop: () => { controls.autoRotate = false; } };
}
window.addEventListener("error", (e) => { $("status").className = "err"; $("status").textContent = String(e.message); });
main().catch((e) => { $("subtitle").textContent = "failed to load"; $("status").className = "err"; $("status").textContent = String(e); console.error(e); });
