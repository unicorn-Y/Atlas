// Long-session benchmark: seeds an isolated backend with 2x2000-message conversations,
// boots the Atlas frontend (vite dev) against it, and measures with headless Edge:
//   1. cold open to interactive (thread painted + composer present)
//   2. conversation switch time (both directions, 6 switches)
//   3. streaming smoothness (300 deltas through the real store -> buffer -> React)
//   4. scroll-to-top pagination (loadEarlier)
// Usage: node scripts/bench/long-session.mjs
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { existsSync } from 'node:fs';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const FRONTEND = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const ROOT = resolve(FRONTEND, '..');
const PYTHON = join(ROOT, 'core', '.venv', 'Scripts', 'python.exe');
const EDGE_CANDIDATES = [
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
];

const freePort = () => new Promise((resolvePort) => {
  const server = createServer();
  server.listen(0, '127.0.0.1', () => { const { port } = server.address(); server.close(() => resolvePort(port)); });
});
const portBusy = (port) => new Promise((resolveBusy) => {
  const server = createServer();
  server.once('error', () => resolveBusy(true));
  server.listen(port, '127.0.0.1', () => server.close(() => resolveBusy(false)));
});
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
async function waitFor(url, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch { /* not up yet */ }
    await wait(300);
  }
  throw new Error(`${what} did not come up at ${url}`);
}

const results = { environment: {}, open_ms: null, switches_ms: [], streaming: null, pagination: null, notes: [] };
const children = [];
const dataDir = mkdtempSync(join(tmpdir(), 'atlas-bench-'));

