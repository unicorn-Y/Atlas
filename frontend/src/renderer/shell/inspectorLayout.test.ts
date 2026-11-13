import { afterEach, describe, expect, it } from 'vitest';
import { inspectorLayoutKey, readInspectorLayout, writeInspectorLayout } from './inspectorLayout';

afterEach(() => { Reflect.deleteProperty(globalThis, 'localStorage'); });

describe('inspector per-session layout', () => {
  it('stores dock, split tab, and active tab separately for each conversation', () => {
    const values = new Map<string, string>();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) },
    });
    writeInspectorLayout('chat/one', { version: 1, tab: 'files', splitTab: 'overview', floating: true });

    expect(inspectorLayoutKey('chat/one')).not.toBe(inspectorLayoutKey('chat/two'));
    expect(readInspectorLayout('chat/one')).toEqual({ version: 1, tab: 'files', splitTab: 'overview', floating: true });
    expect(readInspectorLayout('chat/two')).toEqual({ version: 1, tab: 'artifacts', splitTab: null, floating: false });
  });

  it('recovers safely from invalid or old layout data', () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: () => '{bad json' },
    });
    expect(readInspectorLayout('chat/one')).toEqual({ version: 1, tab: 'artifacts', splitTab: null, floating: false });
  });
});
