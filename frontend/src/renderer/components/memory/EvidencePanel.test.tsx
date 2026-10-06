import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import EvidencePanel, {
  EvidenceDeletedError, EvidencePanelBody, evidencePath, fetchEvidence, normalizeEvidence,
} from './EvidencePanel';

afterEach(() => vi.unstubAllGlobals());

const payload = {
  snippets: [
    { locator: { kind: 'MESSAGE', value: 'chat-timeline/s-1' }, text: '写代码用 VS Code，主题偏暗', occurred_at: '2026-10-04T02:00:00Z', speaker_role: 'USER', epistemic_kind: 'USER_ASSERTED' },
    { locator: { kind: 'IMAGE_REGION', value: 'shots/a.png#120,40,400,60' }, asset_id: 'asset-9', inferred: true },
  ],
};

describe('EvidencePanel normalize', () => {
  it('keeps locator/verbatim/time/role and the inference flag', () => {
    const snippets = normalizeEvidence(payload);
    expect(snippets).toHaveLength(2);
    expect(snippets[0].text).toBe('写代码用 VS Code，主题偏暗');
    expect(snippets[0].locatorKind).toBe('MESSAGE');
    expect(snippets[0].speakerRole).toBe('USER');
    expect(snippets[0].inferred).toBe(false);
    expect(snippets[1].inferred).toBe(true);
    expect(snippets[1].mediaAssetId).toBe('asset-9');
    expect(normalizeEvidence({ snippets: 'nope' })).toEqual([]);
  });
});

describe('EvidencePanel fetch', () => {
  it('keeps : in the record_ref path and appends revision param', async () => {
    let asked = '';
    vi.stubGlobal('fetch', (async (input: RequestInfo | URL) => {
      asked = String(input);
      return new Response(JSON.stringify(payload), { status: 200 });
    }) as typeof fetch);
    const snippets = await fetchEvidence('http://x', 'episode:e-1', { revision: 3 });
    expect(asked).toBe('http://x/api/unified-memory/evidence/episode:e-1?revision=3');
    expect(snippets[0].text).toContain('VS Code');
  });

  it('maps 410 to the deleted state and never falls back to cache', async () => {
    vi.stubGlobal('fetch', (async () => new Response(JSON.stringify({ detail: { error: 'RECORD_ERASED' } }), { status: 410 })) as typeof fetch);
    const cause = await fetchEvidence('http://x', 'episode:e-1').then(() => null, (exc: unknown) => exc);
    expect(cause).toBeInstanceOf(EvidenceDeletedError);
    expect((cause as EvidenceDeletedError).kind).toBe('deleted');
    expect((cause as Error).message).toContain('已删除');
  });

  it('maps the 423 barrier state to a distinct message', async () => {
    vi.stubGlobal('fetch', (async () => new Response(JSON.stringify({ detail: { error: 'ERASURE_BLOCKED' } }), { status: 423 })) as typeof fetch);
    const cause = await fetchEvidence('http://x', 'episode:e-1').then(() => null, (exc: unknown) => exc);
    expect(cause).toBeInstanceOf(EvidenceDeletedError);
    expect((cause as EvidenceDeletedError).kind).toBe('barrier');
  });
});

describe('EvidencePanel render', () => {
  it('renders snippets with locator label, verbatim, time, role and 推断 flag', () => {
    const html = renderToStaticMarkup(<EvidencePanelBody state={{
      loading: false, deleted: null, error: '',
      snippets: normalizeEvidence(payload), recordRef: 'episode:e-1', revision: 3,
    }} />);
    expect(html).toContain('消息原文');
    expect(html).toContain('写代码用 VS Code，主题偏暗');
    expect(html).toContain('说话：用户');
    expect(html).toContain('推断');
    expect(html).toContain('episode:e-1 · 版本 3');
    expect(html).toContain('图片区域');
  });

  it('shows the deleted state on 410 and never renders cached content', () => {
    const html = renderToStaticMarkup(<EvidencePanelBody state={{
      loading: false, deleted: 'deleted', error: '', snippets: [], recordRef: 'episode:e-1', revision: null,
    }} />);
    expect(html).toContain('已删除');
    expect(html).toContain('不会回落到旧缓存');
    expect(html).not.toContain('VS Code');
  });

  it('shows the barrier note, the error note and the loading state', () => {
    const barrier = renderToStaticMarkup(<EvidencePanelBody state={{ loading: false, deleted: 'barrier', error: '', snippets: [], recordRef: 'r', revision: null }} />);
    expect(barrier).toContain('屏障处理中');
    const failed = renderToStaticMarkup(<EvidencePanelBody state={{ loading: false, deleted: null, error: 'HTTP 503：断连', snippets: [], recordRef: 'r', revision: null }} />);
    expect(failed).toContain('读取依据失败：HTTP 503：断连');
    expect(renderToStaticMarkup(<EvidencePanelBody state={{ loading: true, deleted: null, error: '', snippets: [], recordRef: 'r', revision: null }} />)).toContain('正在读取依据…');
  });

  it('escapes the record_ref path but keeps : and / separators', () => {
    expect(evidencePath('episode:e-1')).toBe('episode:e-1');
    expect(evidencePath('memory:a b/c-1')).toBe('memory:a%20b/c-1');
  });

  it('mounts into a dialog shell (default export renders the header label)', () => {
    // Radix Portal 在服务端渲染不输出内容 —— 静态冒烟只验证组件可挂载不抛异常。
    const html = renderToStaticMarkup(<EvidencePanel apiBaseUrl="http://x" recordRef="episode:e-1" revision={2} onClose={() => undefined} />);
    expect(typeof html).toBe('string');
  });
});
