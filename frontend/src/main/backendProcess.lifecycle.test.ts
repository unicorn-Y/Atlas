import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { spawnMock } = vi.hoisted(() => ({ spawnMock: vi.fn() }));
vi.mock('node:child_process', async (importOriginal) => ({
  ...await importOriginal<typeof import('node:child_process')>(), spawn: spawnMock,
}));

describe('backend lifecycle evidence after startup', () => {
  let child: EventEmitter & { pid: number; exitCode: number | null;
    signalCode: NodeJS.Signals | null; stdout: EventEmitter; stderr: EventEmitter };
  let root: string;
  let spawned: boolean;

  beforeEach(() => {
    vi.resetModules();
    vi.useFakeTimers();
    const scratch = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../.tmp');
    fs.mkdirSync(scratch, { recursive: true });
    root = fs.mkdtempSync(path.join(scratch, 'backend-lifecycle-'));
    vi.stubEnv('ATLAS_DATA_DIR', root);
    vi.stubEnv('ATLAS_ROOT', path.resolve(scratch, '..'));
    vi.stubEnv('ATLAS_PORT', '28999');
    vi.stubEnv('ATLAS_PYTHON', 'isolated-test-python');
    vi.stubEnv('ATLAS_BACKEND_EXECUTABLE', '');
    child = Object.assign(new EventEmitter(), {
      pid: 12345678, exitCode: null, signalCode: null,
      stdout: new EventEmitter(), stderr: new EventEmitter(),
    });
    spawned = false;
    spawnMock.mockReset().mockImplementation(() => { spawned = true; return child; });
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (String(url).includes('/api/runtime/shutdown')) {
        child.exitCode = 0;
        child.emit('exit', 0, null);
        child.emit('close', 0, null);
        return { status: 202 };
      }
      return spawned ? { status: 200, json: async () => ({ status: 'ok' }) } : { status: 503 };
    }));
  });

  afterEach(() => {
    child.emit('close', child.exitCode, child.signalCode);
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  async function started() {
    const backend = await import('./backendProcess.js');
    const launch = backend.ensureBackendRunning();
    const ready = expect(launch).resolves.toMatchObject({ ready: true, managed: true });
    await vi.runAllTimersAsync();
    await ready;
    return backend;
  }

  function records(logPath: string) {
    return fs.readFileSync(logPath, 'utf8').trim().split(/\r?\n/)
      .filter(Boolean).map((line) => JSON.parse(line));
  }

  it('records an unexpected exit code and process identity after becoming ready', async () => {
    const backend = await started();
    child.exitCode = 23;
    child.emit('exit', 23, null);
    child.emit('close', 23, null);
    expect(records(backend.getBackendLogPath())).toContainEqual(expect.objectContaining({
      event: 'backend.process_exit', pid: 12345678, code: 23, signal: null,
      stop_reason: null,
    }));
  });

  it('distinguishes a requested shutdown from an unexpected exit', async () => {
    const backend = await started();
    await backend.stopManagedBackend();
    const events = records(backend.getBackendLogPath());
    expect(events).toContainEqual(expect.objectContaining({
      event: 'backend.stop_requested', pid: 12345678, reason: 'app_quit',
    }));
    expect(events).toContainEqual(expect.objectContaining({
      event: 'backend.process_exit', code: 0, stop_reason: 'app_quit',
    }));
  });
});
