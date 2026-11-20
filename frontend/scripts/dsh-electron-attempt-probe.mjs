import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, '..');
const repoRoot = path.resolve(frontendRoot, '..');
const coreRoot = path.join(repoRoot, 'core');
const scenario = process.argv[2] ?? 'retry';
if (!['retry', 'fallback', 'max-output'].includes(scenario)) throw new Error('scenario must be retry, fallback or max-output');
const root = mkdtempSync(path.join(os.tmpdir(), 'atlas-electron-attempt-'));
const vitePort = 5191;
const viteUrl = `http://127.0.0.1:${vitePort}`;
const childEnv = {};
for (const key of ['PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'OS', 'PROCESSOR_ARCHITECTURE']) {
  if (process.env[key]) childEnv[key] = process.env[key];
}
for (const key of ['TEMP', 'TMP', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA']) {
  const directory = path.join(root, key.toLowerCase());
  mkdirSync(directory, { recursive: true });
  childEnv[key] = directory;
}
childEnv.HOME = childEnv.USERPROFILE;
childEnv.NO_PROXY = '127.0.0.1,localhost';
childEnv.no_proxy = childEnv.NO_PROXY;
childEnv.HTTP_PROXY = 'http://127.0.0.1:1';
childEnv.HTTPS_PROXY = childEnv.HTTP_PROXY;
childEnv.ALL_PROXY = childEnv.HTTP_PROXY;
childEnv.http_proxy = childEnv.HTTP_PROXY;
childEnv.https_proxy = childEnv.HTTP_PROXY;
childEnv.all_proxy = childEnv.HTTP_PROXY;

const python = process.env.PYTHON ?? 'python';
const backendScript = path.join(coreRoot, 'scripts', 'dsh_electron_attempt_backend.py');
const backend = spawn(python, [backendScript, root, String(vitePort), scenario], {
  cwd: coreRoot, env: { ...childEnv, PYTHONPATH: coreRoot }, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
});
const backendLines = [];
let backendStdout = '';
let backendStderr = '';
backend.stdout.setEncoding('utf8').on('data', (chunk) => { backendStdout += chunk; });
backend.stderr.setEncoding('utf8').on('data', (chunk) => { backendStderr += chunk; });
const backendReady = new Promise((resolve, reject) => {
  const deadline = setTimeout(() => reject(new Error('private backend ready deadline expired')), 45000);
  const inspect = () => {
    const lines = backendStdout.split(/\r?\n/);
    while (backendLines.length < lines.length - 1) {
      const raw = lines[backendLines.length];
      backendLines.push(raw);
      try {
        const item = JSON.parse(raw);
        if (item.ready) { clearTimeout(deadline); resolve(item); return; }
      } catch { /* structured log lines are ignored; no credentials are printed */ }
    }
    if (backend.exitCode !== null) { clearTimeout(deadline); reject(new Error(`private backend exited ${backend.exitCode}`)); }
  };
  backend.stdout.on('data', inspect);
  backend.on('exit', inspect);
});

let vite;
let app;
let backendInfo;
let backendDoneSent = false;
let conversationId = '';
const sentFrames = [];
const receivedAttemptFrames = [];
const terminalFrames = [];
const browserIssues = [];
const backendResponses = [];
let final = { root, vite_url: viteUrl };
let page = null;
let electronProcess = null;
let electronPid = null;

async function waitUntil(promise, deadline, label) {
  const remaining = deadline - Date.now();
  if (remaining <= 0) throw new Error(`${label} deadline expired`);
  let timer;
  try {
    return await Promise.race([
      Promise.resolve(promise),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} deadline expired`)), remaining);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function waitForExit(child, deadline, label) {
  if (child.exitCode !== null) return child.exitCode;
  const exited = new Promise((resolve) => child.once('exit', resolve));
  if (child.exitCode !== null) return child.exitCode;
  return waitUntil(exited, deadline, label);
}

async function forceOwnedTree(pid, label) {
  if (!Number.isInteger(pid) || pid <= 0) throw new Error(`invalid owned ${label} pid`);
  const killer = spawn('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
    windowsHide: true, stdio: 'ignore',
  });
  return waitForExit(killer, Date.now() + 5000, `${label} taskkill`);
}

try {
  backendInfo = await backendReady;
  final.api_url = backendInfo.api_url;
  final.api_port = backendInfo.api_port;
  if ([5173, 8765].includes(Number(backendInfo.api_port))) throw new Error('reserved service port selected');
  const viteClosePath = path.join(root, 'vite.close');
  const viteEnvDir = path.join(root, 'vite-env');
  mkdirSync(viteEnvDir, { recursive: true });
  const viteServerScript = path.join(here, 'dsh-electron-vite-server.mjs');
  vite = spawn(process.execPath, [viteServerScript, frontendRoot, String(vitePort), viteClosePath, viteEnvDir], {
    cwd: frontendRoot, env: childEnv, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
  });
  let viteReady = '';
  let viteStderr = '';
  const waitVite = new Promise((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error(`private Vite ready deadline expired; stdout=${viteReady.slice(-1000)}; stderr=${viteStderr.slice(-1000)}`)), 30000);
    vite.stdout.setEncoding('utf8').on('data', (chunk) => {
      viteReady += chunk;
      if (viteReady.replace(/\u001b\[[0-?]*[ -/]*[@-~]/g, '').includes(viteUrl)) {
        clearTimeout(timeout);
        resolve();
      }
    });
    vite.stderr.setEncoding('utf8').on('data', (chunk) => { viteStderr += chunk; });
    vite.on('exit', (code) => { clearTimeout(timeout); reject(new Error(`private Vite exited ${code}`)); });
  });
  await waitVite;

  const apiToken = 'atlas-electron-probe-token';
  const tokenPath = path.join(backendInfo.atlas_data_dir, 'data', 'runtime', 'api-token');
  mkdirSync(path.dirname(tokenPath), { recursive: true });
  writeFileSync(tokenPath, `${apiToken}\n`, { mode: 0o600 });
  const electronRoot = path.join(root, 'electron-user-data');
  mkdirSync(electronRoot, { recursive: true });
  const electron = await import('playwright').then((module) => module._electron);
  app = await electron.launch({
    executablePath: path.join(repoRoot, 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: [frontendRoot, '--no-sandbox', '--disable-gpu'],
    env: {
      ...childEnv,
      VITE_DEV_SERVER_URL: viteUrl,
      ATLAS_API_BASE_URL: backendInfo.api_url,
      ATLAS_PORT: String(backendInfo.api_port),
      ATLAS_API_TOKEN: apiToken,
      ATLAS_DATA_DIR: backendInfo.atlas_data_dir,
      ATLAS_DESKTOP_USER_DATA_DIR: electronRoot,
      ATLAS_SCHEDULER_ENABLED: 'false',
      ATLAS_AUTOMATION: '1',
      ELECTRON_DISABLE_SECURITY_WARNINGS: 'true',
    },
    timeout: 30000,
  });
  electronProcess = app.process();
  electronPid = electronProcess.pid;
  page = await app.firstWindow();
  page.on('console', (message) => {
    if (message.type() === 'error') browserIssues.push(`console:${message.text().slice(0, 300)}`);
  });
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText ?? 'unknown';
    browserIssues.push(`request:${request.url().split('?')[0]}:${failure.slice(0, 180)}`);
  });
  page.on('response', (response) => {
    const url = new URL(response.url());
    if (url.port === String(backendInfo.api_port)) {
      backendResponses.push({ path: url.pathname, status: response.status() });
      if (backendResponses.length > 100) backendResponses.shift();
      browserIssues.push(`response:${url.pathname}:${response.status()}`);
    }
  });
  await page.waitForLoadState('domcontentloaded');
  const actualUrl = page.url();
  if (!actualUrl.startsWith(viteUrl)) throw new Error(`Electron window URL mismatch: ${actualUrl}`);
  const connectedDeadline = Date.now() + 15000;
  let connectedText = '';
  while (Date.now() < connectedDeadline) {
    connectedText = await page.locator('body').innerText();
    const healthOk = backendResponses.some((item) => item.path === '/api/health' && item.status === 200);
    const configurationOk = backendResponses.some((item) => item.path === '/api/settings/configuration' && item.status === 200);
    const rejected = backendResponses.find((item) => [401, 403].includes(item.status));
    if (rejected) throw new Error(`Electron backend request denied at ${rejected.path} with HTTP ${rejected.status}`);
    if (healthOk && configurationOk) break;
    await page.waitForTimeout(200);
  }
  if (connectedText.includes('Atlas 后端没有连接')) {
    throw new Error(`Electron UI reports backend disconnected; responses=${JSON.stringify(backendResponses.slice(-12))}; issues=${JSON.stringify(browserIssues.slice(-12))}`);
  }
  if (!backendResponses.some((item) => item.path === '/api/health' && item.status === 200)
      || !backendResponses.some((item) => item.path === '/api/settings/configuration' && item.status === 200)) {
    throw new Error(`Electron did not complete the health+configuration handshake; responses=${JSON.stringify(backendResponses.slice(-20))}`);
  }
  page.on('websocket', (socket) => {
    socket.on('framesent', ({ payload }) => {
      if (typeof payload !== 'string') return;
      try {
        const item = JSON.parse(payload);
        if (item.type === 'run.start' && item.conversation_id) sentFrames.push(item.conversation_id);
      } catch { /* ignore non-JSON frames */ }
    });
    socket.on('framereceived', ({ payload }) => {
      if (typeof payload !== 'string') return;
      try {
        const item = JSON.parse(payload);
        if (['message.delta', 'message.rollback', 'message.completed'].includes(item.event)) {
          receivedAttemptFrames.push({ event: item.event, data: item.data ?? {} });
        }
        if (['run.completed', 'run.failed', 'run.cancelled'].includes(item.event)) {
          terminalFrames.push({ event: item.event, data: item.data ?? {} });
        }
      } catch { /* ignore non-JSON frames */ }
    });
  });
  const input = page.locator('textarea').last();
  await input.waitFor({ state: 'visible', timeout: 30000 });
  const expectedNewFragments = scenario === 'fallback'
    ? ['NEW fallback answer']
    : scenario === 'max-output'
      ? ['NEW answer', 'continuation completed']
      : ['NEW answer survives'];
  const expectedNew = expectedNewFragments.join('');
  const expectedOld = scenario === 'fallback' ? 'OLD filtered answer' : 'OLD answer';
  const expectedOldPrefix = scenario === 'fallback' ? expectedOld : 'OLD';
  await input.fill(`Return exactly ${expectedNew}.`);
  await input.press('Enter');
  const assistantContent = page.locator('[data-message-role="assistant"] [data-message-content]');
  const visibleDeadline = Date.now() + 60000;
  let assistantTexts = [];
  let terminalFrame = null;
  while (Date.now() < visibleDeadline) {
    assistantTexts = await assistantContent.allInnerTexts();
    const visibleText = assistantTexts.join('');
    terminalFrame = terminalFrames.at(-1) ?? null;
    if (terminalFrame && terminalFrame.event !== 'run.completed') {
      throw new Error(`renderer run ended without success: event=${terminalFrame.event}; category=${terminalFrame.data.category ?? 'unknown'}`);
    }
    if (expectedNewFragments.every((fragment) => visibleText.includes(fragment))
        && terminalFrame?.event === 'run.completed'
        && terminalFrame.data.result === 'completed') break;
    await page.waitForTimeout(100);
  }
  const visibleText = assistantTexts.join('');
  if (!expectedNewFragments.every((fragment) => visibleText.includes(fragment))
      || terminalFrame?.event !== 'run.completed'
      || terminalFrame.data.result !== 'completed') {
    throw new Error(`renderer run did not reach visible successful terminal before deadline: fragments=${expectedNewFragments.join('|')}; assistant_chars=${assistantTexts.map((text) => text.length).join(',')}; terminal=${terminalFrame?.event ?? 'missing'}`);
  }
  if (assistantTexts.some((text) => text.includes(expectedOldPrefix))) throw new Error('discarded OLD attempt text leaked into an assistant message');
  const rollbackIndex = receivedAttemptFrames.findIndex((item) => item.event === 'message.rollback');
  const rollbackAttemptId = rollbackIndex >= 0 ? receivedAttemptFrames[rollbackIndex].data.attempt_id : '';
  if (!rollbackAttemptId) throw new Error('renderer WebSocket did not receive a rollback attempt identity');
  const oldDeltas = receivedAttemptFrames.slice(0, rollbackIndex).filter(
    (item) => item.event === 'message.delta' && item.data.attempt_id === rollbackAttemptId,
  );
  const newDeltas = receivedAttemptFrames.slice(rollbackIndex + 1).filter(
    (item) => item.event === 'message.delta' && item.data.attempt_id !== rollbackAttemptId,
  );
  if (!oldDeltas.length || !newDeltas.length) throw new Error('renderer did not receive OLD→rollback→NEW frames');
  const oldStream = oldDeltas.map((item) => String(item.data.content ?? '')).join('');
  const newStream = newDeltas.map((item) => String(item.data.content ?? '')).join('');
  if (!oldStream.startsWith(expectedOldPrefix)
      || !expectedNewFragments.every((fragment) => newStream.includes(fragment))) {
    throw new Error(`renderer attempt frames do not reconstruct expected content: old_chars=${oldStream.length}, new_chars=${newStream.length}`);
  }
  if (sentFrames.length === 0) throw new Error('no runtime WebSocket run.start observed from Electron');
  conversationId = sentFrames.at(-1) ?? '';
  if (!conversationId) throw new Error('no runtime WebSocket run.start observed from Electron');
  writeFileSync(backendInfo.done_path, JSON.stringify({ conversation_id: conversationId }), 'utf8');
  backendDoneSent = true;
  final = { ...final, status: 'ui_pass', scenario, window_url: actualUrl, conversation_id: conversationId,
    visible_new: true, visible_old: false, rollback_seen: true,
    run_terminal_event: terminalFrame.event, run_result: terminalFrame.data.result,
    old_stream_chars: oldStream.length, new_stream_chars: newStream.length, electron_exit_code: null,
    backend_responses: backendResponses.slice(-20), browser_issues: browserIssues.slice(-12) };
} catch (error) {
  final.status = 'error';
  final.error = String(error?.stack ?? error);
  final.sent_run_start_count = sentFrames.length;
  final.backend_responses = backendResponses.slice(-20);
  final.browser_issues = browserIssues.slice(-12);
} finally {
  if (backendInfo && !backendDoneSent) {
    writeFileSync(backendInfo.done_path, JSON.stringify({ conversation_id: conversationId }), 'utf8');
    backendDoneSent = true;
  }
  if (app && electronProcess && electronPid) {
    try {
      const electronDeadline = Date.now() + 12000;
      if (!page) throw new Error('Electron page handle unavailable for graceful quit');
      const quitAccepted = await waitUntil(
        page.evaluate(() => window.atlasDesktop.requestQuit()),
        electronDeadline,
        'Electron requestQuit',
      );
      if (!quitAccepted) throw new Error('Electron explicit quit request was rejected');
      final.electron_exit_code = await waitForExit(electronProcess, electronDeadline, 'Electron process exit');
      final.electron_cleanup = 'window.atlasDesktop.requestQuit → main-process before-quit cleanup';
      if (final.electron_exit_code !== 0) {
        final.status = 'error';
        final.electron_close_error = `Electron exited with code ${final.electron_exit_code}`;
      }
    } catch (error) {
      final.status = 'error';
      final.electron_close_error = String(error);
      try {
        final.electron_taskkill_exit_code = await forceOwnedTree(electronPid, 'Electron');
        final.electron_cleanup = 'forced taskkill of captured isolated Electron tree after graceful deadline';
      } catch (killError) {
        final.electron_cleanup_error = String(killError);
      }
    }
  }
  if (vite && vite.exitCode === null) {
    writeFileSync(path.join(root, 'vite.close'), 'close\n', 'utf8');
    try {
      final.vite_exit_code = await waitForExit(vite, Date.now() + 10000, 'Vite graceful exit');
      final.vite_cleanup = 'close marker → Vite server.close() → helper process exit';
      if (final.vite_exit_code !== 0) {
        final.status = 'error';
        final.vite_close_error = `Vite exited with code ${final.vite_exit_code}`;
      }
    } catch (error) {
      final.status = 'error';
      final.vite_close_error = String(error);
      try {
        final.vite_taskkill_exit_code = await forceOwnedTree(vite.pid, 'Vite');
        final.vite_cleanup = 'forced taskkill of owned Vite tree after graceful deadline';
      } catch (killError) {
        final.vite_cleanup_error = String(killError);
      }
    }
  } else if (vite) {
    final.vite_exit_code = vite.exitCode;
    final.vite_cleanup = 'Vite exited before cleanup phase';
    if (vite.exitCode !== 0) final.status = 'error';
  }
  try {
    await waitForExit(backend, Date.now() + 20000, 'backend helper exit');
  } catch (error) {
    final.status = 'error';
    final.backend_cleanup_error = String(error);
    try {
      final.backend_taskkill_exit_code = await forceOwnedTree(backend.pid, 'backend helper');
    } catch (killError) {
      final.backend_cleanup_error += `; forced cleanup failed: ${String(killError)}`;
    }
  }
  final.backend_exit_code = backend.exitCode;
  if (backend.exitCode !== 0) final.status = 'error';
  final.backend_stderr_tail = backendStderr.slice(-1200);
  console.log(JSON.stringify(final, null, 2));
}
if (final.status !== 'ui_pass') process.exitCode = 1;
