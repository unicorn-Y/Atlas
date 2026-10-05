import { spawn, type ChildProcess } from 'node:child_process';
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
const STARTUP_MAX_WAIT_MS = 120_000;
// Real failures show the last lines of the backend log (H8 §10.3).
const LOG_TAIL_LINES = 50;
const PROGRESS_HEARTBEAT_MS = 1_000;
const STDERR_TAIL_LIMIT = 8_192;
const shutdownToken = randomBytes(32).toString('hex');

let managedChild: ChildProcess | null = null;
let stopPromise: Promise<void> | null = null;
const moduleDir = path.dirname(fileURLToPath(import.meta.url));

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Last N lines of the backend log, for failure reporting (H8 §10.3). */
function logTail(tail: string): string {
  const lines = tail.split(/\r?\n/).filter((line) => line.trim().length > 0);
  return lines.slice(-LOG_TAIL_LINES).join('\n');
}

interface HealthContact {
  /** True only when the backend reports itself fully ready (status === 'ok'). */
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
    return { ready: response.status === 200 && body?.status === 'ok', payload };
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
  const child = spawn(command, args, {
    cwd,
    env: { ...process.env, ATLAS_SHUTDOWN_TOKEN: shutdownToken },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stderrTail = '';
  child.stdout?.on('data', (chunk: Buffer | string) => {
    if (process.env.ATLAS_DEBUG_BACKEND === '1') process.stderr.write(chunk);
  });
  child.stderr?.on('data', (chunk: Buffer | string) => {
    const text = chunk.toString();
    stderrTail = (stderrTail + text).slice(-STDERR_TAIL_LIMIT);
    if (process.env.ATLAS_DEBUG_BACKEND === '1') process.stderr.write(text);
  });

  const outcome = new Promise<ProcessOutcome>((resolve) => {
    child.once('error', (error: NodeJS.ErrnoException) => resolve({ kind: 'error', error }));
    child.once('exit', (code, signal) => resolve({ kind: 'exit', code, signal }));
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
      emit('failed', result.error.message);
      if (result.error.code === 'ENOENT') throw result.error;
      throw new Error(`Atlas backend process failed: ${result.error.message}${stderr() ? `\n${logTail(stderr())}` : ''}`);
    }
    if (result?.kind === 'exit') {
      emit('failed', `exit ${result.code ?? 'unknown'}`);
      throw new Error(
        `Atlas backend exited before becoming healthy (code ${result.code ?? 'unknown'}, signal ${result.signal ?? 'none'}).` +
        `${stderr() ? `\n${logTail(stderr())}` : ''}`,
      );
    }
  }
  emit('failed', `no healthy backend within ${STARTUP_MAX_WAIT_MS / 1000}s`);
  throw new Error(
    `Atlas backend did not become healthy within ${STARTUP_MAX_WAIT_MS / 1000} seconds.` +
    `${stderr() ? `\n${logTail(stderr())}` : ''}`,
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
  child.kill('SIGTERM');
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<boolean> {
  if (child.exitCode !== null || child.signalCode !== null) return Promise.resolve(true);
  return Promise.race([
    new Promise<boolean>((resolve) => child.once('exit', () => resolve(true))),
    sleep(timeoutMs).then(() => false),
  ]);
}

export { BACKEND_STARTUP_CHANNEL };

export async function ensureBackendRunning(options?: EnsureBackendOptions): Promise<BackendLaunchResult> {
  const onProgress = options?.onProgress;
  const startedAt = Date.now();
  const emit = (phase: BackendStartupProgress['phase'], managed: boolean, detail?: string) => {
    onProgress?.({ phase, managed, elapsedMs: Date.now() - startedAt, detail });
  };

  emit('probing', false);
  // A busy backend (mid model-switch engine rebuild, heartbeat/automation tick
  // burst) can miss one probe, and an external backend may still be starting
  // its deferred components. Spawning a second backend then dies on the occupied
  // port and takes the window down with it, so: re-probe a few times, and once
  // an external backend answers at all, wait for it instead of spawning.
  let externalContact = false;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const contact = await probeHealth();
    if (contact?.ready) {
      emit('ready', false);
      return { ready: true, managed: false };
    }
    if (contact && isAtlasHealthPayload(contact.payload)) {
      externalContact = true;
      break;
    }
    if (attempt < 2) await sleep(600);
  }
  if (externalContact) {
    const deadline = startedAt + STARTUP_MAX_WAIT_MS;
    while (Date.now() < deadline) {
      const contact = await probeHealth();
      if (contact?.ready) {
        emit('ready', false);
        return { ready: true, managed: false };
      }
      emit('starting', false, contact ? progressDetail(contact.payload) : '等待已运行的后端响应');
      await sleep(PROBE_INTERVAL_MS);
    }
    emit('failed', false, `external backend not healthy within ${STARTUP_MAX_WAIT_MS / 1000}s`);
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
      if (started) await stopManagedBackend();
      const spawnError = error as NodeJS.ErrnoException;
      if (spawnError.code === 'ENOENT') {
        lastNotFound = spawnError;
        continue;
      }
      throw error;
    }
  }
  throw new Error(`Could not start the Atlas backend.${lastNotFound ? ` ${lastNotFound.message}` : ''}`);
}

export function stopManagedBackend(): Promise<void> {
  if (stopPromise) return stopPromise;
  const child = managedChild;
  managedChild = null;
  if (!child) return Promise.resolve();
  stopPromise = terminate(child).finally(() => { stopPromise = null; });
  return stopPromise;
}
