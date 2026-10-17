import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { BACKEND_STARTUP_CHANNEL, type BackendStartupProgress } from '../shared/ipc.js';

export interface BackendLaunchResult {
  ready: true;
  managed: boolean;
  pid?: number;
}

export interface EnsureBackendOptions {
  /** Receives startup progress while the backend boots (H8 §10.3: the UI shows progress). */
  onProgress?: (progress: BackendStartupProgress) => void;
}

const HEALTH_URL = `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}/api/health`;
const PROBE_TIMEOUT_MS = 700;
const PROBE_INTERVAL_MS = 250;
// H8 §10.3: the old fixed 15-second timeout killed slow-but-healthy backends. Now the
// wait continues while the process is alive and health makes progress; STARTUP_MAX_WAIT_MS
// is only the total upper bound. Real failures (process exit / spawn error) surface
// immediately with the log tail instead of waiting out a timer.
const STARTUP_MAX_WAIT_MS = 300_000; // first boot after an update loads ~57 plugins and npx MCP servers; 120 s was too short
// Real failures show the last lines of the backend log (H8 §10.3).
const LOG_TAIL_LINES = 50;
const PROGRESS_HEARTBEAT_MS = 1_000;
const STDERR_TAIL_LIMIT = 8_192;
const shutdownToken = randomBytes(32).toString('hex');
const PORT = Number(process.env.ATLAS_PORT ?? '8765');

let managedChild: ChildProcess | null = null;
let stopPromise: Promise<void> | null = null;
const stopReasons = new WeakMap<ChildProcess, string>();
const moduleDir = path.dirname(fileURLToPath(import.meta.url));

function dataRootDir(): string {
  return process.env.ATLAS_DATA_DIR
    ? path.resolve(process.env.ATLAS_DATA_DIR)
    : process.env.ATLAS_ROOT
      ? path.resolve(process.env.ATLAS_ROOT)
      : path.resolve(moduleDir, '../../..');
}

function runtimeDir(): string {
  return path.join(dataRootDir(), 'data', 'runtime');
}

export function getBackendLogPath(): string {
  return path.join(dataRootDir(), 'data', 'logs', 'backend-stdio.log');
}

function recordBackendLifecycle(event: string, fields: Record<string, unknown>): void {
  try {
    const logPath = getBackendLogPath();
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    fs.appendFileSync(logPath, `${JSON.stringify({ timestamp: new Date().toISOString(), event, ...fields })}\n`);
  } catch (error) {
    // An unavailable diagnostic sink must not prevent shutdown or mask an exit.
    console.error('Atlas backend lifecycle log unavailable', (error as NodeJS.ErrnoException).code);
  }
}

