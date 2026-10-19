#!/usr/bin/env node
/**
 * P1 static indexer.
 * Parses every JS/MJS/TS file inside the extracted ASAR with acorn (module, ES2023),
 * and emits:
 *   MODULES.tsv      one row per parsed file: size, parse status, top-level shape
 *   SYMBOLS.tsv      functions/classes/registrations with line:col
 *   CALL-EDGES.tsv   intra-file + require/import edges
 *   DYNAMIC-IMPORTS.tsv  import()/require() with non-literal or computed targets
 *   IPC-SIGNALS.tsv  ipcMain.handle/on/once, ipcRenderer.invoke/send/on, exposeInMainWorld, webContents.send
 */
const fs = require('fs');
const path = require('path');
const acorn = require('acorn');

const ASAR = process.argv[2] || 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar';
const OUT = process.argv[3] || 'D:/Atlas/_research/claude-desktop/2026-10-20/index';

const exts = new Set(['.js', '.mjs', '.cjs', '.ts']);
const files = [];
(function walk(d) {
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (exts.has(path.extname(e.name).toLowerCase())) files.push(p);
  }
})(ASAR);
files.sort();

const w = (n, h, rows) => {
  const fp = path.join(OUT, n);
  fs.writeFileSync(fp, [h, ...rows.map(r => r.join('\t'))].join('\n') + '\n', 'utf8');
  console.log(n, rows.length);
};

const modules = [], symbols = [], edges = [], dyn = [], ipc = [];
let parseFail = 0;

function walkNode(node, visit, depth = 0) {
  if (!node || typeof node !== 'object') return;
  if (Array.isArray(node)) { for (const n of node) walkNode(n, visit, depth); return; }
  if (typeof node.type !== 'string') return;
  visit(node);
  for (const k of Object.keys(node)) {
    if (k === 'loc' || k === 'range' || k === 'start' || k === 'end') continue;
    const v = node[k];
    if (v && typeof v === 'object') walkNode(v, visit, depth + 1);
  }
}

const lineCol = (src, pos) => {
  let line = 1, last = 0;
  for (let i = 0; i < pos && i < src.length; i++) if (src.charCodeAt(i) === 10) { line++; last = i + 1; }
  return [line, pos - last + 1];
};

