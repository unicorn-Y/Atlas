#!/usr/bin/env node
/**
 * P1: build the per-file classification ledger for every ASAR file.
 * Combines: parse status (MODULES.tsv), the eipc services each file defines,
 * contextBridge worlds, worker role, renderer role, and size bucket.
 * Emits MODULE-CLASSIFICATION.tsv with an explicit evidence level per row.
 */
const fs = require('fs');
const path = require('path');

const IDX = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';
const ASAR = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar';

const tsv = (n) => {
  const p = path.join(IDX, n);
  if (!fs.existsSync(p)) return [];
  return fs.readFileSync(p, 'utf8').split('\n').slice(1).filter(Boolean).map(l => l.split('\t'));
};

const modules = tsv('MODULES.tsv');
const svc = tsv('EIPC-SERVICES.tsv');
const bridges = tsv('CONTEXTBRIDGE-EXPOSURES.tsv');
const regs = tsv('IPC-REGISTRATIONS.tsv');
const methods = tsv('EIPC-METHODS.tsv');
const events = tsv('EIPC-EVENTS.tsv');

const byFile = {};
const push = (f, k, v) => { (byFile[f] = byFile[f] || { services: [], worlds: [], regs: 0, methods: 0, events: 0 })[k].push(v); };

for (const r of svc) push(r[0], 'services', r[2]);
for (const r of bridges) if (r[2]) push(r[0], 'worlds', r[2]);
for (const r of regs) (byFile[r[0]] = byFile[r[0]] || { services: [], worlds: [], regs: 0, methods: 0, events: 0 }).regs++;
for (const r of methods) (byFile[r[0]] = byFile[r[0]] || { services: [], worlds: [], regs: 0, methods: 0, events: 0 }).methods++;
for (const r of events) (byFile[r[0]] = byFile[r[0]] || { services: [], worlds: [], regs: 0, methods: 0, events: 0 }).events++;

const known = {
  'main': 'Electron 主进程入口 / 启动编排',
  'preload': '窗口 preload，向渲染进程暴露 contextBridge API',
  'renderer': '本地渲染器（窗口 UI）',
  'worker': 'utilityProcess / Worker 子进程',
};

const classify = (p) => {
  if (p.startsWith('.vite/renderer/')) return ['renderer', 'renderer-' + p.split('/')[2]];
  if (p.startsWith('.vite/build/mcp-runtime/')) return ['mcp-runtime', 'MCP host'];
  if (/^\.vite\/build\/(file-index-worker|heavy-work-worker|transcript-search-worker|shell-path-worker|stall-sampler-worker|msal-broker-worker|pty-host)\//.test(p)) {
    return ['worker', 'worker:' + p.split('/')[2]];
  }
  if (p.startsWith('.vite/build/')) {
    const base = path.basename(p, '.js');
    if (base === 'index.pre') return ['main', 'main-entry-pre'];
    if (base === 'index') return ['main', 'main-entry'];
    if (/^(aboutWindow|buddy|claudePagePreview|computerUseTeach|computerUseWatchRecord|coworkArtifact|designWindow|findInPage|localExecConsent|mainView|mainWindow|quickWindow|watchRecordChooser)$/.test(base)) {
      return ['preload', 'preload:' + base];
    }
    if (/^index\.chunk-/.test(base)) return ['main', 'main-chunk'];
    return ['main', 'main-other'];
  }
  if (p.startsWith('node_modules/')) return ['dependency', 'npm:' + p.split('/').slice(1, 3).join('/')];
  if (p.startsWith('resources/')) return ['resource', p.split('/')[1]];
  if (p.startsWith('compile-cache/')) return ['cache', 'v8-code-cache'];
  if (p === 'package.json') return ['metadata', 'package-manifest'];
  return ['other', 'unclassified'];
};

const rows = [['path', 'bytes', 'parse', 'layer', 'role_detail', 'eipc_services', 'bridge_worlds', 'ipc_registrations', 'eipc_methods', 'eipc_events', 'evidence', 'notes']];
for (const m of modules) {
  const [mid, p, bytes, parse] = m;
  const [layer, detail] = classify(p);
  const b = byFile[p] || { services: [], worlds: [], regs: 0, methods: 0, events: 0 };
  let ev = 'S';
  if (parse !== 'ok') ev = 'U';
  else if (!b.services.length && !b.regs && !b.worlds) ev = 'S'; // parsed but no RPC surface: still statically read
  rows.push([p, bytes, parse, layer, detail,
    [...new Set(b.services)].join(','), [...new Set(b.worlds)].join(','),
    b.regs, b.methods, b.events, ev, '']);
}

// include non-JS asar files from the P0 ledger so nothing disappears
const asarLedger = tsv('ASAR-FILE-LEDGER.tsv');
const seen = new Set(modules.map(m => m[1]));
const extra = [];
for (const r of asarLedger) {
  const p = r[4], kind = r[5], size = r[6];
  if (kind === 'dir' || seen.has(p)) continue;
  const [layer, detail] = classify(p);
  extra.push([p, size, 'n/a', layer, detail, '', '', 0, 0, 0, 'S', 'non-JS asset/scaffold; registered in P0 ledger']);
}
rows.push(...extra);

fs.writeFileSync(path.join(IDX, 'MODULE-CLASSIFICATION.tsv'),
  rows.map(r => r.join('\t')).join('\n') + '\n', 'utf8');

const hist = {};
for (const r of rows.slice(1)) hist[r[3]] = (hist[r[3]] || 0) + 1;
console.log('rows', rows.length - 1, JSON.stringify(hist, null, 1));
