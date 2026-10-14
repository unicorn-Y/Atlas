// Measures the real Electron dev app, backend readiness, and first assistant text.
// Usage: node scripts/diag/boot_timing.mjs [--repeats 5] [--output path] [--prompt text]
// One unmeasured launch warms the OS/Vite/Electron caches; then `repeats` measured restarts.
// This does not claim to measure a packaged installer's cold boot or ZCode.
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, isAbsolute, join, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';

const ROOT = resolve(fileURLToPath(new URL('../..', import.meta.url)));
const FRONTEND = join(ROOT, 'frontend');
const REQUIRE = createRequire(join(FRONTEND, 'package.json'));
const WAIT_MS = 200;
const HEALTH_URL = process.env.ATLAS_BOOT_HEALTH_URL ?? 'http://127.0.0.1:8765/api/health';
const DEFAULT_PROMPT = 'Reply with exactly the word BOOT_OK.';

function optionsFrom(argv) {
  const options = { repeats: 5, prompt: DEFAULT_PROMPT, output: null, vitePort: 5173 };
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i];
    if (key === '--repeats') options.repeats = Number(argv[++i]);
    else if (key === '--prompt') options.prompt = argv[++i];
    else if (key === '--output') options.output = argv[++i];
    else if (key === '--vite-port') options.vitePort = Number(argv[++i]);
    else if (key === '--help' || key === '-h') {
      console.log('Usage: node scripts/diag/boot_timing.mjs [--repeats 5] [--prompt text] [--output path] [--vite-port 5173]');
      process.exit(0);
    } else throw new Error(`Unknown argument: ${key}`);
  }
  if (!Number.isInteger(options.repeats) || options.repeats < 1 || options.repeats > 20) {
    throw new Error('--repeats must be an integer from 1 to 20');
  }
  if (!Number.isInteger(options.vitePort) || options.vitePort < 1024 || options.vitePort > 65535) {
    throw new Error('--vite-port must be an integer from 1024 to 65535');
  }
  if (!options.prompt?.trim()) throw new Error('--prompt must not be empty');
  return options;
}

const sleep = (ms) => new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
async function portBusy(port) {
  return new Promise((resolveBusy) => {
    const server = createServer();
    server.once('error', () => resolveBusy(true));
    server.listen(port, '127.0.0.1', () => server.close(() => resolveBusy(false)));
  });
}
async function freePort() {
  return new Promise((resolvePort) => {
    const server = createServer();
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      server.close(() => resolvePort(port));
    });
  });
}
async function waitFor(predicate, timeoutMs, label) {
  const deadline = performance.now() + timeoutMs;
  let lastError;
  while (performance.now() < deadline) {
    try {
      const value = await predicate();
      if (value) return value;
    } catch (error) { lastError = error; }
    await sleep(WAIT_MS);
  }
  throw new Error(`${label} timed out${lastError ? `: ${lastError.message}` : ''}`);
}
async function waitHttp(url, timeoutMs, label, accept = (response) => response.ok) {
  return waitFor(async () => {
    const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
    if (accept(response)) return response;
    return null;
  }, timeoutMs, label);
}
function median(values) {
  const ordered = [...values].sort((a, b) => a - b);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 ? ordered[middle] : (ordered[middle - 1] + ordered[middle]) / 2;
}
async function terminateVite(child) {
  if (child.exitCode !== null || child.killed) return;
  child.kill();
  await Promise.race([new Promise((done) => child.once('exit', done)), sleep(3_000)]);
}

async function terminateElectron(child) {
  if (child.exitCode !== null || child.killed) return;
  if (process.platform === 'win32' && child.pid) {
    const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
    await new Promise((done) => killer.once('exit', done));
  } else child.kill('SIGTERM');
  await Promise.race([new Promise((done) => child.once('exit', done)), sleep(8_000)]);
  if (child.exitCode === null) child.kill('SIGKILL');
}

