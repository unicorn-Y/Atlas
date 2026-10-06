import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import CorrectionDialog, {
  CorrectionConflictError, CorrectionDialogBody, normalizeAffected, submitCorrection,
} from './CorrectionDialog';

afterEach(() => vi.unstubAllGlobals());

const recorded: Array<{ url: string; init?: RequestInit }> = [];

function stubFetch(status: number, body: unknown) {
  recorded.length = 0;
  vi.stubGlobal('fetch', (async (input: RequestInfo | URL, init?: RequestInit) => {
    recorded.push({ url: String(input), init });
    return new Response(JSON.stringify(body), { status });
  }) as typeof fetch);
}

describe('submitCorrection (interaction, mocked fetch)', () => {
  it('posts request_id/target_ref/expected_revision/replacement and reports revision + affected items', async () => {
    stubFetch(200, { revision: 6, affected: [{ record_ref: 'memory:m-2', reason: '同一偏好来源' }, 'memory:m-3'] });
    const result = await submitCorrection('http://x', {
      targetRef: 'memory:m-1', expectedRevision: 5, replacement: '写代码用 VS Code，主题偏亮', requestId: 'req-1',
    });
    expect(recorded[0].url).toBe('http://x/api/unified-memory/corrections');
    expect(recorded[0].init?.method).toBe('POST');
    expect(JSON.parse(String(recorded[0].init?.body))).toEqual({
      request_id: 'req-1', target_ref: 'memory:m-1', expected_revision: 5,
      replacement: '写代码用 VS Code，主题偏亮', source: 'desktop-correction',
    });
    expect(result.revision).toBe(6);
    expect(result.affected).toEqual([
      { recordRef: 'memory:m-2', reason: '同一偏好来源' },
      { recordRef: 'memory:m-3', reason: '' },
    ]);
  });

  it('generates an idempotent request_id when the caller does not supply one', async () => {
    stubFetch(200, { revision: 7, affected: [] });
    await submitCorrection('http://x', { targetRef: 'memory:m-1', expectedRevision: null, replacement: '换成简短中文' });
    const body = JSON.parse(String(recorded[0].init?.body)) as Record<string, unknown>;
    expect(typeof body.request_id).toBe('string');
    expect((body.request_id as string).length).toBeGreaterThan(8);
    expect(body.expected_revision).toBeNull();
  });

  it('maps 409 to the visible conflict error instead of a fake success', async () => {
    stubFetch(409, { detail: { error: 'REVISION_CONFLICT', message: 'revision mismatch' } });
    const cause = await submitCorrection('http://x', { targetRef: 'memory:m-1', expectedRevision: 4, replacement: 'x' })
      .then(() => null, (exc: unknown) => exc);
    expect(cause).toBeInstanceOf(CorrectionConflictError);
    expect((cause as Error).message).toContain('版本冲突');
    expect((cause as Error).message).toContain('刷新');
  });

  it('passes other failures through with the server reason', async () => {
    stubFetch(503, { detail: { message: 'unified memory unavailable' } });
    await expect(submitCorrection('http://x', { targetRef: 'memory:m-1', expectedRevision: 1, replacement: 'x' }))
      .rejects.toThrow('HTTP 503');
  });

  it('refuses to submit an empty replacement or a missing target', async () => {
    await expect(submitCorrection('http://x', { targetRef: 'memory:m-1', expectedRevision: 1, replacement: '   ' }))
      .rejects.toThrow('请填写更正后的内容');
    await expect(submitCorrection('http://x', { targetRef: '  ', expectedRevision: 1, replacement: 'x' }))
      .rejects.toThrow('target_ref');
  });
});

describe('CorrectionDialogBody render', () => {
  const base = { targetRef: 'memory:m-1', expectedRevision: 5 as number | null, replacement: '', onReplacementChange: () => undefined, busy: false, error: '', result: null as null | { revision: number | null; affected: Array<{ recordRef: string; reason: string }> }, onSubmit: () => undefined, onClose: () => undefined };

  it('shows the target, the anchor revision and a disabled submit until input exists', () => {
    const html = renderToStaticMarkup(<CorrectionDialogBody {...base} />);
    expect(html).toContain('纠正这条记忆');
    expect(html).toContain('memory:m-1');
    expect(html).toContain('第 5 版');
    expect(html).toContain('aria-label="更正后的内容"');
    expect(html).toContain('disabled="">提交纠错</button>');
  });

  it('shows the conflict message and never a success toast', () => {
    const html = renderToStaticMarkup(<CorrectionDialogBody {...base} error="版本冲突：这条内容刚被其他操作更新过。请关闭本窗口、刷新页面后再重试（内容不会被覆盖）。" />);
    expect(html).toContain('版本冲突');
    expect(html).toContain('role="alert"');
    expect(html).not.toContain('已提交更正');
  });

  it('lists the affected items after a real success and closes with 完成', () => {
    const html = renderToStaticMarkup(<CorrectionDialogBody {...base} result={{ revision: 6, affected: [{ recordRef: 'memory:m-2', reason: '同一偏好来源' }] }} />);
    expect(html).toContain('已提交更正（新版本 6）');
    expect(html).toContain('memory:m-2：同一偏好来源');
    expect(html).toContain('完成');
  });

  it('notes when the server lists no affected items', () => {
    const html = renderToStaticMarkup(<CorrectionDialogBody {...base} result={{ revision: 2, affected: [] }} />);
    expect(html).toContain('服务端没有列出受影响的其他条目');
  });
});

describe('CorrectionDialog default export', () => {
  it('mounts into the dialog shell', () => {
    // Radix Portal 在服务端渲染不输出内容 —— 静态冒烟只验证组件可挂载不抛异常。
    const html = renderToStaticMarkup(<CorrectionDialog apiBaseUrl="http://x" targetRef="memory:m-1" expectedRevision={5} onClose={() => undefined} />);
    expect(typeof html).toBe('string');
  });
});

describe('normalizeAffected', () => {
  it('tolerates missing fields and legacy shapes', () => {
    expect(normalizeAffected(null)).toEqual([]);
    expect(normalizeAffected({ affected_items: [{ ref: 'r-1' }] })).toEqual([{ recordRef: 'r-1', reason: '' }]);
    expect(normalizeAffected({ affected: [42] })).toEqual([]);
  });
});