for (const f of files) {
  const rel = path.relative(ASAR, f).replace(/\\/g, '/');
  const src = fs.readFileSync(f, 'utf8');
  const bytes = fs.statSync(f).size;
  const mid = 'M-' + String(modules.length).padStart(5, '0');
  let ast = null, err = '';
  try {
    ast = acorn.parse(src, {
      ecmaVersion: 'latest', sourceType: 'module', allowReturnOutsideFunction: true,
      allowAwaitOutsideFunction: true, allowHashBang: true, locations: false,
    });
  } catch (e) {
    try {
      ast = acorn.parse(src, {
        ecmaVersion: 'latest', sourceType: 'script', allowReturnOutsideFunction: true,
        allowAwaitOutsideFunction: true, allowHashBang: true,
      });
    } catch (e2) { err = String(e2.message).slice(0, 160); parseFail++; }
  }

  const imports = [], exportsN = [], fns = [], classes = [], dynHere = [];
  if (ast) {
    walkNode(ast, (n) => {
      if (n.type === 'ImportDeclaration') {
        const s = n.source && n.source.value;
        imports.push(s);
        const names = n.specifiers.map(sp => sp.imported ? (sp.imported.name || sp.imported.value) : (sp.local && sp.local.name)).join(',');
        edges.push([mid, rel, 'imports', s, names]);
      } else if (n.type === 'ExportNamedDeclaration' && n.declaration) {
        const d = n.declaration;
        if (d.id && d.id.name) exportsN.push(d.id.name);
      } else if (n.type === 'ExportDefaultDeclaration') {
        exportsN.push('default');
      } else if (n.type === 'FunctionDeclaration' && n.id) {
        const [l, c] = lineCol(src, n.start);
        fns.push([n.id.name, l, c, n.params.length, n.async ? 'async' : '', n.generator ? 'generator' : '']);
      } else if (n.type === 'ClassDeclaration' && n.id) {
        const [l, c] = lineCol(src, n.start);
        classes.push([n.id.name, l, c]);
      } else if (n.type === 'CallExpression') {
        const cal = n.callee;
        const cname = cal && cal.type === 'Identifier' ? cal.name
          : cal && cal.type === 'MemberExpression' ? memberPath(cal) : '';
        if (cname === 'require' && n.arguments[0]) {
          const a = n.arguments[0];
          if (a.type === 'Literal') edges.push([mid, rel, 'requires', String(a.value), '']);
          else dynHere.push(['require', lineCol(src, n.start).join(':'), a.type]);
        }
        if ((cal && cal.type === 'Import') || cname === 'import') {
          const a = n.arguments[0];
          if (a && a.type === 'Literal') edges.push([mid, rel, 'dynamic-import', String(a.value), '']);
          else dynHere.push(['import()', lineCol(src, n.start).join(':'), a ? a.type : 'none']);
        }
        // IPC-ish signals
        if (/^(ipcMain|ipcRenderer)\.(handle|handleOnce|on|once|send|sendSync|invoke|postMessage)$/.test(cname)) {
          const a = n.arguments[0];
          const ch = a && a.type === 'Literal' ? String(a.value) : (a ? '<' + a.type + '>' : '');
          const [l, c] = lineCol(src, n.start);
          ipc.push([rel, l, c, cname, ch, a && a.type === 'Literal' ? 'literal' : 'computed']);
        }
        if (/webContents\.(send|postMessage)$/.test(cname)) {
          const a = n.arguments[0];
          const ch = a && a.type === 'Literal' ? String(a.value) : (a ? '<' + a.type + '>' : '');
          const [l, c] = lineCol(src, n.start);
          ipc.push([rel, l, c, 'webContents.' + cname.split('.').pop(), ch, a && a.type === 'Literal' ? 'literal' : 'computed']);
        }
        if (/^contextBridge\.exposeInMainWorld$/.test(cname)) {
          const a = n.arguments[0];
          const key = a && a.type === 'Literal' ? String(a.value) : '<computed>';
          const [l, c] = lineCol(src, n.start);
          ipc.push([rel, l, c, 'contextBridge.exposeInMainWorld', key, a && a.type === 'Literal' ? 'literal' : 'computed']);
        }
        // registration hints
        if (/^(app|ipcMain|protocol|session|Menu|Tray|globalShortcut|powerMonitor|nativeTheme|shell|dialog)\./.test(cname)) {
          const [l, c] = lineCol(src, n.start);
          symbols.push(['K', mid, rel, cname, l, c, '']);
        }
      }
    });
  }
  modules.push([mid, rel, bytes, ast ? 'ok' : 'FAIL', String(imports.length), exportsN.length,
    fns.length, classes.length, dynHere.length, err.replace(/\t/g, ' ')]);
  for (const fn of fns) symbols.push(['F', mid, rel, fn[0], fn[1], fn[2], fn[3] + '|' + fn[4] + '|' + fn[5]]);
  for (const cl of classes) symbols.push(['C', mid, rel, cl[0], cl[1], cl[2], '']);
  for (const d of dynHere) dyn.push([mid, rel, d[0], d[1], d[2]]);
}

function memberPath(m) {
  const parts = [];
  let cur = m;
  while (cur) {
    if (cur.type === 'MemberExpression') {
      const p = cur.property;
      parts.unshift(p.type === 'Identifier' ? p.name : (p.type === 'Literal' ? String(p.value) : '<computed>'));
      cur = cur.object;
    } else if (cur.type === 'Identifier') { parts.unshift(cur.name); break; }
    else { parts.unshift('<expr>'); break; }
  }
  return parts.join('.');
}

w('MODULES.tsv', ['module_id', 'path', 'bytes', 'parse', 'imports', 'exports', 'functions', 'classes', 'dynamic_imports', 'parse_error'], modules);
w('SYMBOLS.tsv', ['kind', 'module_id', 'path', 'symbol', 'line', 'col', 'meta'], symbols);
w('CALL-EDGES.tsv', ['from_module', 'from_path', 'edge_kind', 'to_specifier', 'names'], edges);
w('DYNAMIC-IMPORTS.tsv', ['module_id', 'path', 'kind', 'at', 'arg_type'], dyn);
w('IPC-SIGNALS.tsv', ['path', 'line', 'col', 'api', 'channel', 'channel_kind'], ipc);
console.log('parse failures:', parseFail, 'files:', files.length);
