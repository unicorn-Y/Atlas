import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export interface BackendLaunchResult {
  ready: true;
  managed: boolean;
  pid?: number;
}

const HEALTH_URL = `http://127.0.0.1:${process.env.ATLAS_PORT ?? '8765'}/api/health`;
const PROBE_TIMEOUT_MS = 700;
const STARTUP_TIMEOUT_MS = 15_000;
const STDERR_TAIL_LIMIT = 8_192;

let managedChild: ChildProcess | null = null;
let stopPromise: Promise<void> | null = null;
const moduleDir = path.dirname(fileURLToPath(import.meta.url));

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function isBackendHealthy(): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS);
  try {
    const response = await fetch(HEALTH_URL, { signal: controller.signal });
    if (response.status !== 200) return false;
    const body: unknown = await response.json();
    return typeof body === 'object' && body !== null && 'status' in body && body.status === 'ok';
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
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

function pythonCandidates(): Array<{ command: string; args: string[] }> {
  const candidates: Array<{ command: string; args: string[] }> = [];
  if (process.env.ATLAS_PYTHON) candidates.push({ command: process.env.ATLAS_PYTHON, args: [] });
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
    env: process.env,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'],
  });

  let stderrTail = '';
  child.stdout?.on('data', () => undefined);
  child.stderr?.on('data', (chunk: Buffer | string) => {
    stderrTail = (stderrTail + chunk.toString()).slice(-STDERR_TAIL_LIMIT);
  });

  const outcome = new Promise<ProcessOutcome>((resolve) => {
    child.once('error', (error: NodeJS.ErrnoException) => resolve({ kind: 'error', error }));
    child.once('exit', (code, signal) => resolve({ kind: 'exit', code, signal }));
  });
  return { child, stderr: () => stderrTail, outcome };
}

async function waitUntilReady(child: ChildProcess, stderr: () => string, outcome: Promise<ProcessOutcome>): Promise<void> {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const probe = isBackendHealthy().then((healthy) => healthy ? { kind: 'ready' as const } : null);
    const result = await Promise.race([probe, outcome, sleep(250).then(() => null)]);
    if (result?.kind === 'ready') return;
    if (result?.kind === 'error') {
      if (result.error.code === 'ENOENT') throw result.error;
      throw new Error(`Atlas backend process failed: ${result.error.message}${stderr() ? `\n${stderr()}` : ''}`);
    }
    if (result?.kind === 'exit') {
      throw new Error(`Atlas backend exited before becoming healthy (code ${result.code ?? 'unknown'}, signal ${result.signal ?? 'none'}).${stderr() ? `\n${stderr()}` : ''}`);
    }
  }
  throw new Error(`Atlas backend did not become healthy within ${STARTUP_TIMEOUT_MS / 1000} seconds.${stderr() ? `\n${stderr()}` : ''}`);
}

async function terminate(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
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

export async function ensureBackendRunning(): Promise<BackendLaunchResult> {
  if (await isBackendHealthy()) return { ready: true, managed: false };

  const packagedBackend = process.env.ATLAS_BACKEND_EXECUTABLE;
  const rootDir = process.env.ATLAS_ROOT
    ? path.resolve(process.env.ATLAS_ROOT)
    : path.resolve(moduleDir, '../../..');
  const coreDir = packagedBackend ? rootDir : resolveCoreDir();
  const candidates: BackendCandidate[] = packagedBackend
    ? [{ command: packagedBackend, args: [], cwd: rootDir }]
    : pythonCandidates().map((candidate) => ({
      command: candidate.command,
      args: [...candidate.args, '-m', 'uvicorn', 'atlas.server:app', '--host', '127.0.0.1', '--port', process.env.ATLAS_PORT ?? '8765'],
      cwd: coreDir,
    }));
  let lastNotFound: NodeJS.ErrnoException | null = null;
  for (const candidate of candidates) {
    let started: Awaited<ReturnType<typeof startCandidate>> | null = null;
    try {
      started = await startCandidate(candidate.command, candidate.args, candidate.cwd);
      managedChild = started.child;
      await waitUntilReady(started.child, started.stderr, started.outcome);
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
