#!/usr/bin/env node
/**
 * P1d: build the SPA chunk dependency graph.
 *  - static edges:  import ... from "./x.js" / import "./x.js"
 *  - dynamic edges: import("./x.js")  -> these are the route-level lazy chunks
 *  - output: chunk fan-in/fan-out, which chunks are dynamic-only (lazy),
 *    and the "route -> lazy chunk" mapping recovered from route objects.
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ION = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/app/resources/ion-dist/assets/v1';
const OUT = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';

const files = fs.readdirSync(ION).filter(f => f.endsWith('.js'));

function walkNode(node, visit) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) { for (const n of node) walkNode(n, visit); return; }
  if (typeof node.type !== 'string') return;
  visit(node);
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'start' || k === 'end') continue;
    const v = node[k];
    if (v && typeof v === 'object') walkNode(v, visit);
  }
}

const edges = [];       // [from, to, kind]
const fanout = {};
const fanin = {};
const lazyOnly = new Set();
let parseFail = 0;

for (const f of files) {
  const src = fs.readFileSync(path.join(ION, f), 'utf8');
  let ast;
  try {
    ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowHashBang: true, allowReturnOutsideFunction: true });
  } catch {
    try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', allowHashBang: true, allowReturnOutsideFunction: true }); }
    catch { parseFail++; continue; }
  }
  let out = 0;
  walkNode(ast, (n) => {
    if (n.type === 'ImportDeclaration' && n.source && typeof n.source.value === 'string') {
      const t = path.basename(n.source.value);
      edges.push([f, t, 'static']); out++;
      fanin[t] = (fanin[t] || 0) + 1;
    } else if (n.type === 'ExportNamedDeclaration' && n.source && typeof n.source.value === 'string') {
      const t = path.basename(n.source.value);
      edges.push([f, t, 'reexport']); out++;
      fanin[t] = (fanin[t] || 0) + 1;
    } else if (n.type === 'ImportExpression' && n.source && n.source.type === 'Literal') {
      const t = path.basename(String(n.source.value));
      edges.push([f, t, 'dynamic']); out++;
      fanin[t] = (fanin[t] || 0) + 1;
      lazyOnly.add(t);
    } else if (n.type === 'CallExpression' && n.callee && n.callee.type === 'Import') {
      const a = n.arguments[0];
      if (a && a.type === 'Literal') {
        const t = path.basename(String(a.value));
        edges.push([f, t, 'dynamic']); out++;
        fanin[t] = (fanin[t] || 0) + 1;
        lazyOnly.add(t);
      }
    }
  });
  fanout[f] = out;
}

const w = (n, h, rows) => fs.writeFileSync(path.join(OUT, n),
  [h, ...rows.map(r => r.map(x => String(x)).join('\t'))].join('\n') + '\n', 'utf8');

w('ION-CHUNK-EDGES.tsv', ['from', 'to', 'kind'], edges);
const stats = files.map(f => [f, fs.statSync(path.join(ION, f)).size, fanin[f] || 0, fanout[f] || 0,
  lazyOnly.has(f) ? 'LAZY' : 'eager']);
stats.sort((a, b) => (b[2] + b[3]) - (a[2] + a[3]));
w('ION-CHUNK-STATS.tsv', ['chunk', 'bytes', 'fan_in', 'fan_out', 'load_mode'], stats);

const kinds = {};
for (const e of edges) kinds[e[2]] = (kinds[e[2]] || 0) + 1;
console.log(JSON.stringify({
  chunks: files.length, parse_fail: parseFail,
  edges: edges.length, edge_kinds: kinds,
  lazy_chunks: lazyOnly.size,
  eager_chunks: files.length - lazyOnly.size,
  top_fan_in: stats.slice(0, 12).map(x => x[0] + '(' + x[2] + ')'),
}, null, 2));
