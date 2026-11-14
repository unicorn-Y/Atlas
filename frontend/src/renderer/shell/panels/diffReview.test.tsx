import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DiffView } from './ChangesPanel';
import { DiffFilePreview, isBinaryDiff, pairDiffLines, SideBySideDiff } from './diffReview';

const diff = '--- a/file.ts\n+++ b/file.ts\n@@ -7,3 +7,4 @@\n unchanged\n-old value\n+new value\n+extra line\n tail\n';

describe('diff reading modes', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('pairs changed blocks with accurate old/new line numbers and unmatched additions', () => {
    expect(pairDiffLines(diff)).toEqual([
      { header: '@@ -7,3 +7,4 @@' },
      { before: { number: 7, text: 'unchanged', changed: false }, after: { number: 7, text: 'unchanged', changed: false } },
      { before: { number: 8, text: 'old value', changed: true }, after: { number: 8, text: 'new value', changed: true } },
      { before: undefined, after: { number: 9, text: 'extra line', changed: true } },
      { before: { number: 9, text: 'tail', changed: false }, after: { number: 10, text: 'tail', changed: false } },
    ]);
  });

  it('renders both sides, line hover previews and wrapping', () => {
    const html = renderToStaticMarkup(<SideBySideDiff diff={diff} path="file.ts" wrap />);
    expect(html).toContain('file.ts 并排差异');
    expect(html).toContain('修改前'); expect(html).toContain('修改后');
    expect(html).toContain('title="old value"'); expect(html).toContain('title="new value"');
    expect(html).toContain('whitespace-pre-wrap');
    expect(html).toContain('bg-danger-soft'); expect(html).toContain('bg-ok-soft');
  });

  it('labels binary diffs without rendering their encoded patch', () => {
    expect(isBinaryDiff('Binary files a/icon.png and b/icon.png differ')).toBe(true);
    const html = renderToStaticMarkup(<SideBySideDiff path="icon.png" diff={'GIT binary patch\nliteral 999\nencoded payload'} />);
    expect(html).toContain('二进制文件');
    expect(html).not.toContain('encoded payload');
  });

  it('renders a bounded file hover preview and retains deletion lines that resemble diff headers', () => {
    const preview = renderToStaticMarkup(<DiffFilePreview path="file.ts" diff={Array.from({ length: 30 }, (_, index) => `line ${index}`).join('\n')} />);
    expect(preview).toContain('file.ts 改动预览');
    expect(preview).toContain('line 19');
    expect(preview).not.toContain('line 20');
    expect(preview).toContain('预览前 20 行');
    expect(pairDiffLines('@@ -1 +1 @@\n--- old\n+++ new')).toContainEqual({
      before: { number: 1, text: '-- old', changed: true }, after: { number: 1, text: '++ new', changed: true },
    });
  });

  it('exposes both reading modes from the real run diff component', () => {
    vi.stubGlobal('window', {});
    const html = renderToStaticMarkup(<DiffView path="file.ts" diff={diff} defaultLayout="split" onAdd={vi.fn()} onEdit={vi.fn()} onRemove={vi.fn()} />);
    expect(html).toContain('差异阅读设置');
    expect(html).toContain('自动换行');
    expect(html).toContain('file.ts 并排差异');
  });
});