function loadSharedApiToken(): void {
  const tokenPath = path.join(runtimeDir(), 'api-token');
  try {
    const token = fs.readFileSync(tokenPath, 'utf8').trim();
    if (token) process.env.ATLAS_API_TOKEN = token;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Last N lines of the backend log, for failure reporting (H8 §10.3). */
function logTail(tail: string): string {
  const lines = tail.split(/\r?\n/).filter((line) => line.trim().length > 0);
  return lines.slice(-LOG_TAIL_LINES).join('\n');
}

interface HealthContact {
  /** Settled optional failures are usable, but retain degraded health diagnostics. */
  ready: boolean;
  /** Raw JSON body; used to detect progress between polls. */
  payload: unknown;
}

/** One health poll. Null means "no contact yet" (backend still booting or port not bound). */
async function probeHealth(): Promise<HealthContact | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(HEALTH_URL, { signal: controller.signal });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    const body = payload as { status?: unknown } | null;
    return { ready: response.status === 200 && (body?.status === 'ok' || body?.status === 'degraded'), payload };
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

/** Back-compat helper: is a backend fully ready right now? */
/** An Atlas health body (as opposed to some other service answering on the port). */
function isAtlasHealthPayload(payload: unknown): boolean {
  return typeof payload === 'object' && payload !== null
    && ('status' in payload || 'components' in payload);
}

async function isBackendHealthy(): Promise<boolean> {
  return (await probeHealth())?.ready ?? false;
}

/** Short progress line for the UI. Prefers the lifespan components report (H8 §10.2)
 *  once the backend exposes it; falls back to a generic "booting" line. */
function progressDetail(payload: unknown): string {
  const body = payload as {
    status?: unknown;
    components?: Record<string, string | { status?: unknown; error?: unknown } | undefined> | null;
    component_errors?: Record<string, string | undefined> | null;
  } | null;
  if (body && typeof body === 'object' && body.components && typeof body.components === 'object') {
    const pending = Object.entries(body.components)
      .map(([name, state]) => {
        const componentStatus = typeof state === 'string' ? state : state?.status;
        if (componentStatus === 'failed') {
          const detail = body.component_errors?.[name]
            ?? (typeof state === 'object' && typeof state?.error === 'string' ? state.error : undefined);
          return detail ? `${name}(failed: ${detail})` : `${name}(failed)`;
        }
        return componentStatus === 'starting' ? name : null;
      })
      .filter((name): name is string => name !== null);
    if (pending.length > 0) return `启动中：${pending.join('、')}`;
    return '组件已就绪，等待后端确认';
  }
  return '后端进程已启动，等待健康检查通过';
}

function resolveCoreDir(): string {
  const repoRoot = process.env.ATLAS_ROOT
    ? path.resolve(process.env.ATLAS_ROOT)
    : path.resolve(moduleDir, '../../..');
  const coreDir = path.join(repoRoot, 'core');
  if (!fs.existsSync(path.join(coreDir, 'atlas', 'server.py'))) {
    throw new Error(`Atlas backend was not found at ${path.join(coreDir, 'atlas', 'server.py')}. Set ATLAS_ROOT to the Atlas repository root.`);
  }
  return coreDir;
}

function pythonCandidates(coreDir: string): Array<{ command: string; args: string[] }> {
  const candidates: Array<{ command: string; args: string[] }> = [];
  if (process.env.ATLAS_PYTHON) candidates.push({ command: process.env.ATLAS_PYTHON, args: [] });
  const virtualenvPython = process.platform === 'win32'
    ? path.join(coreDir, '.venv', 'Scripts', 'python.exe')
    : path.join(coreDir, '.venv', 'bin', 'python');
  if (fs.existsSync(virtualenvPython)) candidates.push({ command: virtualenvPython, args: [] });
  candidates.push({ command: 'python', args: [] });
  if (process.platform === 'win32') candidates.push({ command: 'py', args: ['-3'] });
  return candidates;
}

interface BackendCandidate {
  command: string;
  args: string[];
  cwd: string;
}

type ProcessOutcome =
  | { kind: 'error'; error: NodeJS.ErrnoException }
  | { kind: 'exit'; code: number | null; signal: NodeJS.Signals | null };

async function startCandidate(
  command: string,
  args: string[],
  cwd: string,
): Promise<{ child: ChildProcess; stderr: () => string; outcome: Promise<ProcessOutcome> }> {
  const logDir = path.dirname(getBackendLogPath());
  fs.mkdirSync(logDir, { recursive: true });
  // Share one append-only descriptor for both pipes. Synchronous writes finish
  // before processing an exit event, so a crash cannot strand buffered traceback.
  const logFd = fs.openSync(getBackendLogPath(), 'a');
  let logClosed = false;
  const closeLog = () => {
    if (logClosed) return;
    logClosed = true;
    fs.closeSync(logFd);
  };
  const appendOutput = (chunk: Buffer | string) => {
    if (logClosed) return;
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    let offset = 0;
    while (offset < bytes.length) offset += fs.writeSync(logFd, bytes, offset, bytes.length - offset);
  };
  let child: ChildProcess;
  try {
    child = spawn(command, args, {
      cwd,
      env: { ...process.env, ATLAS_SHUTDOWN_TOKEN: shutdownToken },
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    closeLog();
    throw error;
  }
  recordBackendLifecycle('backend.process_spawn', {
    pid: child.pid ?? null, parent_pid: process.pid, executable: command,
  });
  // 'close' follows draining stdout/stderr; 'exit' may precede their last chunk.
  child.once('close', closeLog);

  let stderrTail = '';
  child.stdout?.on('data', (chunk: Buffer | string) => {
    appendOutput(chunk);
    if (process.env.ATLAS_DEBUG_BACKEND === '1') process.stderr.write(chunk);
  });
  child.stderr?.on('data', (chunk: Buffer | string) => {
    appendOutput(chunk);
    const text = chunk.toString();
    stderrTail = (stderrTail + text).slice(-STDERR_TAIL_LIMIT);
    if (process.env.ATLAS_DEBUG_BACKEND === '1') process.stderr.write(text);
  });

  const outcome = new Promise<ProcessOutcome>((resolve) => {
    child.once('error', (error: NodeJS.ErrnoException) => {
      recordBackendLifecycle('backend.process_error', {
        pid: child.pid ?? null, parent_pid: process.pid, code: error.code ?? null,
      });
      resolve({ kind: 'error', error });
    });
    child.once('exit', (code, signal) => {
      recordBackendLifecycle('backend.process_exit', {
        pid: child.pid ?? null, parent_pid: process.pid, code, signal,
        stop_reason: stopReasons.get(child) ?? null,
      });
      resolve({ kind: 'exit', code, signal });
    });
  });
  return { child, stderr: () => stderrTail, outcome };
}

async function waitUntilReady(
  child: ChildProcess,
  stderr: () => string,
  outcome: Promise<ProcessOutcome>,
  onProgress?: (progress: BackendStartupProgress) => void,
): Promise<void> {
  const startedAt = Date.now();
  const deadline = startedAt + STARTUP_MAX_WAIT_MS;
  let lastFingerprint: string | null = null;
  let lastHeartbeat = 0;
  const emit = (phase: BackendStartupProgress['phase'], detail?: string) => {
    onProgress?.({ phase, managed: true, elapsedMs: Date.now() - startedAt, detail });
  };

  while (Date.now() < deadline) {
    const probe = probeHealth().then((contact) => (contact ? { kind: 'health' as const, contact } : null));
    const result = await Promise.race([probe, outcome, sleep(PROBE_INTERVAL_MS).then(() => null)]);
    if (result?.kind === 'health') {
      if (result.contact.ready) {
        emit('ready');
        return;
      }
      // Any health response means the server is up and progressing; report changes
      // (component flips) plus a periodic heartbeat so the UI can show movement.
      const fingerprint = JSON.stringify(result.contact.payload);
      const now = Date.now();
      if (fingerprint !== lastFingerprint || now - lastHeartbeat >= PROGRESS_HEARTBEAT_MS) {
        lastFingerprint = fingerprint;
        lastHeartbeat = now;
        emit('starting', progressDetail(result.contact.payload));
      }
      // Pace the next poll: the race above resolves as soon as the probe does, so
      // without a delay a fast-responding "starting" health endpoint would be polled
      // in a hot loop. Process death still cuts the wait short immediately.
      await Promise.race([sleep(PROBE_INTERVAL_MS), outcome]);
      continue;
    }
    if (result?.kind === 'error') {
      emit('failed', `${result.error.message}${stderr() ? `\n${logTail(stderr())}` : ''}\n日志文件：${getBackendLogPath()}`);
      if (result.error.code === 'ENOENT') throw result.error;
      throw new Error(`Atlas backend process failed: ${result.error.message}${stderr() ? `\n${logTail(stderr())}` : ''}\n日志文件：${getBackendLogPath()}`);
    }
    if (result?.kind === 'exit') {
      emit('failed', `exit ${result.code ?? 'unknown'}${stderr() ? `\n${logTail(stderr())}` : ''}\n日志文件：${getBackendLogPath()}`);
      throw new Error(
        `Atlas backend exited before becoming healthy (code ${result.code ?? 'unknown'}, signal ${result.signal ?? 'none'}).` +
        `${stderr() ? `\n${logTail(stderr())}` : ''}\n日志文件：${getBackendLogPath()}`,
      );
    }
  }
  emit('failed', `no healthy backend within ${STARTUP_MAX_WAIT_MS / 1000}s${stderr() ? `\n${logTail(stderr())}` : ''}\n日志文件：${getBackendLogPath()}`);
  throw new Error(
    `Atlas backend did not become healthy within ${STARTUP_MAX_WAIT_MS / 1000} seconds.` +
    `${stderr() ? `\n${logTail(stderr())}` : ''}\n日志文件：${getBackendLogPath()}`,
  );
}

async function terminate(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3_000);
  try {
    const response = await fetch(new URL('/api/runtime/shutdown', HEALTH_URL), {
      method: 'POST',
      headers: { 'X-Atlas-Backend-Shutdown-Token': shutdownToken },
      signal: controller.signal,
    });
    if (response.status === 202 && await waitForExit(child, 15_000)) return;
  } catch {
    // Source-mode or older backends do not expose the packaged graceful-stop endpoint.
  } finally {
    clearTimeout(timeout);
  }
  if (process.platform === 'win32' && child.pid) {
    recordBackendLifecycle('backend.force_stop', { pid: child.pid, method: 'taskkill',
      reason: stopReasons.get(child) ?? null });
    await new Promise<void>((resolve) => {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
        windowsHide: true,
        stdio: 'ignore',
      });
      killer.once('error', () => resolve());
      killer.once('close', () => resolve());
    });
    return;
  }
  recordBackendLifecycle('backend.force_stop', { pid: child.pid ?? null, method: 'SIGTERM',
    reason: stopReasons.get(child) ?? null });
  child.kill('SIGTERM');
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return Promise.race([
    new Promise<boolean>((resolve) => child.once('exit', () => resolve(true))),
    sleep(timeoutMs).then(() => false),
  ]);
}

function readBackendPid(): number | null {
  try {
    const value = fs.readFileSync(path.join(runtimeDir(), 'backend.pid'), 'utf8').trim();
    const parsed = Number(value.startsWith('{') ? (JSON.parse(value) as { pid?: unknown }).pid : value);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
  } catch {
    return null;
  }
}

function processCommandLine(pid: number): string {
  try {
    if (process.platform === 'win32') {
      return execFileSync('powershell.exe', [
        '-NoProfile', '-NonInteractive', '-Command',
        `(Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}').CommandLine`,
      ], { encoding: 'utf8', windowsHide: true, timeout: 3_000 }).trim();
    }
    return fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').replace(/\0/g, ' ').trim();
  } catch {
    return '';
  }
}

function isAtlasBackendProcess(pid: number): boolean {
  const commandLine = processCommandLine(pid).toLowerCase();
  const packagedExecutable = process.env.ATLAS_BACKEND_EXECUTABLE?.toLowerCase();
  return commandLine.includes('atlas.desktop_entry')
    || commandLine.includes('atlasbackend')
    || Boolean(packagedExecutable && commandLine.includes(packagedExecutable.toLowerCase()));
}

function findListeningPid(): number | null {
  try {
    if (process.platform === 'win32') {
      const output = execFileSync('netstat.exe', ['-ano', '-p', 'tcp'], {
        encoding: 'utf8', windowsHide: true, timeout: 3_000,
      });
      const match = output.match(new RegExp(`^\\s*TCP\\s+\\S+:${PORT}\\s+\\S+\\s+LISTENING\\s+(\\d+)\\s*$`, 'im'));
      return match ? Number(match[1]) : null;
    }
    const output = execFileSync('sh', ['-lc', `lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t 2>/dev/null | head -1`], {
      encoding: 'utf8', timeout: 3_000,
    }).trim();
    const parsed = Number(output);
    return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
  } catch {
    return null;
  }
}

function processName(pid: number): string {
  try {
    if (process.platform === 'win32') {
      const output = execFileSync('tasklist.exe', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], {
        encoding: 'utf8', windowsHide: true, timeout: 3_000,
      }).trim();
      return output.split(',')[0]?.replace(/^"|"$/g, '') || '未知进程';
    }
    return path.basename(processCommandLine(pid).split(/\s+/)[0] || '') || '未知进程';
  } catch {
    return '未知进程';
  }
}

