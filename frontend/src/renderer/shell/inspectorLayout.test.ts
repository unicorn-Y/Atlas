import { afterEach, describe, expect, it } from 'vitest';
import { inspectorLayoutKey, moveInspectorFloat, readInspectorLayout, writeInspectorLayout } from './inspectorLayout';

afterEach(() => { Reflect.deleteProperty(globalThis, 'localStorage'); });

describe('inspector per-session layout', () => {
  it('stores dock, split tab, and active tab separately for each conversation', () => {
    const values = new Map<string, string>();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) },
    });
    writeInspectorLayout('chat/one', { version: 1, tab: 'files', splitTab: 'overview', floating: true, floatPosition: null });

    expect(inspectorLayoutKey('chat/one')).not.toBe(inspectorLayoutKey('chat/two'));
    expect(readInspectorLayout('chat/one')).toEqual({ version: 1, tab: 'files', splitTab: 'overview', floating: true, floatPosition: null });
    expect(readInspectorLayout('chat/two')).toEqual({ version: 1, tab: 'artifacts', splitTab: null, floating: false, floatPosition: null });
  });

  it('persists a floating panel position independently for each conversation', () => {
    const values = new Map<string, string>();
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) },
    });
    writeInspectorLayout('chat/one', { version: 1, tab: 'files', splitTab: null, floating: true, floatPosition: { left: 180, top: 72 } });

    expect(readInspectorLayout('chat/one').floatPosition).toEqual({ left: 180, top: 72 });
    expect(readInspectorLayout('chat/two').floatPosition).toBeNull();
  });

  it('keeps a dragged floating panel within the visible viewport', () => {
    expect(moveInspectorFloat({ left: 180, top: 72 }, { x: 55, y: -12 }, { width: 1200, height: 800 }))
      .toEqual({ left: 235, top: 60 });
    expect(moveInspectorFloat({ left: 1150, top: 790 }, { x: 100, y: 100 }, { width: 1200, height: 800 }))
      .toEqual({ left: 1080, top: 752 });
  });

  it('recovers safely from invalid or old layout data', () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: { getItem: () => '{bad json' },
    });
    expect(readInspectorLayout('chat/one')).toEqual({ version: 1, tab: 'artifacts', splitTab: null, floating: false, floatPosition: null });
  });
});
