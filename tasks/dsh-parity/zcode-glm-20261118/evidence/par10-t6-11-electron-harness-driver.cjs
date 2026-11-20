'use strict';

/**
 * T6-11 shortcut reference renderer probe (single isolated Electron window).
 *
 * Mounts the candidate tree's real ShortcutReferenceHost + real ShortcutsPanel
 * inside the real Atlas Dialog (Radix) and drives:
 *   1. primary+/ open and close through a real Electron input event
 *   2. visible Settings entry -> embedded reference inside the Settings dialog
 *   3. inline recording -> real PUT to a temporary uvicorn running the real
 *      atlas.api.u6_router (keybindings.json)
 *   4. recording suppression: primary+/ inside an active recorder never opens
 *   5. modal exclusivity: another dialog blocks with reason "modal"; while the
 *      reference is open, App-level Ctrl+K / Ctrl+, are swallowed
 *   6. closing Settings while the reference is stacked inside it closes the
 *      reference instead of leaving a dead portal
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

const url = arg('url');
const outDir = arg('out');
const runDir = arg('run');
if (!url || !outDir || !runDir) {
  console.error('usage: electron driver.cjs --url=... --out=... --run=...');
  app.exit(2);
  return;
}

const userData = path.join(runDir, 'userdata');
app.setPath('userData', userData);
app.disableHardwareAcceleration();
app.commandLine.appendSwitch('disable-gpu');
app.commandLine.appendSwitch('no-sandbox');

const problems = [];
const steps = [];
let win;
let appGlobalBaseline = 0;

function log(...parts) {
  console.log(`[${new Date().toISOString()}] [t6-11] ${parts.join(' ')}`);
}
function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }
function expect(condition, message) { if (!condition) problems.push(message); }

async function evalJs(code) {
  return win.webContents.executeJavaScript(code, true);
}

async function waitFor(code, label, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try {
      last = await evalJs(code);
      if (last) return last;
    } catch (error) {
      last = String(error);
    }
    await sleep(120);
  }
  throw new Error(`timeout waiting for ${label}; last=${JSON.stringify(last)}`);
}

async function capture(stage) {
  const state = await evalJs(`(() => {
    const overlay = document.querySelector('[data-shortcut-reference]');
    const blocked = document.querySelector('[data-reference-blocked]');
    const settings = document.querySelector('[role="dialog"] [aria-label="关闭设置"]')?.closest('[role="dialog"]') ?? null;
    const active = document.activeElement;
    const settingsContent = document.querySelector('[data-settings-content]');
    return {
      stage: ${JSON.stringify(stage)},
      overlay: Boolean(overlay),
      variant: overlay?.getAttribute('data-shortcut-reference-variant') ?? null,
      overlayInsideSettings: Boolean(overlay && settings && settings.contains(overlay)),
      overlayIsTopDialog: Boolean(overlay && overlay.querySelector('[role="dialog"]')?.contains(active ?? document.body)),
      settingsOpen: Boolean(settingsContent),
      blockedReason: blocked?.getAttribute('data-reference-blocked') ?? null,
      blockedText: blocked?.textContent?.trim() ?? null,
      activeLabel: active?.getAttribute?.('aria-label') ?? active?.tagName ?? null,
      status: document.querySelector('[data-shortcut-reference] [role="status"]')?.textContent?.trim()
        ?? document.querySelector('[data-shortcut-recorder] [role="status"]')?.textContent?.trim() ?? null,
      appGlobalCount: window.__probe?.appGlobalCount?.() ?? null,
      keyLog: window.__probe?.keyLog?.() ?? null,
      dialogs: [...document.querySelectorAll('[role="dialog"], [role="alertdialog"]')].map((dialog) => ({
        role: dialog.getAttribute('role'),
        modal: dialog.getAttribute('aria-modal'),
        label: dialog.getAttribute('aria-label'),
        hasClose: Boolean(dialog.querySelector('[aria-label="关闭设置"]')),
        text: (dialog.innerText || '').slice(0, 60),
      })),
      localCache: localStorage.getItem('atlas.shortcuts'),
      rowCount: document.querySelectorAll('[data-reference-row]').length,
      visibleRows: [...document.querySelectorAll('[data-reference-row]')].map((row) => row.getAttribute('data-reference-row')),
      recordingActive: Boolean(document.querySelector('[data-reference-recording="true"], [data-shortcut-recorder][data-reference-recording]')),
      domText: document.body.innerText.slice(0, 4000),
    };
  })()`);
  const shot = path.join(outDir, `par10-t6-11-electron-${stage}.png`);
  try {
    // Let Chromium present the frame React just committed before capturing.
    await sleep(220);
    const image = await win.capturePage();
    fs.writeFileSync(shot, image.toPNG());
  } catch (error) {
    state.screenshotError = String(error);
  }
  state.screenshot = shot;
  state.server = await evalJs("fetch('/api/u6/keybindings', {cache: 'no-store'}).then((response) => response.json()).catch((error) => ({ error: String(error) }))");
  const jsonPath = path.join(outDir, `par10-t6-11-electron-${stage}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify(state, null, 2));
  steps.push({ stage, path: jsonPath, screenshot: shot });
  log(`snapshot ${stage}: overlay=${state.overlay} variant=${state.variant} settings=${state.settingsOpen} blocked=${state.blockedReason} active=${state.activeLabel}`);
  return state;
}

async function clickSelector(selector) {
  return evalJs(`(() => {
    const target = document.querySelector(${JSON.stringify(selector)});
    if (!target) return { ok: false, reason: 'missing selector' };
    target.click();
    return { ok: true, text: (target.textContent || '').trim(), aria: target.getAttribute('aria-label') };
  })()`);
}

async function dispatchKey(selector, init) {
  return evalJs(`(() => {
    const target = ${selector ? `document.querySelector(${JSON.stringify(selector)})` : 'document.body'};
    if (!target) return { ok: false, reason: 'missing target' };
    const event = new KeyboardEvent('keydown', Object.assign({
      bubbles: true, cancelable: true, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false,
    }, ${JSON.stringify(init)}));
    target.dispatchEvent(event);
    return { ok: true, dispatched: true, defaultPrevented: event.defaultPrevented, key: event.key };
  })()`);
}

async function recordCombo(selector, key, modifiers) {
  return evalJs(`(() => {
    const target = document.querySelector(${JSON.stringify(selector)});
    if (!target) return { ok: false, reason: 'missing record target' };
    target.click();
    const event = new KeyboardEvent('keydown', {
      key: ${JSON.stringify(key)}, code: ${JSON.stringify(`Key${String(key).toUpperCase()}`)},
      ctrlKey: ${Boolean(modifiers.ctrlKey)}, altKey: ${Boolean(modifiers.altKey)},
      shiftKey: ${Boolean(modifiers.shiftKey)}, metaKey: false, bubbles: true, cancelable: true,
    });
    const dispatched = target.dispatchEvent(event);
    return { ok: true, dispatched, defaultPrevented: event.defaultPrevented, aria: target.getAttribute('aria-label') };
  })()`);
}

async function setSearch(value) {
  return evalJs(`(() => {
    const input = document.querySelector('[data-shortcut-reference] [aria-label="搜索快捷键"]');
    if (!input) return { ok: false, reason: 'missing search input' };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, ${JSON.stringify(value)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return { ok: true, value: input.value };
  })()`);
}

const OVERLAY = "Boolean(document.querySelector('[data-shortcut-reference]'))";
const SETTINGS_OPEN = "Boolean(document.querySelector('[data-settings-content]'))";
const BLOCKED_VISIBLE = "Boolean(document.querySelector('[data-reference-blocked=\"modal\"]'))";

async function main() {
  win = new BrowserWindow({
    width: 1180, height: 800, show: true, backgroundColor: '#F4F3F0',
    webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  await win.loadURL(url);
  await waitFor('Boolean(window.__probe && window.__probe.ready)', 'harness ready');
  await waitFor("!Boolean(document.querySelector('[data-open-shortcut-reference]'))", 'settings closed at start');
  win.focus();
  win.webContents.focus();
  await sleep(250);
  let state = await capture('00-initial');
  expect(state.overlay === false, 'overlay must start closed');
  appGlobalBaseline = state.appGlobalCount ?? 0;

  // 1. Real Electron input event: primary+Slash opens the reference.
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: '/', modifiers: ['control'] });
  win.webContents.sendInputEvent({ type: 'keyUp', keyCode: '/', modifiers: ['control'] });
  let openedByRealInput = false;
  try {
    await waitFor(OVERLAY, 'overlay after real Ctrl+/ input', 4000);
    openedByRealInput = true;
  } catch { /* recorded below */ }
  state = await capture('01-real-key-open');
  expect(openedByRealInput, 'real Electron Ctrl+/ input must open the reference');
  expect(state.variant === 'standalone', `standalone variant expected, got ${state.variant}`);

  if (!openedByRealInput) {
    await dispatchKey(null, { key: '/', code: 'Slash', ctrlKey: true });
    await waitFor(OVERLAY, 'overlay after DOM Ctrl+/ fallback');
    state = await capture('01b-dom-key-open');
    expect(state.variant === 'standalone', `standalone fallback variant expected, got ${state.variant}`);
  }

  // 2. While open, an App-level Ctrl+K is swallowed.
  const palette = await dispatchKey('[aria-label="搜索快捷键"]', { key: 'k', code: 'KeyK', ctrlKey: true });
  await sleep(120);
  state = await capture('02-overlay-blocks-app-shortcut');
  expect(palette.defaultPrevented === true, 'Ctrl+K inside open reference must be defaultPrevented');
  expect(state.appGlobalCount === appGlobalBaseline, `App-level Ctrl+K must not fire (count ${state.appGlobalCount} != ${appGlobalBaseline})`);

  // 3. Second primary+/ closes the top modal.
  await dispatchKey('[aria-label="搜索快捷键"]', { key: '/', code: 'Slash', ctrlKey: true });
  await sleep(150);
  state = await capture('03-toggle-close');
  expect(state.overlay === false, 'second Ctrl+/ must close the reference');

  // 4. Visible Settings entry + Settings stacking.
  await clickSelector('#open-settings');
  await waitFor(SETTINGS_OPEN, 'settings dialog open');
  await waitFor("Boolean(document.querySelector('[data-open-shortcut-reference]'))", 'settings visible entry');
  state = await capture('04-settings-open');
  expect(state.settingsOpen === true, 'settings dialog must be open');
  await clickSelector('[data-open-shortcut-reference]');
  await waitFor(OVERLAY, 'embedded overlay');
  await sleep(180);
  state = await capture('05-embedded-open');
  expect(state.overlay === true, 'visible Settings entry must open the reference');
  expect(state.variant === 'embedded', `embedded variant expected, got ${state.variant}`);
  expect(state.overlayInsideSettings === true, 'reference must be portalled inside the Settings dialog');
  expect(state.rowCount > 10, `catalog rows expected, got ${state.rowCount}`);

  // 5. Search filters the real catalog.
  await setSearch('差异');
  await sleep(180);
  state = await capture('06-search-diff');
  expect(state.rowCount > 0 && state.rowCount < 10, `diff search should narrow rows, got ${state.rowCount}`);
  expect((state.visibleRows || []).every((action) => String(action).includes('diff') || action === 'openDiff'), `diff search leaked rows: ${JSON.stringify(state.visibleRows)}`);
  await setSearch('');
  await sleep(120);

  // 6. Inline recording persists through KeybindingsSync -> real u6 router.
  const recordTarget = '[data-shortcut-reference] button[aria-label="修改「搜索与命令」的第 1 组快捷键"]';
  const recordClick = await clickSelector(recordTarget);
  expect(recordClick.ok === true, `overlay record target missing: ${JSON.stringify(recordClick)}`);
  await sleep(150);
  const recordResult = await dispatchKey(recordTarget, { key: 'u', code: 'KeyU', ctrlKey: true, altKey: true });
  expect(recordResult.ok === true && recordResult.defaultPrevented === true, `overlay record keydown not captured: ${JSON.stringify(recordResult)}`);
  await waitFor("Boolean(document.querySelector('[data-shortcut-reference] [role=\"status\"]')?.textContent?.includes('已保存'))||Boolean(document.querySelector('[data-shortcut-reference] [role=\"status\"]')?.textContent?.includes('已设置'))", 'recording saved status');
  await sleep(200);
  state = await capture('07-overlay-recorded');
  const cache = state.localCache ? JSON.parse(state.localCache) : null;
  expect(cache?.palette?.[0] === 'Ctrl+Alt+U', `local cache palette expected Ctrl+Alt+U, got ${JSON.stringify(cache?.palette)}`);
  const filePath = path.join(runDir, 'data-root', 'data', 'keybindings.json');
  const file = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  expect(file.palette?.[0] === 'Ctrl+Alt+U', `keybindings.json palette expected Ctrl+Alt+U, got ${JSON.stringify(file.palette)}`);
  expect(file.settings?.[0] === 'Ctrl+,', `keybindings.json must keep the settings default, got ${JSON.stringify(file.settings)}`);
  fs.copyFileSync(filePath, path.join(outDir, 'par10-t6-11-electron-keybindings-after.json'));

  // 7. Close the reference, then prove an active Settings recorder suppresses primary+/.
  await dispatchKey('[aria-label="搜索快捷键"]', { key: 'Escape', code: 'Escape' });
  await sleep(150);
  state = await capture('08-reference-closed');
  expect(state.overlay === false, 'Escape must close the reference');
  // Record Ctrl+/ into the *newTask* row: the panel's own recorder captures the
  // combo (defaultPrevented), proving the global reference toggle stays out of
  // the way instead of opening a second modal. Palette keeps Ctrl+Alt+U.
  await clickSelector('[data-settings-content] button[aria-label="修改「新任务」的第 1 组快捷键"]');
  await sleep(120);
  const suppressed = await dispatchKey('[data-settings-content] button[aria-label="修改「新任务」的第 1 组快捷键"]', { key: '/', code: 'Slash', ctrlKey: true });
  await sleep(250);
  state = await capture('09-recording-suppressed');
  expect(suppressed.defaultPrevented === true, 'recorder must receive the Ctrl+/ keydown (defaultPrevented by its own handler)');
  expect(state.overlay === false, 'primary+/ during recording must not open the reference');
  expect(state.blockedReason === null, 'recording suppression must not show a modal block');
  const cachedAfterRecord = state.localCache ? JSON.parse(state.localCache) : null;
  expect(cachedAfterRecord?.newTask?.[0] === 'Ctrl+/', `recorder should capture Ctrl+/, got ${JSON.stringify(cachedAfterRecord?.newTask)}`);
  // Restore newTask so the final device file only carries the intended edit.
  await clickSelector('[data-settings-content] button[aria-label="恢复「新任务」的默认快捷键"]');
  await sleep(250);

  // 8. Close Settings; stacked reference disconnects cleanly.
  await clickSelector('[aria-label="关闭设置"]');
  await waitFor(`!${SETTINGS_OPEN}`, 'settings closed');
  await sleep(200);
  state = await capture('10-settings-closed');
  expect(state.settingsOpen === false, 'settings must be closed');
  expect(state.overlay === false, 'closing settings must not leave a reference portal behind');

  // 9. Another dialog blocks with reason modal.
  await clickSelector('#open-other');
  await waitFor("Boolean(document.querySelector('[aria-label=\"其它模态\"]'))", 'other modal open');
  await dispatchKey(null, { key: '/', code: 'Slash', ctrlKey: true });
  await waitFor(BLOCKED_VISIBLE, 'modal blocked notice');
  await sleep(120);
  state = await capture('11-blocked-modal');
  expect(state.overlay === false, 'other dialog must block the reference');
  expect(state.blockedReason === 'modal', `blocked reason expected modal, got ${state.blockedReason}`);
  expect(String(state.blockedText).includes('modal'), 'blocked notice must explain the modal reason');
  await clickSelector('#open-other');
  await waitFor("!Boolean(document.querySelector('[aria-label=\"其它模态\"]'))", 'other modal closed');
  await sleep(120);

  // 10. After the other dialog closes, primary+/ opens; while open Ctrl+, is swallowed.
  await dispatchKey(null, { key: '/', code: 'Slash', ctrlKey: true });
  await waitFor(OVERLAY, 'overlay after modal cleared');
  const settingsKey = await dispatchKey('[aria-label="搜索快捷键"]', { key: ',', code: 'Comma', ctrlKey: true });
  await sleep(120);
  state = await capture('12-overlay-blocks-settings-key');
  expect(settingsKey.defaultPrevented === true, 'Ctrl+, inside open reference must be defaultPrevented');
  expect(state.appGlobalCount === appGlobalBaseline, `App-level Ctrl+, must not fire (count ${state.appGlobalCount} != ${appGlobalBaseline})`);
  await dispatchKey('[aria-label="搜索快捷键"]', { key: 'Escape', code: 'Escape' });
  await sleep(150);
  state = await capture('13-final-tasks-closed');
  expect(state.overlay === false, 'reference must be closed at the end');

  // 11. Server-side final state (real GET through the page).
  await clickSelector('#open-settings');
  await waitFor(SETTINGS_OPEN, 'settings reopen for final anchor check');
  await clickSelector('[data-open-shortcut-reference]');
  await waitFor(OVERLAY, 'embedded overlay reopen');
  await clickSelector('[aria-label="关闭设置"]');
  await waitFor(`!${SETTINGS_OPEN}`, 'settings closed with overlay stacked');
  await waitFor(`!${OVERLAY}`, 'overlay closed when anchor disconnects', 5000);
  state = await capture('14-anchor-disconnect');
  expect(state.overlay === false && state.settingsOpen === false, 'anchor disconnect must close the reference');

  const finalServer = await evalJs("fetch('/api/u6/keybindings', {cache: 'no-store'}).then((response) => response.json())");
  expect(finalServer?.bindings?.palette?.[0] === 'Ctrl+Alt+U', `server palette expected Ctrl+Alt+U, got ${JSON.stringify(finalServer?.bindings?.palette)}`);
  expect(finalServer?.revision, 'server must return a content revision');

  const summary = {
    result: problems.length === 0 ? 'PASS' : 'FAIL',
    electron: process.versions.electron,
    chrome: process.versions.chrome,
    url,
    userData,
    openedByRealInput,
    steps,
    finalServer,
    problems,
  };
  fs.writeFileSync(path.join(outDir, 'par10-t6-11-electron-summary.json'), JSON.stringify(summary, null, 2));
  log(`result=${summary.result} problems=${problems.length} realInput=${openedByRealInput}`);
  return problems.length === 0 ? 0 : 1;
}

app.whenReady().then(async () => {
  let code = 3;
  try {
    code = await main();
  } catch (error) {
    problems.push(String(error && error.stack ? error.stack : error));
    console.error(error);
    try {
      const image = await win?.capturePage();
      if (image) fs.writeFileSync(path.join(outDir, 'par10-t6-11-electron-failure.png'), image.toPNG());
    } catch { /* ignore */ }
    fs.writeFileSync(path.join(outDir, 'par10-t6-11-electron-summary.json'), JSON.stringify({ result: 'FAIL', problems, steps }, null, 2));
    code = 1;
  }
  app.exit(code);
});