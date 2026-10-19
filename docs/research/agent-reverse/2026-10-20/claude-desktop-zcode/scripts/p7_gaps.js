#!/usr/bin/env node
/**
 * P7/P8: bidirectional gap analysis.
 *  1. RPC handlers with no reachable renderer caller  (handler-only)
 *  2. renderer-referenced names that match no eipc method (caller-only candidates)
 *  3. webContents events with no renderer listener
 *  4. main-process modules that are never imported by index.pre/index (orphans)
 * Emits UNRESOLVED-CALL-EDGES.tsv and STATIC-GAPS.json
 */
const fs = require('fs');
const path = require('path');

const IDX = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';
const ASAR = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar';
const tsv = (n) => fs.readFileSync(path.join(IDX, n), 'utf8')
  .split('\n').slice(1).filter(Boolean).map(l => l.split('\t'));

const rpc = tsv('RPC-REGISTRY.tsv');
const methods = tsv('EIPC-METHODS.tsv');
const events = tsv('EIPC-EVENTS.tsv');
const edges = tsv('CALL-EDGES.tsv');
const mods = tsv('MODULES.tsv');
const wc = tsv('WEBCONTENTS-EVENTS.tsv');

const rows = [];

// 1. handler without caller (preload doesn't reference the service name)
const svcToPreload = {};
for (const r of rpc) {
  const svc = r[1];
  if (!svcToPreload[svc]) svcToPreload[svc] = new Set();
  if (r[5]) r[5].split(',').filter(Boolean).forEach(x => svcToPreload[svc].add(x));
}
for (const [svc, set] of Object.entries(svcToPreload)) {
  if (set.size === 0) rows.push(['HANDLER_NO_CALLER', svc, '-', 'no preload references this service', 'U']);
}

// 2. modules never required/imported by any other module
const imported = new Set();
for (const e of edges) {
  let spec = e[3] || '';
  spec = spec.replace(/^\.\//, '').replace(/\.js$/, '');
  imported.add(spec);
}
const mainChunks = mods.filter(m => m[1].startsWith('.vite/build/index.chunk-'));
let orphanChunks = 0;
for (const m of mainChunks) {
  const base = path.basename(m[1], '.js');
  if (!imported.has(base) && !imported.has(m[1])) {
    orphanChunks++;
    rows.push(['MODULE_NOT_IMPORTED_BY_NAME', m[1], '-', 'no static import/require edge names this chunk', 'I']);
  }
}

// 3. webContents events with no renderer listener of the same name
const rendererListeners = new Set(tsv('IPC-REGISTRATIONS.tsv')
  .filter(r => /^ipcRenderer\.(on|once)$/.test(r[1]))
  .map(r => r[2]));
let wcNoListener = 0;
for (const r of wc) {
  const name = r[2];
  if (name && !rendererListeners.has(name)) {
    wcNoListener++;
    // these are BrowserWindow/webContents DOM-ish events, expected to have no ipcRenderer twin
  }
}

// 4. renderer-side method-ish names that match no eipc method
const eipcNames = new Set(methods.map(m => m[2]));
const rendererFiles = fs.readdirSync(path.join(ASAR, '.vite/renderer/main_window/assets'))
  .filter(f => f.endsWith('.js'));
let rendererUnknownCalls = 0;
const unknownNames = new Set();
for (const f of rendererFiles) {
  const src = fs.readFileSync(path.join(ASAR, '.vite/renderer/main_window/assets', f), 'utf8');
  const re = /\.([a-zA-Z_$][a-zA-Z0-9_$]{3,40})\s*\(/g;
  let m;
  while ((m = re.exec(src))) {
    const n = m[1];
    if (eipcNames.has(n)) continue;
    if (/^(then|catch|finally|map|filter|reduce|forEach|slice|splice|concat|join|split|replace|test|exec|match|push|pop|shift|unshift|sort|find|findIndex|some|every|includes|indexOf|toString|valueOf|hasOwnProperty|addEventListener|removeEventListener|dispatchEvent|querySelector|querySelectorAll|getElementById|createElement|appendChild|removeChild|setAttribute|getAttribute|preventDefault|stopPropagation|JSON|Object|Array|String|Number|Boolean|Promise|Math|Date|Error|console|setTimeout|setInterval|clearTimeout|clearInterval|requestAnimationFrame|cancelAnimationFrame|fetch|parse|stringify|keys|values|entries|assign|freeze|isArray|from|of)$/.test(n)) continue;
    unknownNames.add(n);
    rendererUnknownCalls++;
    if (unknownNames.size <= 400) rows.push(['RENDERER_CALL_UNMAPPED', f, n, 'name called in renderer but not an eipc method', 'I']);
  }
}

fs.writeFileSync(path.join(IDX, 'UNRESOLVED-CALL-EDGES.tsv'),
  'gap_kind\twhere\tname\tdetail\tconfidence\n' +
  rows.map(r => r.join('\t')).join('\n') + '\n', 'utf8');

const summary = {
  rpc_entries: rpc.length,
  rpc_paired: rpc.filter(r => r[7] === 'PAIRED').length,
  services_without_preload: Object.entries(svcToPreload).filter(([, s]) => s.size === 0).map(([k]) => k),
  main_chunks: mainChunks.length,
  main_chunks_not_statically_imported: orphanChunks,
  webcontents_events: wc.length,
  webcontents_events_without_renderer_listener: wcNoListener,
  renderer_call_names_unmapped: unknownNames.size,
  unresolved_edges_total: rows.length,
};
fs.writeFileSync(path.join(IDX, 'STATIC-GAPS.json'), JSON.stringify(summary, null, 2), 'utf8');
console.log(JSON.stringify(summary, null, 2));