async function connectCdp(port, timeoutMs = 30_000) {
  const target = await waitFor(async () => {
    const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(1_000) });
    const pages = await response.json();
    return pages.find((item) => item.type === 'page' && item.webSocketDebuggerUrl);
  }, timeoutMs, 'Electron CDP page target');
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolveSocket, rejectSocket) => {
    socket.addEventListener('open', resolveSocket, { once: true });
    socket.addEventListener('error', () => rejectSocket(new Error('Could not connect to Electron CDP')), { once: true });
  });
  let nextId = 0;
  const pending = new Map();
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    const deferred = pending.get(message.id);
    if (!deferred) return;
    pending.delete(message.id);
    if (message.error) deferred.reject(new Error(message.error.message));
    else deferred.resolve(message.result);
  });
  const call = (method, params = {}) => new Promise((resolveCall, rejectCall) => {
    const id = ++nextId;
    pending.set(id, { resolve: resolveCall, reject: rejectCall });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async (expression) => {
    const response = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text ?? 'CDP evaluate failed');
    return response.result?.value;
  };
  return { call, evaluate, close: () => socket.close() };
}

async function main() {
  const options = optionsFrom(process.argv.slice(2));
  if (!existsSync(join(FRONTEND, 'node_modules', 'vite'))) throw new Error('Frontend dependencies are missing; run npm install first.');
  if (await portBusy(options.vitePort)) throw new Error(`Vite port ${options.vitePort} is already in use; choose --vite-port or stop its owner.`);
  if (await portBusy(8765)) throw new Error('Backend port 8765 is already in use. Stop the existing Atlas/backend first to avoid measuring an unrelated instance.');

  const viteBin = [join(FRONTEND, 'node_modules', 'vite', 'bin', 'vite.js'), join(ROOT, 'node_modules', 'vite', 'bin', 'vite.js')]
    .find((candidate) => existsSync(candidate));
  if (!viteBin) throw new Error('Vite installation not found');
  const viteUrl = `http://127.0.0.1:${options.vitePort}`;
  const vite = spawn(process.execPath, [viteBin, '--host', '127.0.0.1', '--port', String(options.vitePort), '--strictPort'], {
    cwd: FRONTEND, stdio: 'inherit', env: process.env,
  });
  const results = [];
  const environment = {
    mode: 'Electron development build; Vite remains warm across launches',
    health_url: HEALTH_URL,
    vite_url: viteUrl,
    prompt: options.prompt,
    measured_runs: options.repeats,
    warmup_runs: 1,
  };

  try {
    await waitHttp(viteUrl, 60_000, 'Vite server');
    // Build only Electron main/preload before timing; renderer source remains Vite-served.
    const build = spawn(process.execPath, ['scripts/build-preload.mjs'], {
      cwd: FRONTEND, stdio: 'inherit', env: process.env,
    });
    await new Promise((resolveBuild, rejectBuild) => {
      build.once('error', rejectBuild);
      build.once('exit', (code) => code === 0 ? resolveBuild() : rejectBuild(new Error(`build:preload exited ${code}`)));
    });
    const tscBin = [join(FRONTEND, 'node_modules', 'typescript', 'bin', 'tsc'), join(ROOT, 'node_modules', 'typescript', 'bin', 'tsc')]
      .find((candidate) => existsSync(candidate));
    if (!tscBin) throw new Error('TypeScript installation not found');
    const tsc = spawn(process.execPath, [tscBin, '-p', 'tsconfig.electron.json'], { cwd: FRONTEND, stdio: 'inherit', env: process.env });
    await new Promise((resolveBuild, rejectBuild) => {
      tsc.once('error', rejectBuild);
      tsc.once('exit', (code) => code === 0 ? resolveBuild() : rejectBuild(new Error(`Electron TypeScript build exited ${code}`)));
    });

    async function launchOne(index, measured) {
      const started = performance.now();
      const debugPort = await freePort();
      const electronBin = REQUIRE('electron');
      const app = spawn(electronBin, [FRONTEND, `--remote-debugging-port=${debugPort}`], {
        cwd: FRONTEND, stdio: 'inherit', env: { ...process.env, VITE_DEV_SERVER_URL: viteUrl },
      });
      let cdp;
      try {
        cdp = await connectCdp(debugPort, 120_000);
        await cdp.call('Runtime.enable');
        await waitFor(() => cdp.evaluate('document.visibilityState === "visible" && document.readyState !== "loading"'),
          60_000, 'visible Electron window');
        const windowMs = performance.now() - started;
        await waitHttp(HEALTH_URL, 300_000, 'Atlas /api/health ready', async (response) => {
          if (!response.ok) return false;
          try { return (await response.clone().json()).status === 'ok'; } catch { return false; }
        });
        const healthMs = performance.now() - started;
        const row = { run: index, window_ms: Math.round(windowMs), health_ready_ms: Math.round(healthMs) };
        if (measured) {
          await waitFor(() => cdp.evaluate('Boolean(document.querySelector(\'textarea[aria-label="消息内容"]\'))'), 60_000, 'chat composer');
          const baseline = await cdp.evaluate('[...document.querySelectorAll("[data-message-role=assistant]")].map((node) => node.textContent?.trim() ?? "")');
          const sentAt = performance.now();
          await cdp.evaluate('document.querySelector(\'textarea[aria-label="消息内容"]\').focus()');
          await cdp.call('Input.insertText', { text: options.prompt });
          await waitFor(() => cdp.evaluate(`(() => {
            const textarea = document.querySelector('textarea[aria-label="消息内容"]');
            const submit = document.querySelector('button[aria-label="发送消息"]');
            return textarea?.value === ${JSON.stringify(options.prompt)} && submit && !submit.disabled;
          })()`), 5_000, 'chat composer input');
          await cdp.evaluate('document.querySelector(\'button[aria-label="发送消息"]\').click()');
          await waitFor(() => cdp.evaluate(`(() => {
            const before = ${JSON.stringify(baseline)};
            const texts = [...document.querySelectorAll('[data-message-role="assistant"]')].map((node) => node.textContent?.trim() ?? '');
            return texts.some((text, index) => text.length > 0 && (index >= before.length || text !== before[index]));
          })()`), 180_000, 'first assistant stream text');
          row.submit_to_first_stream_ms = Math.round(performance.now() - sentAt);
          row.launch_to_first_stream_ms = Math.round(performance.now() - started);
        }
        return row;
      } finally {
        cdp?.close();
        await terminateElectron(app);
      }
    }

    console.log('[boot-timing] unmeasured warm-up launch');
    await launchOne(0, false);
    for (let run = 1; run <= options.repeats; run++) {
      console.log(`[boot-timing] measured launch ${run}/${options.repeats}`);
      results.push(await launchOne(run, true));
    }

    const report = {
      created_at: new Date().toISOString(),
      environment,
      results,
      medians_ms: {
        window_visible: Math.round(median(results.map((row) => row.window_ms))),
        backend_health_ready: Math.round(median(results.map((row) => row.health_ready_ms))),
        first_stream_text: Math.round(median(results.map((row) => row.launch_to_first_stream_ms))),
      },
      unmeasured: ['cold packaged startup (requires an independently controlled cold boot)', 'ZCode comparison (run same prompt/device/cache conditions manually)'],
      notes: [
        'The warm-up launch is excluded; Vite stays running while Electron and its managed backend are restarted.',
        'window_ms measures launch request to a visible Electron BrowserWindow using Playwright Electron automation.',
        'health_ready_ms is elapsed from launch request until /api/health returns status=ok.',
        'launch_to_first_stream_ms measures launch request until the first new non-empty assistant DOM text; submit_to_first_stream_ms isolates message/model latency.',
        'This exercises the development renderer and local data/configuration, not the packaged updater/installer path.',
      ],
    };
    const output = options.output ? (isAbsolute(options.output) ? options.output : resolve(ROOT, options.output)) : null;
    if (output) {
      mkdirSync(dirname(output), { recursive: true });
      writeFileSync(output, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
      console.log(`[boot-timing] report: ${output}`);
    }
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await terminateVite(vite);
  }
}

main().catch((error) => {
  console.error(`[boot-timing] ${error instanceof Error ? error.stack ?? error.message : String(error)}`);
  process.exitCode = 1;
});
