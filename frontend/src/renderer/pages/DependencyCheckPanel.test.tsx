import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import DependencyCheckPanel from './DependencyCheckPanel';

describe('dependency check settings panel', () => {
  it('exposes a read-only one-click check and explains blockers', () => {
    const html = renderToStaticMarkup(<DependencyCheckPanel apiBaseUrl="http://127.0.0.1:8765" />);
    expect(html).toContain('检查依赖');
    expect(html).toContain('只读检查');
    expect(html).toContain('使用内置 Node');
  });
});
