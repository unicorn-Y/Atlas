#!/usr/bin/env node
/**
 * P3: build the method-level RPC registry.
 * The transport-level pairing (IPC-REGISTRY.tsv) shows only 3 closed channels because
 * eipc multiplexes 97 services over ONE channel; the real unit is (service, method).
 *
 * For each (service, method) we record:
 *   - handler: the eipc service definition site (the service owns it by construction)
 *   - caller: every renderer bundle whose preload attaches the namespace of that service
 *   - status: PAIRED when a namespace-matching preload exists, else HANDLER_ONLY
 */
const fs = require('fs');
const path = require('path');

const IDX = 'D:/Atlas/_research/claude-desktop/2026-10-20/index';
const tsv = (n) => fs.readFileSync(path.join(IDX, n), 'utf8')
  .split('\n').slice(1).filter(Boolean).map(l => l.split('\t'));

const svc = tsv('EIPC-SERVICES.tsv');
const methods = tsv('EIPC-METHODS.tsv');
const events = tsv('EIPC-EVENTS.tsv');
const bridges = tsv('CONTEXTBRIDGE-EXPOSURES.tsv');
const regs = tsv('IPC-REGISTRATIONS.tsv');

// namespace -> which preload/bundle references it
const nsOf = {};
for (const [p, namespace, service] of svc) {
  nsOf[service] = nsOf[service] || { namespace, at: [] };
  nsOf[service].at.push(p);
}
// which files mention a given namespace suffix (preloads attach namespaces)
const nsFiles = {};
for (const r of regs.concat(bridges)) {
  const p = r[0];
  nsFiles[p] = (nsFiles[p] || 0) + 1;
}

// preload -> namespaces it can reach (by scanning the file's channel strings)
const fsx = require('fs');
const ASAR = 'D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar';
const preloads = fsx.readdirSync(path.join(ASAR, '.vite/build'))
  .filter(f => /^(aboutWindow|buddy|claudePagePreview|computerUseTeach|computerUseWatchRecord|coworkArtifact|designWindow|findInPage|localExecConsent|mainView|mainWindow|quickWindow|watchRecordChooser)\.js$/.test(f));

const preloadNs = {};
for (const f of preloads) {
  const src = fsx.readFileSync(path.join(ASAR, '.vite/build', f), 'utf8');
  const found = new Set();
  const re = /_claude\.([a-zA-Z0-9._-]+)_\$_/g;
  let m;
  while ((m = re.exec(src))) found.add(m[1]);
  preloadNs[f] = [...found];
}

const rows = [];
const svcNames = new Set(methods.map(m => m[1]).concat(events.map(e => e[1])));
for (const s of [...svcNames].sort()) {
  const info = nsOf[s] || { namespace: '', at: [] };
  const ms = methods.filter(m => m[1] === s);
  const evs = events.filter(e => e[1] === s);
  // which preloads reference this service name at all
  const callers = preloads.filter(f => {
    try {
      return fsx.readFileSync(path.join(ASAR, '.vite/build', f), 'utf8').includes(s);
    } catch { return false; }
  });
  const nsKey = info.namespace.replace(/^\$eipc_message\$[0-9a-f-]{36}_\$_/, '').replace(/_$/, '');
  const nsCallers = preloads.filter(f => (preloadNs[f] || []).includes(nsKey));
  for (const m of ms) {
    rows.push(['method', s, m[2], m[3], nsKey, (callers.join(',') || ''), (nsCallers.join(',') || ''),
      callers.length || nsCallers.length ? 'PAIRED' : 'HANDLER_ONLY', info.at[0] || '']);
  }
  for (const e of evs) {
    rows.push(['event', s, e[2], e[3], nsKey, (callers.join(',') || ''), (nsCallers.join(',') || ''),
      callers.length || nsCallers.length ? 'PAIRED' : 'HANDLER_ONLY', info.at[0] || '']);
  }
}

fs.writeFileSync(path.join(IDX, 'RPC-REGISTRY.tsv'),
  'kind\tservice\tname\tparams\tnamespace\tname_referencing_preloads\tnamespace_preloads\tstatus\thandler_site\n' +
  rows.map(r => r.join('\t')).join('\n') + '\n', 'utf8');

const paired = rows.filter(r => r[7] === 'PAIRED').length;
console.log('rpc entries', rows.length, 'paired', paired, 'handler-only', rows.length - paired);
console.log('\npreload -> namespaces:');
for (const [f, ns] of Object.entries(preloadNs)) console.log('  ' + f.padEnd(30) + ns.join(','));
const orphan = Object.keys(nsOf).filter(s => !nsOf[s].namespace);
console.log('\nservices without namespace:', orphan.join(',') || 'none');
