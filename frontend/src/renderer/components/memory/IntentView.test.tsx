import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import IntentView, { IntentRow, fetchIntents, normalizeIntents } from './IntentView';

afterEach(() => vi.unstubAllGlobals());

describe('IntentView normalize', () => {
  it('keeps title/status/due/scope and drops anchor-less entries', () => {
    const page = normalizeIntents({
      items: [
        { id: 'intent-1', title: '周五前给出对比结论', status: 'ACTIVE', due: '2026-10-09T18:00:00+08:00', scope: '工作' },
        { id: 'intent-2', status: 'PROPOSED' },
        { status: 'ACTIVE' },
        'junk',
      ],
      next_cursor: 'i2',
    });
    expect(page.nextCursor).toBe('i2');
    expect(page.items).toHaveLength(2);
    expect(page.items[0].title).toBe('周五前给出对比结论');
    expect(page.items[0].due).toContain('2026-10-09');
    expect(page.items[1].title).toBe('(未写明内容)');
  });

  it('tolerates wrapped and junk payloads', () => {
    expect(normalizeIntents({ intents: [{ id: 'a' }] }).items).toHaveLength(1);
    expect(normalizeIntents(null).items).toHaveLength(0);
  });
});

describe('IntentView fetch — 501 degraded path', () => {
  it('rejects with HTTP 501 which the view maps to the degraded note', async () => {
    vi.stubGlobal('fetch', (async () => new Response(
      JSON.stringify({ detail: { error: 'FEATURE_NOT_READY', message: 'intents not wired' } }), { status: 501 },
    )) as typeof fetch);
    await expect(fetchIntents('http://x', {})).rejects.toThrow('HTTP 501');
  });
});

describe('IntentView render', () => {
  it('renders the status badge and due date', () => {
    const html = renderToStaticMarkup(<IntentRow intent={{ id: 'intent-1', title: '周五前给出对比结论', status: 'ACTIVE', due: '2026-10-09T18:00:00+08:00', scope: '工作', revision: 1 }} />);
    expect(html).toContain('周五前给出对比结论');
    expect(html).toContain('进行中');
    expect(html).toContain('到期');
    expect(html).toContain('工作');
  });

  it('renders the loading skeleton and the degraded note on mount', () => {
    const html = renderToStaticMarkup(<IntentView apiBaseUrl="http://x" connected />);
    expect(html).toContain('aria-label="待办"');
    expect(html).toContain('正在读取待办…');
  });
});
