import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import EntityView, { EntityRow, fetchEntities, normalizeEntities, entityStatusLabel } from './EntityView';

afterEach(() => vi.unstubAllGlobals());

const payload = {
  items: [
    { id: 'ent-1', type: 'PERSON', name: '小王', aliases: ['老王'], alias_status: 'VERIFIED' },
    { id: 'ent-2', type: 'PERSON', name: '小王', aliases: ['王同学'], alias_status: 'PROPOSED' },
    { id: 'ent-3', type: 'PROJECT', name: '统一记忆', aliases: [], alias_status: 'WEIRD_STATE' },
  ],
  next_cursor: 'e2',
};

describe('EntityView normalize', () => {
  it('keeps aliases and the raw alias status; unknown states stay untranslated', () => {
    const page = normalizeEntities(payload);
    expect(page.items).toHaveLength(3);
    expect(page.nextCursor).toBe('e2');
    expect(page.items[0].aliases).toEqual(['老王']);
    // 未决关联不装成已确认：PROPOSED 是待确认，未知状态原样显示
    expect(entityStatusLabel(page.items[0])).toMatchObject({ text: '已确认', verified: true });
    expect(entityStatusLabel(page.items[1])).toMatchObject({ text: '待确认', proposed: true });
    expect(entityStatusLabel(page.items[2]).text).toBe('WEIRD_STATE');
  });

  it('drops entries without id and tolerates junk payloads', () => {
    expect(normalizeEntities({ items: [{ name: '没有 id' }, null] }).items).toHaveLength(0);
    expect(normalizeEntities(null).items).toHaveLength(0);
  });
});

describe('EntityView fetch', () => {
  it('passes the query and cursor params', async () => {
    let asked = '';
    vi.stubGlobal('fetch', (async (input: RequestInfo | URL) => {
      asked = String(input);
      return new Response(JSON.stringify({ items: [] }), { status: 200 });
    }) as typeof fetch);
    await fetchEntities('http://x', { query: '小王', cursor: 'c1', limit: 50 });
    expect(asked).toBe('http://x/api/unified-memory/entities?query=%E5%B0%8F%E7%8E%8B&cursor=c1&limit=50');
  });
});

describe('EntityView render', () => {
  it('renders PROPOSED/VERIFIED badges as-is and lists aliases', () => {
    const page = normalizeEntities(payload);
    const html = page.items.map((entity) => renderToStaticMarkup(<EntityRow entity={entity} />)).join('');
    expect(html).toContain('小王');
    expect(html).toContain('已确认');
    expect(html).toContain('待确认');
    expect(html).toContain('老王');
    expect(html).toContain('王同学');
    expect(html).toContain('人物');
    expect(html).toContain('项目');
  });

  it('renders the search field and loading skeleton on mount', () => {
    const html = renderToStaticMarkup(<EntityView apiBaseUrl="http://x" connected />);
    expect(html).toContain('aria-label="人事"');
    expect(html).toContain('aria-label="搜索实体"');
    expect(html).toContain('正在读取人物与事物…');
  });
});
