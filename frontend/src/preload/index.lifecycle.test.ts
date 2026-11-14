import { transformSync } from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';
import type { BackendLifecycleEvent } from '../shared/ipc.js';

// D2 (renderer half): the preload's typed backend-lifecycle subscription must be
// disposable, must catch up on the latest published state right after subscribing,
// and must never regress to an older sequence. The preload source is executed in a
// sandbox the same way the packaged bundle is exercised by scripts/test-preload-bundle.mjs.

const sourcePath = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'index.cts');

interface PreloadApi {
  platform: string;
  apiBaseUrl: string;
  onBackendLifecycleEvent(callback: (event: BackendLifecycleEvent) => void): () => void;
}

interface Harness {
  api: PreloadApi;
  /** Channel -> currently registered ipcRenderer listeners. */
  listeners: Map<string, Set<(event: unknown, payload: unknown) => void>>;
  invocations: string[];
}

function bootPreload(
  env: Record<string, string>,
  getLatest: () => BackendLifecycleEvent | null,
): Harness {
  const source = fs.readFileSync(sourcePath, 'utf8');
  const bundle = transformSync(source, { loader: 'ts', target: 'es2022', format: 'cjs' }).code;
  const exposed = new Map<string, unknown>();
  const listeners = new Map<string, Set<(event: unknown, payload: unknown) => void>>();
  const invocations: string[] = [];
  const electron = {
    contextBridge: { exposeInMainWorld: (name: string, api: unknown) => exposed.set(name, api) },
    ipcRenderer: {
      on: (channel: string, listener: (event: unknown, payload: unknown) => void) => {
        if (!listeners.has(channel)) listeners.set(channel, new Set());
        listeners.get(channel)!.add(listener);
      },
      removeListener: (channel: string, listener: (event: unknown, payload: unknown) => void) => {
        listeners.get(channel)?.delete(listener);
      },
      invoke: async (channel: string) => {
        invocations.push(channel);
        return channel === 'backend:get-lifecycle' ? getLatest() : undefined;
      },
      send: () => undefined,
    },
  };
  const sandbox = {
    exports: {},
    module: { exports: {} },
    process: { platform: 'win32', env: { ...env } },
    require: (specifier: string) => {
      if (specifier !== 'electron') throw new Error(`sandboxed preload attempted require(${specifier})`);
      return electron;
    },
  };
  new vm.Script(bundle, { filename: 'preload-lifecycle-test.cjs' }).runInNewContext(sandbox);
  const api = exposed.get('atlasDesktop') as PreloadApi | undefined;
  if (!api) throw new Error('preload did not expose window.atlasDesktop');
  return { api, listeners, invocations };
}

function push(harness: Harness, channel: string, payload: unknown): void {
  for (const listener of [...(harness.listeners.get(channel) ?? [])]) listener({ sender: {} }, payload);
}

const flush = () => new Promise<void>((resolve) => setImmediate(resolve));

const lifecycleEvent = (overrides: Partial<BackendLifecycleEvent>): BackendLifecycleEvent => ({
  kind: 'ready', sequence: 1, timestamp: new Date(0).toISOString(), ...overrides,
});

describe('preload backend port surface (D1)', () => {
  it('exposes apiBaseUrl on the injected ATLAS_PORT with the documented fallbacks', () => {
    expect(bootPreload({ ATLAS_PORT: '41025' }, () => null).api.apiBaseUrl).toBe('http://127.0.0.1:41025');
    expect(bootPreload({}, () => null).api.apiBaseUrl).toBe('http://127.0.0.1:8765');
    expect(bootPreload({ ATLAS_API_BASE_URL: 'http://127.0.0.1:9001', ATLAS_PORT: '41025' }, () => null).api.apiBaseUrl)
      .toBe('http://127.0.0.1:9001');
  });
});

describe('preload backend lifecycle subscription (D2)', () => {
  it('catches up on the latest published state right after subscribing', async () => {
    const latest = lifecycleEvent({ kind: 'fatal', sequence: 3, detail: 'backend exploded' });
    const harness = bootPreload({ ATLAS_PORT: '41025' }, () => latest);
    const seen: BackendLifecycleEvent[] = [];
    const dispose = harness.api.onBackendLifecycleEvent((event) => seen.push(event));
    await flush();
    expect(harness.invocations).toContain('backend:get-lifecycle');
    expect(seen).toEqual([latest]);
    dispose();
    expect(harness.listeners.get('backend:lifecycle')?.size ?? 0).toBe(0);
  });

  it('delivers pushed events, ignores a stale catch-up, and detaches on disposal', async () => {
    let releaseCatchup: ((event: BackendLifecycleEvent | null) => void) | null = null;
    const harness = bootPreload({ ATLAS_PORT: '41025' }, () => new Promise<BackendLifecycleEvent | null>((resolve) => { releaseCatchup = resolve; }));
    const seen: BackendLifecycleEvent[] = [];
    const dispose = harness.api.onBackendLifecycleEvent((event) => seen.push(event));
    try {
      // Pushed events arrive as they happen.
      push(harness, 'backend:lifecycle', lifecycleEvent({ kind: 'ready', sequence: 2, timestamp: 't2' }));
      expect(seen).toEqual([lifecycleEvent({ kind: 'ready', sequence: 2, timestamp: 't2' })]);

      // The catch-up snapshot taken before the push is older: it must not regress the renderer.
      releaseCatchup?.(lifecycleEvent({ kind: 'ready', sequence: 1, timestamp: 't1' }));
      await flush();
      expect(seen).toHaveLength(1);
      // A pushed replay of the same older sequence is ignored too.
      push(harness, 'backend:lifecycle', lifecycleEvent({ kind: 'ready', sequence: 1, timestamp: 't1' }));
      expect(seen).toHaveLength(1);

      push(harness, 'backend:lifecycle', lifecycleEvent({ kind: 'quit-inspection', sequence: 3, timestamp: 't3', runningTasks: 1, scheduledTasks: 2 }));
      expect(seen).toHaveLength(2);
      expect(seen.at(-1)).toMatchObject({ kind: 'quit-inspection', runningTasks: 1, scheduledTasks: 2 });
    } finally {
      releaseCatchup?.(null);
      dispose();
    }
    push(harness, 'backend:lifecycle', lifecycleEvent({ kind: 'fatal', sequence: 4, timestamp: 't4' }));
    expect(seen).toHaveLength(2);
    expect(harness.listeners.get('backend:lifecycle')?.size ?? 0).toBe(0);
  });

  it('delivers nothing when no lifecycle state was ever published', async () => {
    const harness = bootPreload({ ATLAS_PORT: '41025' }, () => null);
    const seen: BackendLifecycleEvent[] = [];
    const dispose = harness.api.onBackendLifecycleEvent((event) => seen.push(event));
    await flush();
    expect(harness.invocations).toContain('backend:get-lifecycle');
    expect(seen).toEqual([]);
    dispose();
    expect(harness.listeners.get('backend:lifecycle')?.size ?? 0).toBe(0);
  });
});
