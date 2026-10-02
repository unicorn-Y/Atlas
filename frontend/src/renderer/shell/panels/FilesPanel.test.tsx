import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import FilesPanel, { ancestorPaths } from './FilesPanel';

describe('ancestorPaths', () => {
  it('returns every ancestor directory of a nested file, accumulated', () => {
    expect(ancestorPaths('src/app.py')).toEqual(['src']);
    expect(ancestorPaths('a/b/c.ts')).toEqual(['a', 'a/b']);
  });

  it('returns nothing for a top-level file and filters empty segments', () => {
    expect(ancestorPaths('c.ts')).toEqual([]);
    expect(ancestorPaths('/a/b.ts')).toEqual(['a']);
    expect(ancestorPaths('')).toEqual([]);
  });
});

describe('FilesPanel static rendering', () => {
  it('shows the empty state without a workspace', () => {
    const html = renderToStaticMarkup(<FilesPanel workspace={null} onChooseWorkspace={() => undefined} refreshKey="r" onPreview={() => undefined} />);
    expect(html).toContain('还没有选工作目录');
  });

  it('shows the reading hint while the root listing has not loaded', () => {
    const html = renderToStaticMarkup(<FilesPanel workspace="C:/ws" onChooseWorkspace={() => undefined} refreshKey="r" onPreview={() => undefined} />);
    expect(html).toContain('正在读取目录');
  });
});