function pidIsRunning(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === 'EPERM';
  }
}

async function stopPreviousBackend(pid: number): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline && pidIsRunning(pid)) await sleep(250);
  if (!pidIsRunning(pid)) return;
  if (!isAtlasBackendProcess(pid)) {
    throw new Error(`data/runtime/backend.pid 指向 PID ${pid}，但无法确认它是 Atlas 后端；为避免结束无关进程，未执行 taskkill。`);
  }
  if (process.platform === 'win32') {
    recordBackendLifecycle('backend.force_stop', {
      pid, method: 'taskkill', reason: 'previous_backend_replacement',
    });
    await new Promise<void>((resolve) => {
      const killer = spawn('taskkill.exe', ['/PID', String(pid), '/T', '/F'], {
        windowsHide: true, stdio: 'ignore',
      });
      killer.once('error', () => resolve());
      killer.once('close', () => resolve());
    });
    const killedDeadline = Date.now() + 5_000;
    while (Date.now() < killedDeadline && pidIsRunning(pid)) await sleep(100);
  } else {
    try { process.kill(pid, 'SIGKILL'); } catch { /* The process may have exited between checks. */ }
  }
}

async function preparePreviousBackend(onProgress?: (progress: BackendStartupProgress) => void): Promise<boolean> {
  const pid = readBackendPid();
  const ownerPid = findListeningPid();
  if (ownerPid !== null && ownerPid !== pid) {
    // An Atlas health response without our pid file is still eligible for the
    // legacy attach path below; any other listener is a hard, named conflict.
    const contact = await probeHealth();
    if (!(contact && isAtlasHealthPayload(contact.payload))) {
      throw new Error(`端口 ${PORT} 已被 ${processName(ownerPid)} (PID ${ownerPid}) 占用。请关闭该程序后重试。`);
    }
  }
  if (pid === null || !pidIsRunning(pid)) return false;
  if (!isAtlasBackendProcess(pid)) {
    if (ownerPid === pid) {
      throw new Error(`端口 ${PORT} 由 ${processName(pid)} (PID ${pid}) 占用，backend.pid 指向的进程无法确认为 Atlas 后端。`);
    }
    return false;
  }

  if (ownerPid === pid && await externalAcceptsSessionToken()) {
    const contact = await probeHealth();
    if (contact?.ready) {
      return true;
    }
  }

  onProgress?.({ phase: 'starting', managed: false, elapsedMs: 0, detail: '等待上次启动的后端退出' });
  await stopPreviousBackend(pid);
  if (pidIsRunning(pid)) throw new Error(`Atlas 后端 (PID ${pid}) 在等待及强制结束后仍未退出。`);
  return false;
}

