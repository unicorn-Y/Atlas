'use strict';

/**
 * One isolated Electron window ('window1' or 'window2') that mounts the real
 * worktree ShortcutsPanel and drives its real buttons with DOM events.
 *
 * Scenarios (--scenario):
 *   missing     keybindings.json absent for both windows at mount
 *   existing    keybindings.json present for both windows at mount
 *   same-action both windows edit the same action, then window2 adjudicates
 *
 * Window 2 mounts first and reads the initial revision. Window 1 then edits
 * action A and saves. Window 2 edits action B (or the same action) and hits
 * the 409 path. Coordination uses marker files in --run; each role has its own
 * --user-data-dir so localStorage is isolated.
 */

const { app, BrowserWindow } = require('electron');
const fs = require('fs');
const path = require('path');

const argv = process.argv.slice(2);
function arg(name) {
  const prefix = `--${name}=`;
  const hit = argv.find((item) => item.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : undefined;
}

const role = arg('role');
const scenario = arg('scenario') || 'existing';
const url = arg('url');
const outDir = arg('out');
const runDir = arg('run');
if (!role || !url || !outDir || !runDir || !['missing', 'existing', 'same-action'].includes(scenario)) {
  console.error('usage: electron driver.cjs --role=window1 --scenario=missing|existing|same-action --url=... --out=... --run=...');
  app.exit(2);
  return;
}

const userData = path.join(runDir, `${scenario}-userdata-${role}`);
app.setPath('userData', userData);
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('no-sandbox');

const logLines = [];
function log(...parts) {
  const line = `[${new Date().toISOString()}] [${scenario}/${role}] ${parts.join(' ')}`;
  logLines.push(line);
  console.log(line);
}
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function markerPath(name) { return path.join(runDir, `${scenario}-${name}`); }
function writeMarker(name) { fs.writeFileSync(markerPath(name), new Date().toISOString()); }
async function waitForMarker(name, timeoutMs = 120000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(markerPath(name))) return true;
    await sleep(100);
  }
  throw new Error(`timeout waiting for marker ${name}`);
}

let win;

async function evalJs(code) {
  return win.webContents.executeJavaScript(code, true);
}

async function waitFor(code, label, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await evalJs(code);
      if (last) return last;
    } catch (error) {
      last = String(error);
    }
    await sleep(150);
  }
  throw new Error(`timeout waiting for ${label}; last=${JSON.stringify(last)}`);
}

async function clickByAria(label) {
  return evalJs(`(() => {
    const button = document.querySelector('button[aria-label=${JSON.stringify(label)}]');
    if (!button) return { ok: false, reason: 'missing button' };
    button.click();
    return { ok: true, label: button.getAttribute('aria-label') };
  })()`);
}

async function clickByText(text) {
  return evalJs(`(() => {
    const target = ${JSON.stringify(text)};
    const button = [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === target);
    if (!button) return { ok: false, reason: 'missing button', texts: [...document.querySelectorAll('button')].map((item) => item.textContent.trim()).filter(Boolean) };
    button.click();
    return { ok: true, text: button.textContent.trim() };
  })()`);
}

async function clickConflictResolution(action, text) {
  return evalJs(`(() => {
    const row = document.querySelector('[data-conflict-action=${JSON.stringify(action)}]');
    if (!row) return { ok: false, reason: 'missing conflict row' };
    const target = ${JSON.stringify(text)};
    const button = [...row.querySelectorAll('button')].find((item) => item.textContent.trim() === target);
    if (!button) return { ok: false, reason: 'missing resolution button', texts: [...row.querySelectorAll('button')].map((item) => item.textContent.trim()) };
    button.click();
    return { ok: true, text: button.textContent.trim() };
  })()`);
}

async function recordCombo(label, key, modifiers) {
  const init = JSON.stringify({
    key,
    ctrlKey: Boolean(modifiers.ctrlKey),
    altKey: Boolean(modifiers.altKey),
    shiftKey: Boolean(modifiers.shiftKey),
    metaKey: false,
    bubbles: true,
    cancelable: true,
  });
  return evalJs(`(() => {
    const button = document.querySelector('button[aria-label=${JSON.stringify(label)}]');
    if (!button) return { ok: false, reason: 'missing button' };
    const event = new KeyboardEvent('keydown', ${init});
    const dispatched = button.dispatchEvent(event);
    return { ok: true, dispatched, defaultPrevented: event.defaultPrevented, label: button.getAttribute('aria-label') };
  })()`);
}

