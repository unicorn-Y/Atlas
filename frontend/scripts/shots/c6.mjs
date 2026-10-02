// C6 screenshot pipeline: isolated backend + fake LLM + vite dev + headless Edge.
// Produces five taskbook screenshots into artifacts/screenshots/c6/.
// Usage: node scripts/shots/c6.mjs
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { existsSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const FRONTEND = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const ROOT = resolve(FRONTEND, '..');
const PYTHON = join(ROOT, 'core', '.venv', 'Scripts', 'python.exe');
const OUT = join(ROOT, 'artifacts', 'screenshots', 'c6');
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
    try { const r = await fetch(url); if (r.ok) return; } catch { /* not up yet */ }
    await wait(300);
  }
  throw new Error(`${what} did not come up at ${url}`);
}

const children = [];
const die = async (err) => {
  console.error('[shots] failed:', err);
  for (const child of children.reverse()) { try { child.kill(); } catch { /* gone */ } }
  process.exit(1);
};

async function main() {
  const edge = EDGE_CANDIDATES.find((c) => existsSync(c));
  if (!edge) throw new Error('system Edge not found');
  mkdirSync(OUT, { recursive: true });
  const shotsRoot = mkdtempSync(join(tmpdir(), 'atlas-shots-'));
  const dataDir = join(shotsRoot, 'atlas');
  // 工作区必须放在仓库 _tmp 下：LSP 信任门控只放行 trusted_workspaces（D:\Atlas）内的目录，
  // 系统 temp 里的工作区会被静默关掉诊断。
  const workspace = join(ROOT, '_tmp', 'shots-workspace');
  mkdirSync(join(workspace, 'placeholder'), { recursive: true });

  // 1. Fake LLM first (its URL goes into the configs).
  const fake = spawn(PYTHON, [join(FRONTEND, 'scripts', 'shots', 'fake_llm.py'), workspace],
    { cwd: join(ROOT, 'core'), stdio: ['ignore', 'pipe', 'inherit'] });
  children.push(fake);
  const fakeUrl = await new Promise((done, fail) => {
    let buf = '';
    fake.stdout.on('data', (chunk) => {
      buf += chunk;
      const line = buf.split('\n').find((l) => l.trim().startsWith('http://'));
      if (line) done(line.trim());
    });
    fake.on('exit', (code) => fail(new Error(`fake llm exited: ${code}`)));
  });
  console.log('[shots] fake llm at', fakeUrl);

  // 2. Configs + workspace (after fake URL known). Backend boot overwrites nothing here;
  //    the DB is seeded afterwards exactly like the bench does.
  const prep = spawn(PYTHON, [join(FRONTEND, 'scripts', 'shots', 'seed_shots.py'), dataDir, workspace, fakeUrl], {
    cwd: join(ROOT, 'core'), stdio: 'inherit', env: { ...process.env, ATLAS_DATA_DIR: dataDir },
  });
  await new Promise((done, fail) => { prep.on('exit', (c) => (c === 0 ? done() : fail(new Error(`prep failed: ${c}`)))); });
  const seed = spawn(PYTHON, [join(FRONTEND, 'scripts', 'bench', 'seed_long.py'), dataDir], {
    cwd: join(ROOT, 'core'), stdio: 'inherit', env: { ...process.env, ATLAS_DATA_DIR: dataDir },
  });
  await new Promise((done, fail) => { seed.on('exit', (c) => (c === 0 ? done() : fail(new Error(`seed failed: ${c}`)))); });

  // 3. Isolated backend on a free port.
  const backendPort = await freePort();
  const backendLog = join(shotsRoot, 'backend.log');
  const backend = spawn(PYTHON, ['-m', 'uvicorn', 'atlas.server:app', '--host', '127.0.0.1', '--port', String(backendPort)], {
    cwd: join(ROOT, 'core'), stdio: ['ignore', 'ignore', 'pipe'],
    env: {
      ...process.env, ATLAS_DATA_DIR: dataDir, ATLAS_SCHEDULER_ENABLED: 'false',
      HERMES_HOME: join(dataDir, 'engine'), HERMES_TEST_MODE: '1',
      ATLAS_API_TOKEN: 'shots-token', NO_PROXY: '127.0.0.1,localhost',
    },
  });
  children.push(backend);
  backend.stderr && backend.stderr.pipe(existsSync(backendLog) ? process.stderr : process.stderr);
  await waitFor(`http://127.0.0.1:${backendPort}/api/health`, 90000, 'backend');

  // 4. Vite dev server on an OriginGuard-trusted dev port.
  const webPort = await (async () => {
    for (const c of [5173, 4173]) if (!(await portBusy(c))) return c;
    throw new Error('端口 5173/4173 都被占用，请先腾出一个');
  })();
  const viteBin = [join(FRONTEND, 'node_modules', 'vite', 'bin', 'vite.js'), join(ROOT, 'node_modules', 'vite', 'bin', 'vite.js')]
    .find((c) => existsSync(c));
  children.push(spawn(process.execPath, [viteBin, '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'], {
    cwd: FRONTEND, stdio: 'ignore', env: { ...process.env, VITE_API_BASE_URL: `http://127.0.0.1:${backendPort}` },
  }));
  await waitFor(`http://127.0.0.1:${webPort}/`, 60000, 'vite');

  // 5. Headless Edge.
  const playwrightEntry = [join(FRONTEND, 'node_modules', 'playwright-core'), join(ROOT, 'node_modules', 'playwright-core')]
    .map((base) => join(base, 'index.mjs')).find((c) => existsSync(c));
  if (!playwrightEntry) throw new Error('playwright-core not found');
  const { chromium } = await import(pathToFileURL(playwrightEntry).href);
  const browser = await chromium.launch({ executablePath: edge, headless: true });
  children.push({ kill: () => browser.close() });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('dialog', (dialog) => dialog.accept(workspace).catch(() => undefined));
  await page.addInitScript(() => { try { localStorage.setItem('atlas.preference.onboarded', 'true'); } catch { /* */ } });

  const shot = (name) => page.screenshot({ path: join(OUT, name) });
  const busy = () => page.evaluate(() => Boolean(window.__store?.getState()?.busy));
  const waitIdle = async (label, timeoutMs = 120000) => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (!(await busy().catch(() => true))) { await wait(800); if (!(await busy().catch(() => true))) return; }
      await wait(500);
    }
    const dump = await page.evaluate(() => {
      const state = window.__store?.getState?.() ?? {};
      const runs = state.runs ?? [];
      const last = runs[runs.length - 1] ?? null;
      return JSON.stringify({
        busy: state.busy, error: state.error,
        runCount: runs.length,
        lastRun: last ? { status: last.status, events: last.events?.slice(-6)?.map((e) => `${e.type}:${JSON.stringify(e.data ?? e).slice(0, 160)}`) } : null,
      }, null, 2);
    }).catch((e) => `dump failed: ${e}`);
    console.error('[shots] run stall dump:', dump);
    throw new Error(`run did not finish: ${label}`);
  };
  const send = async (text) => {
    await page.locator('textarea[aria-label="消息内容"]').click();
    await page.keyboard.insertText(text);
    await page.keyboard.press('Enter');
    await wait(1500);
  };

  const base = `http://127.0.0.1:${webPort}`;
  await page.goto(base, { waitUntil: 'commit' });
  await page.waitForSelector('textarea', { timeout: 60000 });
  await page.waitForTimeout(1500);
  for (let i = 0; i < 5; i += 1) {
    const overlays = await page.evaluate(() => [...document.querySelectorAll('div')]
      .filter((el) => typeof el.className === 'string' && el.className.includes('anim-fade') && el.className.includes('inset-0')).length);
    if (!overlays) break;
    await page.locator('div.anim-fade.fixed.inset-0').last().click({ force: true, position: { x: 5, y: 5 } }).catch(() => undefined);
    await wait(600);
  }
  const closeSettings = page.locator('button[aria-label="关闭设置"]');
  if (await closeSettings.count()) {
    await closeSettings.first().click({ timeout: 5000 }).catch(() => undefined);
    await page.waitForSelector('button[aria-label="关闭设置"]', { state: 'detached', timeout: 10000 }).catch(() => undefined);
  }
  await page.evaluate(`window.__atlas = import('/src/renderer/store/useAtlasStore.ts')`);
  await page.evaluate(async () => { window.__store = (await window.__atlas).useAtlasStore; });
  await page.waitForFunction(() => Boolean(window.__store?.getState().connected), { timeout: 60000 });
  console.log('[shots] app connected');

  // 6. 主聊天：先建会话并设置工作区（无头环境没有 atlasDesktop，直接走 store），
  //    再跑一次真实（假模型）运行 — 写 demo.py → LSP 诊断事件。
  await page.locator('button:has-text("新任务")').first().click();
  await wait(800);
  await page.evaluate((ws) => {
    const state = window.__store.getState();
    const id = state.activeConversationId ?? state.conversations?.[0]?.id;
    if (!id) throw new Error('no active conversation');
    window.__store.getState().setWorkspace(id, ws);
  }, workspace);
  await wait(400);
  await send('把演示代码写入 demo.py');
  await waitIdle('write run');
  await shot('1-chat-lsp.png');
  console.log('[shots] 1-chat-lsp done');

  // 6b. 改动面板（此时活动运行是写文件运行：diff + 诊断徽标）。
  await send('/diff');
  await wait(1500);
  await shot('3-changes.png');
  console.log('[shots] 3-changes done');
  const closeInspector = page.locator('button[aria-label="关闭检查器"], button[aria-label="收起检查器"]');
  if (await closeInspector.count()) { await closeInspector.first().click().catch(() => undefined); await wait(600); }

  // 7. review UI：/review → findings 卡片。
  await send('/review');
  await waitIdle('review run');
  await shot('2-review.png');
  console.log('[shots] 2-review done');

  // 8. 终端。
  const termTab = page.locator('button:has-text("终端")').first();
  if (await termTab.count()) { await termTab.click(); await wait(2500); await shot('4-terminal.png'); console.log('[shots] 4-terminal done'); }

  // 9. 设置页（高级面板里有 LSP 状态卡）。
  await page.keyboard.press('Control+,');
  await wait(1000);
  const advancedNav = page.locator('button:has-text("高级"), [class*="nav"] >> text=高级').first();
  if (await advancedNav.count()) { await advancedNav.click().catch(() => undefined); await wait(1500); }
  await shot('5-settings.png');
  console.log('[shots] 5-settings done');
  const closeSettings2 = page.locator('button[aria-label="关闭设置"]');
  if (await closeSettings2.count()) await closeSettings2.first().click({ timeout: 5000 }).catch(() => undefined);
  await wait(500);

  // 10. 大对话（2000 条）。
  await page.locator('button:has-text("长会话 A")').first().click();
  await page.waitForFunction(() => {
    const state = window.__store.getState();
    const loaded = (state.conversationMessages[state.activeConversationId] ?? []).length;
    return loaded >= 100 && document.querySelectorAll('[data-message-role]').length > 0;
  }, { timeout: 60000 });
  await wait(1500);
  await shot('6-long-conversation.png');
  console.log('[shots] 6-long-conversation done');

  console.log('[shots] all done →', OUT);
  for (const child of children.reverse()) { try { child.kill(); } catch { /* gone */ } }
}

main().catch(die);
