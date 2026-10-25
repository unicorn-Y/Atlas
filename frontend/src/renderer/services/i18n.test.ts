import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { observeLocalizedCopy, readLocale, saveLocale, t } from './i18n';
import { messages as enUS } from './locales/en-US';

describe('renderer locale resources', () => {
  const values = new Map<string, string>();
  const documentStub = { documentElement: { lang: '' }, body: { dataset: {} as Record<string, string> } };
  beforeEach(() => {
    values.clear();
    vi.stubGlobal('localStorage', { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value), removeItem: (key: string) => values.delete(key) });
    vi.stubGlobal('document', documentStub);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('persists locale and translates catalog copy in English', () => {
    saveLocale('en-US');
    expect(readLocale()).toBe('en-US');
    expect(documentStub.documentElement.lang).toBe('en-US');
    expect(t('通知级别')).toBe('Notification level');
  });

  it('keeps Chinese source copy when Chinese is selected and falls back safely', () => {
    saveLocale('zh-CN');
    expect(t('通知级别')).toBe('通知级别');
    expect(t('A user supplied label')).toBe('A user supplied label');
  });

  it('translates interpolated renderer copy and preserves runtime values', () => {
    saveLocale('en-US');
    expect(t('Atlas 3.0 已更新。')).toBe('Atlas 3.0 has been updated.');
    expect(t('已加入 4 张截图')).toBe('Added 4 screenshots');
    expect(t('收到用户输入：private value')).toBe('收到用户输入：private value');
    expect(Object.keys(enUS).length).toBeGreaterThan(6_000);
  });

  it('relocalizes renderer-owned text updates without reusing stale source copy', () => {
    let observerCallback: MutationCallback | undefined;
    class ObserverStub {
      constructor(callback: MutationCallback) { observerCallback = callback; }
      observe() {}
      disconnect() {}
    }
    const text = { nodeType: 3, nodeValue: '模型与服务', parentElement: { tagName: 'DIV', closest: () => null } };
    const root = {
      nodeType: 1,
      tagName: 'DIV',
      childNodes: [text],
      getAttribute: () => null,
      setAttribute: () => undefined,
    };
    vi.stubGlobal('Node', { TEXT_NODE: 3, ELEMENT_NODE: 1 });
    vi.stubGlobal('MutationObserver', ObserverStub);

    const disconnect = observeLocalizedCopy(root as unknown as HTMLElement, 'en-US');
    expect(text.nodeValue).toBe('Models & Services');
    text.nodeValue = '通知级别';
    observerCallback?.([{ type: 'characterData', target: text } as unknown as MutationRecord], {} as MutationObserver);
    expect(text.nodeValue).toBe('Notification level');
    disconnect();
  });
});