async function main() {
  const edge = EDGE_CANDIDATES.find((candidate) => existsSync(candidate));
  if (!edge) throw new Error('system Edge not found');
  results.environment.edge = edge;

  // 1. Seed the isolated database (idempotent per fresh tmp dir). ATLAS_DATA_DIR keeps the
  //    user's own config/database out of this run entirely.
  const seed = spawn(PYTHON, [join(FRONTEND, 'scripts', 'bench', 'seed_long.py'), dataDir], {
    cwd: join(ROOT, 'core'), stdio: 'inherit', env: { ...process.env, ATLAS_DATA_DIR: dataDir },
  });
  await new Promise((done, fail) => { seed.on('exit', (code) => (code === 0 ? done() : fail(new Error(`seed failed: ${code}`)))); });

  // 2. Start an isolated backend on a free port (never 8765).
  const backendPort = await freePort();
  results.environment.backend_port = backendPort;
  children.push(spawn(PYTHON, ['-m', 'uvicorn', 'atlas.server:app', '--host', '127.0.0.1', '--port', String(backendPort)], {
    cwd: join(ROOT, 'core'), stdio: 'ignore', env: { ...process.env, ATLAS_DATA_DIR: dataDir },
  }));
  await waitFor(`http://127.0.0.1:${backendPort}/api/health`, 60000, 'backend');

  // 3. Start the vite dev server pointed at it. The backend's OriginGuard only trusts
  //    dev origins 5173/4173, so the browser has to be served from one of those ports.
  const webPort = await (async () => {
    for (const candidate of [5173, 4173]) if (!(await portBusy(candidate))) return candidate;
    throw new Error('端口 5173/4173 都被占用：后端只信任这两个开发来源，请先腾出一个再跑基准');
  })();
  results.environment.web_port = webPort;
  const viteBin = [join(FRONTEND, 'node_modules', 'vite', 'bin', 'vite.js'), join(ROOT, 'node_modules', 'vite', 'bin', 'vite.js')]
    .find((candidate) => existsSync(candidate));
  if (!viteBin) throw new Error('vite installation not found');
  children.push(spawn(process.execPath,
    [viteBin, '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'], {
      cwd: FRONTEND, stdio: 'ignore', env: { ...process.env, VITE_API_BASE_URL: `http://127.0.0.1:${backendPort}` },
    }));
  await waitFor(`http://127.0.0.1:${webPort}/`, 60000, 'vite');

  // 4. Headless Edge (playwright-core, like vite, may be hoisted to the repo root).
  const playwrightEntry = [join(FRONTEND, 'node_modules', 'playwright-core'), join(ROOT, 'node_modules', 'playwright-core')]
    .map((base) => join(base, 'index.mjs')).find((candidate) => existsSync(candidate));
  if (!playwrightEntry) throw new Error('playwright-core not found');
  const { chromium } = await import(pathToFileURL(playwrightEntry).href);
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  children.push({ kill: () => browser.close() });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  // 不弹首次向导（无 API key 的后端一定会触发它），只留右上角带关闭按钮的设置面板。
  await page.addInitScript(() => { try { localStorage.setItem('atlas.preference.onboarded', 'true'); } catch { /* ignore */ } });

  const base = `http://127.0.0.1:${webPort}`;
  await page.goto(base, { waitUntil: 'commit' });
  // 首次启动会叠两层对话框（设置面板 + 首次向导）；从最上层的遮罩角上点掉（点中心会点到卡片本身）。
  await page.waitForSelector('textarea', { timeout: 60000 });
  await page.waitForTimeout(1500);
  for (let i = 0; i < 5; i++) {
    const overlays = await page.evaluate(() => [...document.querySelectorAll('div')]
      .filter((el) => typeof el.className === 'string' && el.className.includes('anim-fade') && el.className.includes('inset-0')).length);
    if (!overlays) break;
    await page.locator('div.anim-fade.fixed.inset-0').last().click({ force: true, position: { x: 5, y: 5 } }).catch(() => undefined);
    await page.waitForTimeout(600);
  }
  const closeSettings = page.locator('button[aria-label="关闭设置"]');
  if (await closeSettings.count()) {
    await closeSettings.first().click({ timeout: 5000 }).catch(() => undefined);
    await page.waitForSelector('button[aria-label="关闭设置"]', { state: 'detached', timeout: 10000 }).catch(() => undefined);
  }
  await page.evaluate(`window.__atlas = import('/src/renderer/store/useAtlasStore.ts')`);
  await page.evaluate(async () => { window.__store = (await window.__atlas).useAtlasStore; });
  await page.waitForFunction(() => Boolean(window.__store?.getState().connected), { timeout: 60000 });

  // 5. Cold open of the long conversation: sidebar click -> page painted with history loaded.
  const t0 = Date.now();
  await page.locator('button:has-text("长会话 A")').first().click();
  await page.waitForFunction(() => {
    const state = window.__store.getState();
    const loaded = (state.conversationMessages[state.activeConversationId] ?? []).length;
    const painted = document.querySelectorAll('[data-message-role]').length;
    return loaded >= 100 && painted > 0 && Boolean(document.querySelector('textarea[aria-label="消息内容"]'));
  }, { timeout: 60000 });
  results.open_ms = Date.now() - t0;

  const state = await page.evaluate(() => {
    const current = window.__store.getState();
    return {
      activeId: current.activeConversationId,
      loaded: (current.conversationMessages[current.activeConversationId] ?? []).length,
      conversations: current.conversations.map((item) => ({ id: item.id, title: item.title })),
      hasEarlier: current.messagesHasEarlier[current.activeConversationId] ?? null,
    };
  });
  results.notes.push(`active conversation loaded ${state.loaded} messages (page size 100), hasEarlier=${state.hasEarlier}`);

  // 6. Conversation switches between the two long conversations.
  const others = state.conversations.filter((item) => item.id !== state.activeId);
  const sidebarButton = (title) => page.locator(`button:has-text("${title}")`).first();
  let fromTitle = '长会话 A';
  for (let i = 0; i < 6; i++) {
    const target = state.conversations.find((item) => item.title !== fromTitle) ?? others[0];
    const started = Date.now();
    await sidebarButton(target.title).click();
    await page.waitForFunction((id) => window.__store.getState().activeConversationId === id, target.id, { timeout: 30000 });
    await page.waitForFunction(() => {
      const current = window.__store.getState();
      return (current.conversationMessages[current.activeConversationId] ?? []).length > 0
        && document.querySelectorAll('[data-message-role]').length > 0;
    }, { timeout: 30000 });
    results.switches_ms.push(Date.now() - started);
    fromTitle = target.title;
  }

  // 7. Scroll-to-top pagination: pinned at top, earlier pages stream in progressively.
  results.pagination = await page.evaluate(async () => {
    const store = window.__store;
    const id = store.getState().activeConversationId;
    const before = (store.getState().conversationMessages[id] ?? []).length;
    const scroller = document.querySelector('[aria-label="任务活动"]');
    if (!scroller) return { ok: false, reason: 'scroller not found' };
    let after = before;
    let via = 'startReached';
    // 恢复滚动存档后高度估算还在收敛，顶部会被重新锚定；持续按在顶部直到开始翻页。
    for (let round = 0; round < 10 && after === before; round++) {
      scroller.scrollTop = 0;
      scroller.dispatchEvent(new Event('scroll'));
      await new Promise((resolveTick) => setTimeout(resolveTick, 400));
      after = (store.getState().conversationMessages[id] ?? []).length;
      if (after === before) {
        const button = [...document.querySelectorAll('button')].find((item) => item.textContent?.includes('载入更早的消息'));
        if (button) {
          via = 'button';
          button.click();
          await new Promise((resolveTick) => setTimeout(resolveTick, 600));
          after = (store.getState().conversationMessages[id] ?? []).length;
        }
      }
    }
    return {
      ok: after > before, before, after, via,
      scrollTop: scroller.scrollTop,
      rows: document.querySelectorAll('[data-message-role]').length,
      firstRow: document.querySelector('[data-message-role]')?.getAttribute('data-message-id') ?? null,
      stillLoading: store.getState().loadingEarlierConversationId === id,
      error: store.getState().error,
    };
  });

  // 6. Streaming: push 300 deltas through the real store at ~100 Hz; measure frame gaps.
  results.streaming = await page.evaluate(async () => {
    const store = window.__store;
    const conversationId = store.getState().activeConversationId;
    const run = store.getState().createRun(conversationId, 'bench-stream');
    const at = () => new Date().toISOString();
    store.getState().appendEvent({ id: `${run.id}:start`, runId: run.id, sequence: 1, type: 'run.started', timestamp: at(), data: { content: 'bench' } });
    await new Promise((resolveTick) => setTimeout(resolveTick, 300));
    const gaps = [];
    let last = performance.now();
    let running = true;
    const sampler = () => { if (!running) return; const now = performance.now(); gaps.push(now - last); last = now; requestAnimationFrame(sampler); };
    requestAnimationFrame(sampler);
    const chunk = '这是流式输出的一段内容，用来测量长会话流式时的帧稳定性，包含一些中文和 numbers 12345。';
    for (let i = 0; i < 300; i++) {
      store.getState().appendEvent({ id: `${run.id}:d${i}`, runId: run.id, sequence: i + 2, type: 'message.delta', timestamp: at(), data: { content: chunk } });
      await new Promise((resolveTick) => setTimeout(resolveTick, 10));
    }
    await new Promise((resolveTick) => setTimeout(resolveTick, 500));
    running = false;
    store.getState().removeRun(run.id);
    const sorted = [...gaps].sort((a, b) => a - b);
    const pick = (ratio) => sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * ratio))];
    return {
      frames: gaps.length,
      p50_ms: +pick(0.5).toFixed(1), p95_ms: +pick(0.95).toFixed(1), max_ms: +sorted[sorted.length - 1].toFixed(1),
      events_in_run: store.getState().runs.find((item) => item.id === run.id)?.events.length ?? 'run removed',
    };
  });

  const heap = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null);
  results.heap_after_mb = heap ? +(heap / 1048576).toFixed(1) : null;

  await browser.close();
  console.log('\n=== RESULTS (JSON) ===');
  console.log(JSON.stringify(results, null, 2));
}

main()
  .catch((error) => { console.error(error); process.exitCode = 1; })
  .finally(() => {
    for (const child of children) { try { child.kill(); } catch { /* already gone */ } }
    try { rmSync(dataDir, { recursive: true, force: true }); } catch { /* windows may hold the db briefly */ }
  });