/**
 * An external backend is only usable if it accepts this session's API token: the
 * renderer's requests carry ``Origin: null`` plus the token Electron injects. A stale
 * dev backend (or another Atlas) on the port answers /api/health but rejects every
 * real request, which used to surface only as "cannot reach the backend".
 */
async function externalAcceptsSessionToken(): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3_000);
  try {
    const response = await fetch(HEALTH_URL.replace('/api/health', '/api/configuration'), {
      signal: controller.signal,
      headers: { Origin: 'null', 'X-Atlas-Api-Token': process.env.ATLAS_API_TOKEN ?? '' },
    });
    return response.status !== 401 && response.status !== 403;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

async function attachExternal(): Promise<BackendLaunchResult> {
  if (!(await externalAcceptsSessionToken())) {
    throw new Error(
      `端口 ${new URL(HEALTH_URL).port} 已被另一个 Atlas 后端占用，它不接受本窗口的访问令牌`
      + '（通常是没关掉的开发版后端）。请关闭那个进程后重新打开 Atlas。',
    );
  }
  return { ready: true, managed: false };
}

export { BACKEND_STARTUP_CHANNEL };

async function ensureBackendRunningImpl(options?: EnsureBackendOptions): Promise<BackendLaunchResult> {
  const onProgress = options?.onProgress;
  const startedAt = Date.now();
  const emit = (phase: BackendStartupProgress['phase'], managed: boolean, detail?: string) => {
    onProgress?.({ phase, managed, elapsedMs: Date.now() - startedAt, detail });
  };

  try {
    loadSharedApiToken();
    // Fast path (resident backend): a healthy Atlas that accepts our token is attached
    // without the netstat/PowerShell process checks below, which cost seconds on Windows.
    const live = await probeHealth();
    if (live?.ready && isAtlasHealthPayload(live.payload) && await externalAcceptsSessionToken()) {
      emit('ready', false, '复用已运行的 Atlas 后端');
      return { ready: true, managed: false, pid: readBackendPid() ?? undefined };
    }
    if (await preparePreviousBackend(onProgress)) {
      emit('ready', false, '复用已运行的 Atlas 后端');
      return { ready: true, managed: false, pid: readBackendPid() ?? undefined };
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    emit('failed', false, `${message}\n日志文件：${getBackendLogPath()}`);
    throw new Error(`${message}\n日志文件：${getBackendLogPath()}`);
  }

  emit('probing', false);
  // A busy backend (mid model-switch engine rebuild, heartbeat/automation tick
  // burst) can miss one probe, and an external backend may still be starting
  // its deferred components. Spawning a second backend then dies on the occupied
  // port and takes the window down with it, so: re-probe a few times, and once
  // an external backend answers at all, wait for it instead of spawning.
  let externalContact = false;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const probeStartedAt = Date.now();
    const contact = await probeHealth();
    if (contact?.ready) {
      const attached = await attachExternal();
      emit('ready', false);
      return attached;
    }
    if (contact && isAtlasHealthPayload(contact.payload)) {
      externalContact = true;
      break;
    }
    // Only a probe that ran into its timeout suggests a busy backend worth re-probing;
    // a refused connection means nothing is listening, so spawn right away.
    const timedOut = contact === null && Date.now() - probeStartedAt >= PROBE_TIMEOUT_MS;
    if (!timedOut) break;
    if (attempt < 2) await sleep(600);
  }
  if (externalContact) {
    const deadline = startedAt + STARTUP_MAX_WAIT_MS;
    while (Date.now() < deadline) {
      const contact = await probeHealth();
      if (contact?.ready) {
        const attached = await attachExternal();
        emit('ready', false);
        return attached;
      }
      emit('starting', false, contact ? progressDetail(contact.payload) : '等待已运行的后端响应');
      await sleep(PROBE_INTERVAL_MS);
    }
    emit('failed', false, `external backend not healthy within ${STARTUP_MAX_WAIT_MS / 1000}s\n日志文件：${getBackendLogPath()}`);
    throw new Error(
      `An Atlas backend is already running but did not become healthy within ${STARTUP_MAX_WAIT_MS / 1000} seconds.`,
    );
  }

  const packagedBackend = process.env.ATLAS_BACKEND_EXECUTABLE;
  const rootDir = process.env.ATLAS_ROOT
    ? path.resolve(process.env.ATLAS_ROOT)
    : path.resolve(moduleDir, '../../..');
  const coreDir = packagedBackend ? rootDir : resolveCoreDir();
  const candidates: BackendCandidate[] = packagedBackend
    ? [{ command: packagedBackend, args: [], cwd: rootDir }]
    : pythonCandidates(coreDir).map((candidate) => ({
      command: candidate.command,
      args: [...candidate.args, '-m', 'atlas.desktop_entry'],
      cwd: coreDir,
    }));
  let lastNotFound: NodeJS.ErrnoException | null = null;
  for (const candidate of candidates) {
    let started: Awaited<ReturnType<typeof startCandidate>> | null = null;
    try {
      started = await startCandidate(candidate.command, candidate.args, candidate.cwd);
      managedChild = started.child;
      emit('starting', true, '后端进程已启动，等待健康检查');
      await waitUntilReady(started.child, started.stderr, started.outcome, onProgress);
      return { ready: true, managed: true, pid: started.child.pid };
    } catch (error) {
      if (started) await stopManagedBackend('startup_failed');
      const spawnError = error as NodeJS.ErrnoException;
      if (spawnError.code === 'ENOENT') {
        lastNotFound = spawnError;
        continue;
      }
      throw error;
    }
  }
  const message = `Could not start the Atlas backend.${lastNotFound ? ` ${lastNotFound.message}` : ''}`;
  emit('failed', false, `${message}\n日志文件：${getBackendLogPath()}`);
  throw new Error(`${message}\n日志文件：${getBackendLogPath()}`);
}

/** Start or attach to the backend. Calling again after rejection is the retry API. */
export async function ensureBackendRunning(options?: EnsureBackendOptions): Promise<BackendLaunchResult> {
  const startedAt = Date.now();
  let lastPhase: BackendStartupProgress['phase'] | undefined;
  try {
    return await ensureBackendRunningImpl({
      ...options,
      onProgress: (progress) => {
        lastPhase = progress.phase;
        options?.onProgress?.(progress);
      },
    });
  } catch (error) {
    if (lastPhase !== 'failed') {
      const message = error instanceof Error ? error.message : String(error);
      options?.onProgress?.({
        phase: 'failed',
        managed: false,
        elapsedMs: Date.now() - startedAt,
        detail: `${message}\n日志文件：${getBackendLogPath()}`,
      });
    }
    throw error;
  }
}

export function stopManagedBackend(reason = 'app_quit'): Promise<void> {
  if (stopPromise) return stopPromise;
  const child = managedChild;
  managedChild = null;
  if (!child) return Promise.resolve();
  stopReasons.set(child, reason);
  recordBackendLifecycle('backend.stop_requested', { pid: child.pid ?? null, reason });
  stopPromise = terminate(child).finally(() => { stopPromise = null; });
  return stopPromise;
}
