import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import RecordsView, {
  RecordRow,
  fetchRecordsPage,
  normalizeRecords,
} from './RecordsView';

afterEach(() => vi.unstubAllGlobals());

const samplePayload = {
  items: [
    {
      record_ref: 'memory:m-001',
      revision: 2,
      facet: 'PREFERENCE',
      importance: 0.9,
      recorded_at: '2026-10-08T00:00:00+08:00',
      lifecycle: 'ACTIVE',
      content: { key: 'pref:editor', value: '用户偏好使用 VS Code 深色主题' },
      locator: { kind: 'MESSAGE', value: 'msg-1' },
      epistemic_kind: 'USER_ASSERTED',
      speaker_role: 'USER',
    },
    {
      record_ref: 'memory:m-002',
      revision: 1,
      facet: 'SUMMARY',
      importance: 0.75,
      recorded_at: '2026-10-07T18:00:00+08:00',
      lifecycle: 'SUPERSEDED',
      content: { topic: '工作经历', text: '在一家科技创业公司担任架构师' },
      source_object_id: 'doc-resume',
      epistemic_kind: 'INFERRED',
      speaker_role: 'ASSISTANT',
    },
  ],
  next_cursor: 'rec-c2',
};

describe('RecordsView normalize', () => {
  it('normalizes records with category, status, importance, and source provenance', () => {
    const page = normalizeRecords(samplePayload);
    expect(page.items).toHaveLength(2);
    expect(page.nextCursor).toBe('rec-c2');

    const [item1, item2] = page.items;
    expect(item1.recordRef).toBe('memory:m-001');
    expect(item1.facet).toBe('PREFERENCE');
    expect(item1.importance).toBe(0.9);
    expect(item1.status).toBe('ACTIVE');
    expect(item1.source).toBe('MESSAGE:msg-1');
    expect(item1.text).toBe('用户偏好使用 VS Code 深色主题');

    expect(item2.status).toBe('SUPERSEDED');
    expect(item2.source).toBe('doc-resume');
    expect(item2.text).toBe('在一家科技创业公司担任架构师');
  });

  it('tolerates empty or junk payloads', () => {
    expect(normalizeRecords(null).items).toHaveLength(0);
    expect(normalizeRecords({ items: ['junk', null] }).items).toHaveLength(0);
  });
});

describe('RecordsView fetch', () => {
  it('passes facet, status, cursor and limit query parameters', async () => {
    let asked = '';
    vi.stubGlobal('fetch', (async (input: RequestInfo | URL) => {
      asked = String(input);
      return new Response(JSON.stringify(samplePayload), { status: 200 });
    }) as typeof fetch);

    await fetchRecordsPage('http://x', {
      facet: 'PREFERENCE',
      status: 'ACTIVE',
      cursor: 'cur-1',
      limit: 50,
    });
    expect(asked).toBe(
      'http://x/api/unified-memory/records?facet=PREFERENCE&status=ACTIVE&cursor=cur-1&limit=50',
    );
  });
});

describe('RecordRow render', () => {
  it('renders record fields: source, active/historical badge, importance, evidence/correct buttons', () => {
    const page = normalizeRecords(samplePayload);
    const html = renderToStaticMarkup(
      <RecordRow
        item={page.items[0]}
        onOpenEvidence={() => undefined}
        onCorrect={() => undefined}
        onDelete={() => undefined}
      />,
    );

    expect(html).toContain('用户偏好使用 VS Code 深色主题');
    expect(html).toContain('出处：MESSAGE:msg-1');
    expect(html).toContain('当前');
    expect(html).toContain('重要性 0.9');
    expect(html).toContain('依据');
    expect(html).toContain('纠偏');
    expect(html).toContain('删除');
  });

  it('renders historical record badge', () => {
    const page = normalizeRecords(samplePayload);
    const html = renderToStaticMarkup(<RecordRow item={page.items[1]} />);
    expect(html).toContain('历史 (SUPERSEDED)');
    expect(html).toContain('出处：doc-resume');
  });
});

describe('RecordsView mount', () => {
  it('renders search bar, category filter, and loading skeleton on mount', () => {
    const html = renderToStaticMarkup(<RecordsView apiBaseUrl="http://x" connected />);
    expect(html).toContain('aria-label="记忆列表"');
    expect(html).toContain('aria-label="搜索记忆列表"');
    expect(html).toContain('aria-label="类别筛选"');
    expect(html).toContain('aria-label="状态筛选"');
    expect(html).toContain('正在读取记忆列表…');
  });

  it('shows waiting note when disconnected', () => {
    const html = renderToStaticMarkup(<RecordsView apiBaseUrl="http://x" connected={false} />);
    expect(html).toContain('等待 Atlas 后端连接后读取记忆列表');
  });
});
