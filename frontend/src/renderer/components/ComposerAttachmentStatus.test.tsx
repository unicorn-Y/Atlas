import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { ComposerAttachmentStatus } from './Composer';

describe('ComposerAttachmentStatus', () => {
  it('shows staging progress with a cancel action', () => {
    const html = renderToStaticMarkup(<ComposerAttachmentStatus progress="暂存 report.pdf（42%）" onCancel={vi.fn()} />);
    expect(html).toContain('暂存 report.pdf（42%）');
    expect(html).toContain('取消');
    expect(html).toContain('role="status"');
  });

  it('shows attachment read failures with a retry action', () => {
    const html = renderToStaticMarkup(<ComposerAttachmentStatus failedCount={2} onRetry={vi.fn()} />);
    expect(html).toContain('2 个附件读取失败');
    expect(html).toContain('重试');
  });
});
