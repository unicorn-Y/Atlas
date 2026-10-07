import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import TimelineView, {
  fetchTimelinePage, ItemRow, normalizeTimeline, normalizeTimelineItem,
} from './TimelineView';
import type { TimelineItem } from './TimelineView';

afterEach(() => vi.unstubAllGlobals());

const item = (overrides: Partial<TimelineItem> = {}): TimelineItem => ({
  recordRef: 'episode:e-1',
  revision: 3,
  facet: 'EPISODE',
  timeStatus: 'KNOWN',
  from: '2026-10-04T10:00:00+08:00',
  to: null,
  title: '发布定档',
  text: '和小王确定了发布时间',
  participants: ['小王'],
  speakerRole: 'USER',
  epistemic: 'USER_ASSERTED',
  sourceRefCount: 2,
  ...overrides,
});

describe('TimelineView normalize', () => {
  it('splits KNOWN and UNKNOWN time entries and keeps them separate', () => {
    const page = normalizeTimeline({
      items: [{ record_ref: 'episode:a', revision: 1, facet: 'EPISODE', content: { topic: 'raw:配色稿讨论', participants: [{ kind: 'ROLE', name: 'USER' }] }, valid_time: { valid_from: '2026-10-04T02:00:00Z', time_status: 'KNOWN' }, source_refs: [{}, {}] }],
      unknown: [{ record_ref: 'episode:b', content: { text: '不知道具体时候说的事' }, valid_time: { valid_from: null, time_status: 'UNKNOWN' }, source_refs: [{}] }],
      next_cursor: 'cur-2',
    });
    expect(page.items.map((entry) => entry.recordRef)).toEqual(['episode:a']);
    expect(page.unknown.map((entry) => entry.recordRef)).toEqual(['episode:b']);
    expect(page.nextCursor).toBe('cur-2');
    // raw: 机器前缀在展示层剥掉，但不改服务端数据
    expect(page.items[0].title).toBe('配色稿讨论');
    expect(page.items[0].participants).toEqual(['USER']);
    expect(page.items[0].sourceRefCount).toBe(2);
    expect(page.unknown[0].from).toBeNull();
  });

  it('drops entries without a record_ref (no evidence anchor, no clickable facade)', () => {
    expect(normalizeTimelineItem({ facet: 'EPISODE' })).toBeNull();
    expect(normalizeTimelineItem('junk')).toBeNull();
    expect(normalizeTimeline({ items: [{ record_ref: 'episode:ok' }], unknown: 'not-a-list' }).items).toHaveLength(1);
    expect(normalizeTimeline({ items: [{ record_ref: 'episode:ok' }], unknown: 'not-a-list' }).unknown).toHaveLength(0);
  });
});

describe('TimelineView fetch', () => {
  it('passes start/end/cursor/limit as query params', async () => {
    let asked = '';
    vi.stubGlobal('fetch', (async (input: RequestInfo | URL) => {
      asked = String(input);
      return new Response(JSON.stringify({ items: [], unknown: [] }), { status: 200 });
    }) as typeof fetch);
    await fetchTimelinePage('http://x', { start: '2026-10-01', end: '2026-10-06', cursor: 'c1', limit: 50 });
    expect(asked).toBe('http://x/api/unified-memory/timeline?start=2026-10-01&end=2026-10-06&cursor=c1&limit=50');
  });

  it('surfaces 501 as a degraded note, not a crash', async () => {
    vi.stubGlobal('fetch', (async () => new Response(JSON.stringify({ detail: { error: 'FEATURE_NOT_READY' } }), { status: 501 })) as typeof fetch);
    await expect(fetchTimelinePage('http://x', {})).rejects.toThrow('HTTP 501');
  });
});

describe('TimelineView render', () => {
  it('renders the loading skeleton and the filter bar on mount', () => {
    const html = renderToStaticMarkup(<TimelineView apiBaseUrl="http://x" connected />);
    expect(html).toContain('aria-label="日常时间线"');
    expect(html).toContain('正在读取时间线…');
    expect(html).toContain('aria-label="开始日期"');
    expect(html).toContain('aria-label="结束日期"');
    expect(html).toContain('每日概括');
    expect(html).toContain('每周概括');
    expect(html).toContain('单次事件');
  });

  it('shows a waiting note instead of a stuck spinner when the backend is offline', () => {
    const html = renderToStaticMarkup(<TimelineView apiBaseUrl="http://x" connected={false} />);
    expect(html).toContain('等待 Atlas 后端连接后读取时间线');
    expect(html).not.toContain('正在读取时间线');
  });

  it('renders rows with evidence/correction entry points, role and inference badges', () => {
    const html = renderToStaticMarkup(<ItemRow item={item()} />);
    expect(html).toContain('发布定档');
    expect(html).toContain('和小王确定了发布时间');
    expect(html).toContain('用户亲述');
    expect(html).toContain('原话 2 条');
    expect(html).toContain('依据');
    expect(html).toContain('纠错');
    expect(html).toContain('版本 3');
  });

  it('marks inferred entries with the 推断 badge', () => {
    const html = renderToStaticMarkup(<ItemRow item={item({ epistemic: 'INFERRED', speakerRole: 'TOOL' })} />);
    expect(html).toContain('推断');
    expect(html).toContain('工具');
  });

  it('marks daily and weekly rollup summaries with explicit tags (S5)', () => {
    const dailyHtml = renderToStaticMarkup(<ItemRow item={item({ facet: 'SUMMARY', title: '10月8日概括' })} />);
    expect(dailyHtml).toContain('[每日概括]');
    const weeklyHtml = renderToStaticMarkup(<ItemRow item={item({ facet: 'SUMMARY', title: '第40周概括' })} />);
    expect(weeklyHtml).toContain('[每周概括]');
  });
});
