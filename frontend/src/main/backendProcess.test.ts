import { EventEmitter } from 'node:events';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { BackendStartupProgress } from '../shared/ipc.js';

// H8 §10.3 unit tests: slow starts are not killed, process exits surface immediately,
// the total cap still bounds the wait, and failure reports carry the log tail.
// Only `spawn` is replaced (partial mock keeps the worker's own child_process usable).
const h = vi.hoisted(() => ({ spawn: vi.fn() }));
vi.mock('node:child_process', async (importOriginal) => {
  const actual = await importOriginal<typeof import('node:child_process')>();
  return { ...actual, spawn: h.spawn };
});

import { ensureBackendRunning } from './backendProcess.js';

/** Repository root (this file lives at <root>/frontend/src/main/). */
const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');

interface FakeChild extends EventEmitter {
  stdout: EventEmitter;
  stderr: EventEmitter;
  pid: number;
  exitCode: number | null;
  signalCode: number | null;
  kill: ReturnType<typeof vi.fn>;
}

function makeChild(): FakeChild {
  const child = new EventEmitter() as FakeChild;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.pid = 4242;
  child.exitCode = null;
  child.signalCode = null;
  child.kill = vi.fn();
  return child;
}

/** One fake child for the backend process; `taskkill` invocations get their own child that closes instantly. */
function stubSpawn(child: FakeChild): void {
  h.spawn.mockImplementation((command: string) => {
    if (command === 'taskkill') {
      const killer = new EventEmitter();
      queueMicrotask(() => killer.emit('close'));
      return killer;
    }
    return child;
  });
}

function stubHealth(body: () => unknown, status = 200): void {
  vi.stubGlobal('fetch', vi.fn(async () => ({ status, json: async () => body() })));
}

/** Health for a backend this session spawns: nothing listens on the port until spawn. */
function stubManagedHealth(body: () => unknown, status = 200): void {
  vi.stubGlobal('fetch', vi.fn(async () => {
    if (h.spawn.mock.calls.length === 0) throw new Error('ECONNREFUSED');
    return { status, json: async () => body() };
  }));
}

