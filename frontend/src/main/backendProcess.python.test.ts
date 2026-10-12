import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { spawnMock } = vi.hoisted(() => ({ spawnMock: vi.fn() }));
vi.mock('node:child_process', async (importOriginal) => ({
  ...await importOriginal<typeof import('node:child_process')>(),
  spawn: spawnMock,
}));

function fakeChild() {
  const child = new EventEmitter() as EventEmitter & {
    pid: number;
    exitCode: number | null;
    signalCode: NodeJS.Signals | null;
    stdout: EventEmitter;
    stderr: EventEmitter;
  };
  child.pid = 4321;
  child.exitCode = null;
  child.signalCode = null;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  Object.assign(child, {
    kill: vi.fn((signal: NodeJS.Signals) => {
      child.exitCode = 1;
      child.signalCode = signal;
      child.emit('exit', 1, signal);
      return true;
    }),
  });
  return child;
}

describe('source backend Python selection', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.stubEnv('ATLAS_ROOT', path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..'));
    vi.stubEnv('ATLAS_PYTHON', '');
    vi.stubEnv('ATLAS_BACKEND_EXECUTABLE', '');
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 503 })));
    spawnMock.mockReset().mockImplementation((command: string) => {
      const child = fakeChild();
      queueMicrotask(() => {
        if (command === 'taskkill') child.emit('close', 1, null);
        else child.emit('error', Object.assign(new Error('not found'), { code: 'ENOENT' }));
      });
      return child;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  async function firstSpawnCommand(): Promise<string> {
    const { ensureBackendRunning } = await import('./backendProcess.js');
    const starting = ensureBackendRunning();
    const startupFailure = expect(starting).rejects.toThrow('Could not start the Atlas backend');
    await vi.runAllTimersAsync();
    await startupFailure;
    return spawnMock.mock.calls[0]?.[0];
  }

  it('tries the repository core virtualenv before global Python commands', async () => {
    const expectedCorePython = path.join(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../core'),
      '.venv', 'Scripts', 'python.exe',
    );
    const nativeExistsSync = fs.existsSync.bind(fs);
    vi.spyOn(fs, 'existsSync').mockImplementation((candidate) =>
      String(candidate) === expectedCorePython || nativeExistsSync(candidate),
    );
    expect(await firstSpawnCommand()).toBe(expectedCorePython);
  });

  it('keeps ATLAS_PYTHON ahead of the repository virtualenv', async () => {
    vi.stubEnv('ATLAS_PYTHON', 'C:\\AtlasPython\\python.exe');

    expect(await firstSpawnCommand()).toBe('C:\\AtlasPython\\python.exe');
  });

  it('uses the desktop entry point that installs authenticated graceful shutdown', async () => {
    vi.stubEnv('ATLAS_PORT', '18775');
    await firstSpawnCommand();

    expect(spawnMock.mock.calls[0]?.[1]).toEqual(['-m', 'atlas.desktop_entry']);
    expect(spawnMock.mock.calls[0]?.[2].env.ATLAS_PORT).toBe('18775');
    expect(spawnMock.mock.calls[0]?.[2].env.ATLAS_SHUTDOWN_TOKEN).toMatch(/^[a-f0-9]{64}$/);
  });

  it('uses the core bin/python candidate on non-Windows platforms', async () => {
    const platformDescriptor = Object.getOwnPropertyDescriptor(process, 'platform');
    const expectedCorePython = path.join(
      path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../core'),
      '.venv', 'bin', 'python',
    );
    const nativeExistsSync = fs.existsSync.bind(fs);
    const existsSync = vi.spyOn(fs, 'existsSync').mockImplementation((candidate) =>
      String(candidate) === expectedCorePython || nativeExistsSync(candidate),
    );
    Object.defineProperty(process, 'platform', { configurable: true, value: 'linux' });
    try {
      expect(await firstSpawnCommand()).toBe(expectedCorePython);
    } finally {
      existsSync.mockRestore();
      if (platformDescriptor) Object.defineProperty(process, 'platform', platformDescriptor);
    }
  });
});

describe('external backend already starting', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    vi.stubEnv('ATLAS_ROOT', path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..'));
    spawnMock.mockReset();
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('waits for an external backend that is still starting instead of spawning a duplicate', async () => {
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async () => {
      calls += 1;
      const status = calls < 4 ? 'starting' : 'ok';
      return { status: 200, json: async () => ({ status, components: { mcp: status === 'ok' ? 'ready' : 'starting' } }) };
    }));
    const { ensureBackendRunning } = await import('./backendProcess.js');
    const starting = ensureBackendRunning();
    await vi.runAllTimersAsync();
    await expect(starting).resolves.toEqual({ ready: true, managed: false });
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it('re-probes a briefly unresponsive backend before spawning', async () => {
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn((_url: string, init?: { signal?: AbortSignal }) => {
      calls += 1;
      if (calls === 1) {
        // A busy backend: the request hangs until the probe's own timeout aborts it.
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        });
      }
      return Promise.resolve({ status: 200, json: async () => ({ status: 'ok' }) });
    }));
    const { ensureBackendRunning } = await import('./backendProcess.js');
    const starting = ensureBackendRunning();
    await vi.runAllTimersAsync();
    await expect(starting).resolves.toEqual({ ready: true, managed: false });
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it('refuses to attach to a backend that rejects this window token', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => (
      String(url).endsWith('/api/health')
        ? { status: 200, json: async () => ({ status: 'ok' }) }
        : { status: 403, json: async () => ({ detail: 'forbidden' }) }
    )));
    const { ensureBackendRunning } = await import('./backendProcess.js');
    const starting = ensureBackendRunning();
    const failure = expect(starting).rejects.toThrow(/不接受本窗口的访问令牌/);
    await vi.runAllTimersAsync();
    await failure;
    expect(spawnMock).not.toHaveBeenCalled();
  });
});
