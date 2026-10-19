#!/usr/bin/env node
/**
 * P3 pairing: build caller/handler pairs from IPC-REGISTRATIONS.tsv.
 * Direction semantics:
 *   renderer->main : ipcRenderer.invoke/send/sendSync  <->  ipcMain.handle/on
 *   main->renderer : webContents.send/postMessage      <->  ipcRenderer.on
 *   main-internal  : webContents.on/once (BrowserWindow events, not IPC)
 * Emits IPC-REGISTRY.tsv and UNPAIRED-CALLS.tsv.
 */
const fs = require('fs');
const path = require('path');

const IDX = process.argv[2];
const rows = fs.readFileSync(path.join(IDX, 'IPC-REGISTRATIONS.tsv'), 'utf8')
  .split('\n').slice(1).filter(Boolean)
  .map(l => { const c = l.split('\t'); return { path: c[0], api: c[1], ch: c[2], res: c[3] }; });

const isWebContentsEvent = (api) =>
  /^webContents\.(on|once)$/.test(api) ||
  /\.on$/.test(api) && !/^ipcRenderer\./.test(api) && !/^ipcMain\./.test(api);

const toRenderer = rows.filter(r => /^(ipcRenderer)\.(invoke|send|sendSync)$/.test(r.api));
const fromMain = rows.filter(r => /^(ipcMain)\.(handle|on|handleOnce)$/.test(r.api) || r.api === 'ipcMain.removeHandler');
const pushMain = rows.filter(r => /^(webContents)\.(send|postMessage)$/.test(r.api));
const listenRenderer = rows.filter(r => /^ipcRenderer\.(on|once)$/.test(r.api));
const wcEvents = rows.filter(r => isWebContentsEvent(r.api));

const byCh = (arr) => {
  const m = new Map();
  for (const r of arr) {
    if (!r.ch) continue;
    if (!m.has(r.ch)) m.set(r.ch, []);
    m.get(r.ch).push(r);
  }
  return m;
};
const inv = byCh(toRenderer), hnd = byCh(fromMain), push = byCh(pushMain), lis = byCh(listenRenderer);

const all = new Set([...inv.keys(), ...hnd.keys(), ...push.keys(), ...lis.keys()]);
const out = [], unpaired = [];
let paired = 0;
for (const ch of [...all].sort()) {
  const callers = inv.get(ch) || [];
  const handlers = hnd.get(ch) || [];
  const pushers = push.get(ch) || [];
  const listeners = lis.get(ch) || [];
  const directional = (callers.length || handlers.length) ? 'renderer->main'
    : (pushers.length || listeners.length) ? 'main->renderer' : 'unknown';
  const closed = directional === 'renderer->main'
    ? (callers.length > 0 && handlers.length > 0)
    : (pushers.length > 0 && listeners.length > 0);
  if (closed) paired++;
  const row = [
    ch, directional, closed ? 'PAIRED' : 'UNPAIRED',
    callers.map(x => x.path + '@' + x.api).join(' | ') || '',
    handlers.map(x => x.path + '@' + x.api).join(' | ') || '',
    pushers.map(x => x.path + '@' + x.api).join(' | ') || '',
    listeners.map(x => x.path + '@' + x.api).join(' | ') || '',
    callers[0] && callers[0].res, handlers[0] && handlers[0].res,
  ];
  out.push(row);
  if (!closed) {
    const why = callers.length && !handlers.length ? 'CALLER_ONLY_NO_HANDLER'
      : handlers.length && !callers.length ? 'HANDLER_ONLY_NO_CALLER'
      : pushers.length && !listeners.length ? 'PUSH_ONLY_NO_LISTENER'
      : listeners.length && !pushers.length ? 'LISTENER_ONLY_NO_PUSH'
      : 'BOTH_SIDES_EMPTY';
    unpaired.push([ch, directional, why,
      callers.length, handlers.length, pushers.length, listeners.length,
      (callers[0] || handlers[0] || pushers[0] || listeners[0] || {}).path || '']);
  }
}

fs.writeFileSync(path.join(IDX, 'IPC-REGISTRY.tsv'),
  'channel\tdirection\tstatus\tcallers\thandlers\tpushers\tlisteners\tcaller_resolution\thandler_resolution\n' +
  out.map(r => r.join('\t')).join('\n') + '\n', 'utf8');
fs.writeFileSync(path.join(IDX, 'UNPAIRED-CALLS.tsv'),
  'channel\tdirection\treason\tcallers\thandlers\tpushers\tlisteners\tsample_path\n' +
  unpaired.map(r => r.join('\t')).join('\n') + '\n', 'utf8');
fs.writeFileSync(path.join(IDX, 'WEBCONTENTS-EVENTS.tsv'),
  'path\tapi\tevent\n' + wcEvents.map(r => [r.path, r.api, r.ch].join('\t')).join('\n') + '\n', 'utf8');

console.log('channels', all.size, 'paired', paired, 'unpaired', unpaired.length);
console.log('registrations total', rows.length);
console.log('  renderer->main callers', toRenderer.length, 'handlers', fromMain.length);
console.log('  main->renderer pushers', pushMain.length, 'listeners', listenRenderer.length);
console.log('  webContents events', wcEvents.length);
const reasons = {};
for (const u of unpaired) reasons[u[2]] = (reasons[u[2]] || 0) + 1;
console.log(reasons);
