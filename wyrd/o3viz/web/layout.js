// Collapsible side panels of the o3viz viewer (pure state; the DOM part is in app.js).
export const PANELS = ["left", "hdl", "right"];
export const KEYS = { "[": "left", h: "hdl", "]": "right" };
const KEY = "o3viz.panels";

// stored: JSON text or null/garbage -> {left, hdl, right} booleans, true = collapsed
export function parseState(stored) {
  let raw = {};
  try { raw = JSON.parse(stored ?? "{}") ?? {}; } catch { raw = {}; }
  return Object.fromEntries(PANELS.map((p) => [p, raw[p] === true]));
}
export const toggled = (state, name) => (PANELS.includes(name) ? { ...state, [name]: !state[name] } : state);
// the key (without modifiers, outside inputs) -> panel name or null
export const panelForKey = (key) => KEYS[key] ?? null;
// CSS grid columns of #app: left strip or 230px, the main area, right strip or 320px
export const gridColumns = (state) => `${state.left ? "26px" : "230px"} minmax(0,1fr) ${state.right ? "26px" : "320px"}`;
export const load = (storage) => parseState(storage?.getItem(KEY));
export const save = (storage, state) => storage?.setItem(KEY, JSON.stringify(state));
