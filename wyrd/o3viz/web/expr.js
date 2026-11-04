// A small safe expression language for derived metrics: numbers, metric names, + - * / % ^,
// comparisons, and a fixed set of functions. No eval, no property access, no assignment.
// A missing value (null) makes the result null; division by zero and domain errors give null.

const FUNCS = {
  abs: [1, Math.abs], sqrt: [1, Math.sqrt], log: [1, Math.log], log2: [1, Math.log2], exp: [1, Math.exp],
  floor: [1, Math.floor], ceil: [1, Math.ceil], round: [1, Math.round],
  min: [2, Math.min], max: [2, Math.max], pow: [2, Math.pow],
  clamp: [3, (x, lo, hi) => Math.min(Math.max(x, lo), hi)],
  if: [3, (c, a, b) => (c ? a : b)],
};

export function tokenize(text) {
  const out = [];
  const re = /\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|([A-Za-z_][A-Za-z0-9_]*)|(<=|>=|==|!=|[-+*/%^(),<>]))/y;
  let pos = 0;
  while (pos < text.length) {
    re.lastIndex = pos;
    const m = re.exec(text);
    if (!m) {
      if (/^\s*$/.test(text.slice(pos))) break;
      throw new Error(`unexpected character at ${pos + 1}: "${text[pos]}"`);
    }
    pos = re.lastIndex;
    if (m[1] !== undefined) out.push({ t: "num", v: Number(m[1]) });
    else if (m[2] !== undefined) out.push({ t: "id", v: m[2] });
    else out.push({ t: "op", v: m[3] });
  }
  return out;
}

export function parse(text) {
  const toks = tokenize(text);
  let i = 0;
  const peek = () => toks[i];
  const isOp = (...ops) => peek() && peek().t === "op" && ops.includes(peek().v);
  const eat = (v) => {
    if (!isOp(v)) throw new Error(`expected "${v}"`);
    i++;
  };
  function cmp() {
    let l = add();
    while (isOp("<", ">", "<=", ">=", "==", "!=")) { const op = toks[i++].v; l = { k: "bin", op, l, r: add() }; }
    return l;
  }
  function add() {
    let l = mul();
    while (isOp("+", "-")) { const op = toks[i++].v; l = { k: "bin", op, l, r: mul() }; }
    return l;
  }
  function mul() {
    let l = unary();
    while (isOp("*", "/", "%")) { const op = toks[i++].v; l = { k: "bin", op, l, r: unary() }; }
    return l;
  }
  function unary() {
    if (isOp("-", "+")) { const op = toks[i++].v; return { k: "un", op, a: unary() }; }
    return pow();
  }
  function pow() {
    const base = atom();
    if (isOp("^")) { i++; return { k: "bin", op: "^", l: base, r: unary() }; }
    return base;
  }
  function atom() {
    const t = toks[i++];
    if (!t) throw new Error("unexpected end");
    if (t.t === "num") return { k: "num", v: t.v };
    if (t.t === "id") {
      if (isOp("(")) {
        i++;
        const args = [];
        if (!isOp(")")) { args.push(cmp()); while (isOp(",")) { i++; args.push(cmp()); } }
        eat(")");
        const f = FUNCS[t.v];
        if (!f) throw new Error(`unknown function ${t.v}`);
        if (f[0] !== args.length) throw new Error(`${t.v} takes ${f[0]} arguments`);
        return { k: "call", name: t.v, args };
      }
      return { k: "var", name: t.v };
    }
    if (t.v === "(") { const e = cmp(); eat(")"); return e; }
    throw new Error(`unexpected "${t.v}"`);
  }
  const ast = cmp();
  if (i < toks.length) throw new Error(`unexpected "${toks[i].v}"`);
  return ast;
}

export function varsOf(ast, acc = new Set()) {
  if (ast.k === "var") acc.add(ast.name);
  else if (ast.k === "bin") { varsOf(ast.l, acc); varsOf(ast.r, acc); }
  else if (ast.k === "un") varsOf(ast.a, acc);
  else if (ast.k === "call") ast.args.forEach((a) => varsOf(a, acc));
  return acc;
}

const BIN = {
  "+": (a, b) => a + b, "-": (a, b) => a - b, "*": (a, b) => a * b, "/": (a, b) => (b === 0 ? null : a / b),
  "%": (a, b) => (b === 0 ? null : a % b), "^": Math.pow,
  "<": (a, b) => +(a < b), ">": (a, b) => +(a > b), "<=": (a, b) => +(a <= b), ">=": (a, b) => +(a >= b),
  "==": (a, b) => +(a === b), "!=": (a, b) => +(a !== b),
};

// get(name) returns a number or null.
export function evaluate(ast, get) {
  const v = ev(ast, get);
  return v === null || !Number.isFinite(v) ? null : v;
}
function ev(n, get) {
  if (n.k === "num") return n.v;
  if (n.k === "var") return get(n.name);
  if (n.k === "un") { const a = ev(n.a, get); return a === null ? null : n.op === "-" ? -a : a; }
  if (n.k === "bin") {
    const a = ev(n.l, get), b = ev(n.r, get);
    if (a === null || b === null) return null;
    return BIN[n.op](a, b);
  }
  const args = n.args.map((x) => ev(x, get));
  if (args.some((x) => x === null)) return null;
  return FUNCS[n.name][1](...args);
}
