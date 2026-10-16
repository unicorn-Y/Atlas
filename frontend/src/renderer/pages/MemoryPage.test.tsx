import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import MemoryPage from './MemoryPage';
import { MOCK_MEMLIB_ENABLED } from '../components/memory/mockMemlib';

const noop = () => undefined;

/** 静态渲染：effects 不执行，只验证页面骨架。 */
describe('MemoryPage', () => {
  it('renders the W2 browser navigation, search, empty state, and disconnected state without mock data', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected={false} onToast={noop} />);
    expect(html).toContain('aria-label="记忆分区"');
    expect(html).toContain('aria-label="搜索全部记忆"');
    for (const label of ['搜索', '时间线', '项目', '人']) expect(html).toContain(label);
    expect(html).toContain('还没有经历记录');
    expect(html).toContain('记忆服务未连接');
    expect(MOCK_MEMLIB_ENABLED).toBe(false);
  });
});
