#!/usr/bin/env node
/**
 * P1B: index the bundled first-party SPA (ion-dist), which P0/P1 had bucketed
 * as "resources". 3,554 JS files, ~156 MB.
 *
 * Emits: ION-MODULES.tsv, ION-ROUTES.tsv, ION-BRIDGE.tsv, ION-WASM.tsv
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ION = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/app/resources/ion-dist';
const OUT = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';

const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (/\.(js|mjs)$/i.test(e.name)) files.push(p);
  }
})(ION);
files.sort();

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

const modRows = [], routeRows = [], bridgeRows = [], wasmRows = [];
let ok = 0, fail = 0, totalBytes = 0;

for (const f of files) {
  const rel = path.relative(ION, f).replace(/\\/g, '/');
  const src = fs.readFileSync(f, 'utf8');
  const bytes = Buffer.byteLength(src);
  totalBytes += bytes;
  let ast = null;
  try {
    ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'module', allowReturnOutsideFunction: true, allowHashBang: true });
  } catch {
    try { ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true, allowHashBang: true }); }
    catch { fail++; }
  }
  if (ast) ok++;

  const imports = [], fns = [], classes = [];
  const routeLits = new Set(), bridgeHits = new Set();
  if (ast) {
    walkNode(ast, (n) => {
      if (n.type === 'ImportDeclaration' && n.source) imports.push(n.source.value);
      else if (n.type === 'FunctionDeclaration' && n.id) fns.push(n.id.name);
      else if (n.type === 'ClassDeclaration' && n.id) classes.push(n.id.name);
      else if (n.type === 'Literal' && typeof n.value === 'string') {
        const v = n.value;
        // SPA routes look like "/settings/..." or "/new"
        if (/^\/[a-z0-9][a-z0-9-]{1,40}(\/[a-z0-9:_-]{1,40})*$/.test(v) && v.length < 70) routeLits.add(v);
      }
      // bridge: window.<world> usage or eipc dispatch
      if (n.type === 'MemberExpression' && n.object.type === 'Identifier' && n.property.name) {
        const o = n.object.name, p = n.property.name;
        if (/^(claude|desktop|cowork|buddy|electron|claudeApp|claudeDesktop)/i.test(o + p) && p.length > 3) bridgeHits.add(o + '.' + p);
      }
    });
  }
  modRows.push([rel, bytes, ast ? 'ok' : 'FAIL', imports.length, fns.length, classes.length,
    imports.slice(0, 8).join(' | ')]);
  for (const r of routeLits) routeRows.push([rel, r]);
  for (const b of bridgeHits) bridgeRows.push([rel, b]);
}

// wasm inventory
(function walk2(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk2(p);
    else if (/\.wasm$/i.test(e.name)) {
      const b = fs.readFileSync(p);
      wasmRows.push([path.relative(ION, p).replace(/\\/g, '/'), b.length,
        b.slice(0, 4).toString('hex')]);
    }
  }
})(ION);

const w = (n, h, rows) => fs.writeFileSync(path.join(OUT, n),
  [h, ...rows.map(r => r.map(x => String(x).replace(/[\r\n\t]/g, ' ')).join('\t'))].join('\n') + '\n', 'utf8');
w('ION-MODULES.tsv', ['path', 'bytes', 'parse', 'imports', 'functions', 'classes', 'sample_imports'], modRows);
w('ION-ROUTES.tsv', ['path', 'route_literal'], [...new Map(routeRows.map(r => [r[1], r])).values()]);
w('ION-BRIDGE.tsv', ['path', 'bridge_symbol'], bridgeRows);
w('ION-WASM.tsv', ['path', 'bytes', 'magic_hex'], wasmRows);

console.log(JSON.stringify({
  files: files.length, parsed_ok: ok, parse_fail: fail,
  total_js_bytes: totalBytes,
  unique_route_literals: new Set(routeRows.map(r => r[1])).size,
  bridge_symbols: new Set(bridgeRows.map(r => r[1])).size,
  wasm_files: wasmRows.length,
}, null, 2));