async function snapshot(stage) {
  const domText = await evalJs('document.body.innerText');
  const html = await evalJs('document.documentElement.outerHTML');
  const cache = await evalJs("localStorage.getItem('atlas.shortcuts')");
  const status = await evalJs("document.querySelector('[role=\"status\"]') ? document.querySelector('[role=\"status\"]').textContent : null");
  const conflict = await evalJs("document.querySelector('[data-keybindings-conflict]') ? document.querySelector('[data-keybindings-conflict]').innerText : null");
  const replayConflict = await evalJs("document.querySelector('[data-keybindings-replay-conflict]') ? document.querySelector('[data-keybindings-replay-conflict]').innerText : null");
  const conflictRows = await evalJs("[...document.querySelectorAll('[data-conflict-action]')].map((row) => ({ action: row.getAttribute('data-conflict-action'), text: row.innerText }))");
  let server = null;
  try {
    server = await evalJs("fetch('/api/u6/keybindings', {cache: 'no-store'}).then((response) => response.json())");
  } catch (error) {
    server = { error: String(error) };
  }
  const shotPath = path.join(outDir, `par09-b2-electron-${scenario}-${role}-${stage}.png`);
  const image = await win.capturePage();
  fs.writeFileSync(shotPath, image.toPNG());
  const result = {
    scenario,
    role,
    stage,
    timestamp: new Date().toISOString(),
    url,
    electronArgv: process.argv.slice(),
    userDataDir: userData,
    userDataPath: app.getPath('userData'),
    status,
    conflict,
    replayConflict,
    conflictRows,
    localStorage: cache === null ? null : JSON.parse(cache),
    server,
    domText,
    html: String(html).slice(0, 200000),
    screenshot: shotPath,
    log: logLines.slice(),
  };
  const jsonPath = path.join(outDir, `par09-b2-electron-${scenario}-${role}-${stage}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify(result, null, 2));
  log(`snapshot ${stage}: status=${JSON.stringify(status)} conflict=${Boolean(conflict)} rows=${JSON.stringify(conflictRows.map((row) => row.action))} revision=${server && server.revision}`);
  return result;
}

const READY = "Boolean(document.querySelector('[data-shortcut-recorder]') && document.querySelector('[role=\"status\"]'))";
const CONFLICT_VISIBLE = "Boolean(document.querySelector('[data-keybindings-conflict]'))";
const REPLAY_CONFLICT_VISIBLE = "Boolean(document.querySelector('[data-keybindings-replay-conflict]'))";
const SAVE_OK = "((document.querySelector('[role=\"status\"]') || {}).textContent || '').includes('快捷键已保存到 keybindings.json')";
const RETRY_OK = "!document.querySelector('[data-keybindings-conflict]') && ((document.querySelector('[role=\"status\"]') || {}).textContent || '').includes('其他窗口的修改已保留')";
const RESOLVED_OK = "!document.querySelector('[data-keybindings-conflict]') && ((document.querySelector('[role=\"status\"]') || {}).textContent || '').includes('已按选择保存')";

async function run() {
  win = new BrowserWindow({
    width: 1280,
    height: 1000,
    show: false,
    webPreferences: { backgroundThrottling: false, contextIsolation: true, nodeIntegration: false },
  });
  win.webContents.on('render-process-gone', (_event, details) => log('render-process-gone', JSON.stringify(details)));
  win.webContents.on('console-message', (_event, level, message) => log(`console(${level}): ${message}`));
  win.webContents.on('did-fail-load', (_event, code, description, validUrl) => log(`did-fail-load ${code} ${description} ${validUrl}`));

  log(`loading ${url}`);
  await win.loadURL(url);
  await waitFor(READY, 'ShortcutsPanel mounted');
  // The panel's mount refresh is async; let it finish before this role claims ready.
  await sleep(1500);
  if (scenario !== 'missing') {
    await waitFor("localStorage.getItem('atlas.shortcuts') !== null", 'mount file adoption');
  }
  await snapshot('ready');

  if (role === 'window1') {
    writeMarker('w1-ready');
    await waitForMarker('w2-ready');
    log('window2 ready; clicking palette binding row');
    const clicked = await clickByAria('修改「搜索与命令」的第 1 组快捷键');
    log(`click palette binding: ${JSON.stringify(clicked)}`);
    await sleep(200);
    const typed = await recordCombo('修改「搜索与命令」的第 1 组快捷键', 'u', { ctrlKey: true, altKey: true });
    log(`dispatch Ctrl+Alt+U: ${JSON.stringify(typed)}`);
    await waitFor(SAVE_OK, 'window1 palette save');
    const saved = await snapshot('saved');
    if (saved.localStorage.palette[0] !== 'Ctrl+Alt+U') throw new Error(`window1 palette not set locally: ${JSON.stringify(saved.localStorage.palette)}`);
    writeMarker('w1-saved');
    log('window1 save done; waiting for window2');
    await waitForMarker('w2-done', 150000);
    await snapshot('after');
    writeMarker('w1-done');
    log('window1 complete');
    app.exit(0);
    return;
  }

  if (role === 'window2') {
    writeMarker('w2-ready');
    await waitForMarker('w1-saved');
    if (scenario === 'same-action') {
      log('window1 saved palette; window2 now edits the same palette action');
      const clicked = await clickByAria('修改「搜索与命令」的第 1 组快捷键');
      log(`click palette binding: ${JSON.stringify(clicked)}`);
      await sleep(200);
      const typed = await recordCombo('修改「搜索与命令」的第 1 组快捷键', 'o', { ctrlKey: true, altKey: true });
      log(`dispatch Ctrl+Alt+O: ${JSON.stringify(typed)}`);
      await waitFor(CONFLICT_VISIBLE, '409 conflict banner');
      await snapshot('409');
      const retry = await clickByText('用本机改动重试保存');
      log(`click retry: ${JSON.stringify(retry)}`);
      await waitFor(REPLAY_CONFLICT_VISIBLE, 'per-action conflict row');
      const conflicted = await snapshot('replay-conflict');
      const row = conflicted.conflictRows.find((item) => item.action === 'palette');
      if (!row) throw new Error(`no palette conflict row: ${JSON.stringify(conflicted.conflictRows)}`);
      if (conflicted.server.bindings.palette[0] !== 'Ctrl+Alt+U') {
        throw new Error(`file palette changed before resolution: ${JSON.stringify(conflicted.server.bindings.palette)}`);
      }
      const choose = await clickConflictResolution('palette', '保留本机');
      log(`click 保留本机: ${JSON.stringify(choose)}`);
      await sleep(150);
      const apply = await clickByText('按选择保存');
      log(`click 按选择保存: ${JSON.stringify(apply)}`);
      await waitFor(RESOLVED_OK, 'resolved save');
      await snapshot('resolved');
      writeMarker('w2-done');
      log('window2 same-action resolution complete');
      await sleep(300);
      app.exit(0);
      return;
    }

    log('window1 saved action A; clicking newTask binding row');
    const clicked = await clickByAria('修改「新任务」的第 1 组快捷键');
    log(`click newTask binding: ${JSON.stringify(clicked)}`);
    await sleep(200);
    const typed = await recordCombo('修改「新任务」的第 1 组快捷键', 'n', { ctrlKey: true, altKey: true });
    log(`dispatch Ctrl+Alt+N: ${JSON.stringify(typed)}`);
    await waitFor(CONFLICT_VISIBLE, '409 conflict banner');
    const conflictSnapshot = await snapshot('409');
    if (conflictSnapshot.replayConflict) throw new Error(`unexpected replay conflict before retry: ${conflictSnapshot.replayConflict}`);
    const retry = await clickByText('用本机改动重试保存');
    log(`click retry: ${JSON.stringify(retry)}`);
    await waitFor(RETRY_OK, 'retry replay success');
    const retried = await snapshot('retry');
    if (retried.replayConflict || retried.conflictRows.length > 0) {
      throw new Error(`unexpected per-action conflict after retry: ${JSON.stringify(retried.conflictRows)}`);
    }
    writeMarker('w2-done');
    log('window2 retry complete');
    await sleep(300);
    app.exit(0);
    return;
  }

  throw new Error(`unknown role ${role}`);
}

app.whenReady().then(() => {
  run().catch((error) => {
    log(`FAILED: ${error && error.stack ? error.stack : error}`);
    const failure = { scenario, role, error: error && error.stack ? error.stack : String(error), log: logLines.slice() };
    fs.writeFileSync(path.join(outDir, `par09-b2-electron-${scenario}-${role}-error.json`), JSON.stringify(failure, null, 2));
    app.exit(1);
  });
});