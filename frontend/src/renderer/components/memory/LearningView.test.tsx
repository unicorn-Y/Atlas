import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import LearningView, { LearningRow, fetchLearning, isVerifiedMethod, normalizeLearning } from './LearningView';

afterEach(() => vi.unstubAllGlobals());

describe('LearningView normalize', () => {
  it('keeps title/kind/stage and separates verified methods from unverified candidates', () => {
    const page = normalizeLearning({
      items: [
        { id: 'm-1', title: 'Windows 下用 where 查命令路径', type: 'METHOD', status: 'VERIFIED' },
        { id: 'm-2', title: '批量重命名先 dry-run', type: 'STRATEGY', status: 'CANDIDATE', detail: '还没有真实结果确认' },
        { id: 'm-3', title: '缺端到端时序验证', type: 'CAPABILITY_GAP' },
        { title: '没有 id 也没有 title' },
      ],
      next_cursor: 'l2',
    });
    expect(page.nextCursor).toBe('l2');
    expect(page.items).toHaveLength(4);
    expect(isVerifiedMethod(page.items[0])).toBe(true);
    expect(isVerifiedMethod(page.items[1])).toBe(false);
    // 两者都不是 → 归入候选（宁保守，不装成已验证）
    expect(isVerifiedMethod(page.items[2])).toBe(false);
  });
});

describe('LearningView fetch — 501 degraded path', () => {
  it('rejects with HTTP 501 which the view maps to the degraded note', async () => {
    vi.stubGlobal('fetch', (async () => new Response(
      JSON.stringify({ detail: { error: 'FEATURE_NOT_READY' } }), { status: 501 },
    )) as typeof fetch);
    await expect(fetchLearning('http://x', { cursor: null })).rejects.toThrow('HTTP 501');
  });
});

describe('LearningView render', () => {
  it('renders kind labels and the detail line', () => {
    const html = renderToStaticMarkup(<LearningRow item={{ id: 'm-1', title: '批量重命名先 dry-run', kind: 'COUNTEREXAMPLE', stage: '', status: 'CANDIDATE', detail: 'R-r 兼容性反例' }} />);
    expect(html).toContain('批量重命名先 dry-run');
    expect(html).toContain('反例');
    expect(html).toContain('R-r 兼容性反例');
  });

  it('renders the loading skeleton and explains the candidate/verified split', () => {
    const html = renderToStaticMarkup(<LearningView apiBaseUrl="http://x" connected />);
    expect(html).toContain('aria-label="学到的方法"');
    expect(html).toContain('正在读取学到的方法…');
    expect(html).toContain('试验候选不会标成已验证');
  });
});