describe('backendProcess startup (H8 §10.3)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Point the backend resolver at this repository; spawn itself is mocked.
    vi.stubEnv('ATLAS_ROOT', REPO_ROOT);
    vi.stubEnv('ATLAS_PYTHON', 'atlas-fake-python');
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.useRealTimers();
    h.spawn.mockReset();
  });

  it('attaches to an external ready backend without spawning anything', async () => {
    stubHealth(() => ({ status: 'ok' }));
    const progress: BackendStartupProgress[] = [];
    const result = await ensureBackendRunning({ onProgress: (p) => progress.push(p) });
    expect(result).toEqual({ ready: true, managed: false });
    expect(h.spawn).not.toHaveBeenCalled();
    expect(progress.map((p) => p.phase)).toEqual(['probing', 'ready']);
  });

  it('keeps waiting through a slow 30-second start and kills nothing', async () => {
    let health: unknown = { status: 'starting', components: { mcp: { status: 'starting' } } };
    stubManagedHealth(() => health);
    const child = makeChild();
    stubSpawn(child);
    const progress: BackendStartupProgress[] = [];
    const promise = ensureBackendRunning({ onProgress: (p) => progress.push(p) });

    // A slow boot that used to lose the race against the fixed 15s timeout.
    await vi.advanceTimersByTimeAsync(30_000);
    expect(h.spawn).toHaveBeenCalledTimes(1);
    expect(child.kill).not.toHaveBeenCalled();
    expect(progress.some((p) => p.phase === 'starting')).toBe(true);

    health = { status: 'ok' };
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(promise).resolves.toEqual({ ready: true, managed: true, pid: 4242 });
    expect(child.kill).not.toHaveBeenCalled();
    expect(progress.at(-1)?.phase).toBe('ready');
    expect(progress.at(-1)?.managed).toBe(true);
  });

  it('reports progress details while health components are still starting', async () => {
    let health: unknown = { status: 'starting', components: { mcp: { status: 'starting' }, lsp: { status: 'starting' } } };
    stubManagedHealth(() => health);
    const child = makeChild();
    stubSpawn(child);
    const progress: BackendStartupProgress[] = [];
    const promise = ensureBackendRunning({ onProgress: (p) => progress.push(p) });
    await vi.advanceTimersByTimeAsync(1_200);

    const starting = progress.filter((p) => p.phase === 'starting');
    expect(starting.length).toBeGreaterThan(0);
    expect(starting.at(-1)?.detail).toContain('mcp');

    health = { status: 'ok' };
    await vi.advanceTimersByTimeAsync(1_000);
    await promise;
  });

  it('reads the backend string state contract and shows failed component details', async () => {
    let health: unknown = {
      status: 'starting',
      components: { session_migration: 'failed', mcp: 'starting' },
      component_errors: { session_migration: 'legacy import failed' },
    };
    stubManagedHealth(() => health);
    const child = makeChild();
    stubSpawn(child);
    const progress: BackendStartupProgress[] = [];
    const promise = ensureBackendRunning({ onProgress: (p) => progress.push(p) });
    await vi.advanceTimersByTimeAsync(1_200);

    expect(progress.at(-1)?.detail).toContain('session_migration(failed: legacy import failed)');
    expect(progress.at(-1)?.detail).toContain('mcp');

    health = { status: 'ok' };
    await vi.advanceTimersByTimeAsync(1_000);
    await promise;
  });

  it('fails immediately when the process exits, with the last 50 log lines', async () => {
    stubManagedHealth(() => null);
    const child = makeChild();
    stubSpawn(child);

    const promise = ensureBackendRunning();
    // Let the spawn + wait loop actually start before the process dies.
    await vi.advanceTimersByTimeAsync(300);
    child.stderr.emit('data', 'FIRST-LINE\n');
    for (let i = 0; i < 58; i += 1) child.stderr.emit('data', `filler ${i}\n`);
    child.stderr.emit('data', 'LAST-LINE\n');
    child.exitCode = 1;
    child.emit('exit', 1, null);
    const error = await promise.then(
      () => { throw new Error('expected rejection'); },
      (caught: Error) => caught,
    );
    expect(error.message).toContain('exited before becoming healthy');
    expect(error.message).toContain('LAST-LINE');
    expect(error.message).not.toContain('FIRST-LINE');
  });

  it('waits for an external backend that is still starting instead of spawning a second one', async () => {
    let health: unknown = { status: 'starting', components: { mcp: 'starting' } };
    stubHealth(() => health);
    const promise = ensureBackendRunning();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(h.spawn).not.toHaveBeenCalled();
    health = { status: 'ok' };
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(promise).resolves.toEqual({ ready: true, managed: false });
  });

  it('still gives up at the 300-second total cap, with the log tail', async () => {
    stubManagedHealth(() => ({ status: 'starting' }));
    const child = makeChild();
    stubSpawn(child);
    child.stderr.emit('data', 'booting\n');
    const promise = ensureBackendRunning();
    const expectation = expect(promise).rejects.toThrow(/did not become healthy within 300 seconds/);
    await vi.advanceTimersByTimeAsync(301_000);
    await expectation;
  });

  it('keeps a managed backend alive after optional startup failure settles', async () => {
    let health: unknown = { status: 'starting', components: { scheduler: 'starting' } };
    stubManagedHealth(() => health);
    const child = makeChild();
    stubSpawn(child);
    const promise = ensureBackendRunning();
    await vi.advanceTimersByTimeAsync(1_000);
    health = {
      status: 'degraded', components: { scheduler: 'failed' },
      component_errors: { scheduler: 'unavailable' },
    };
    await vi.advanceTimersByTimeAsync(1_000);
    await expect(promise).resolves.toEqual({ ready: true, managed: true, pid: child.pid });
    expect(child.kill).not.toHaveBeenCalled();
    expect(h.spawn).toHaveBeenCalledTimes(1);
  });

  it('attaches to a degraded external backend without spawning', async () => {
    stubHealth(() => ({ status: 'degraded', components: { mcp: 'failed' } }));
    await expect(ensureBackendRunning()).resolves.toEqual({ ready: true, managed: false });
    expect(h.spawn).not.toHaveBeenCalled();
  });
});
