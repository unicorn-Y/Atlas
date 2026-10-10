import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import MemoryPage from './MemoryPage';

const noop = () => undefined;

/** 静态渲染：effects 不执行，只验证页面骨架。 */
describe('MemoryPage', () => {
  it('shows the MemOS-backed tabs and none of the retired MemoryOS ones', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected onToast={noop} onPendingChange={noop} />);
    for (const label of ['关于你', '记忆变动', '经验与技能', '提醒', '资料']) expect(html).toContain(label);
    for (const retired of ['时间线', '它对我的了解', '记忆列表', '人事', '待确认', '未启用']) expect(html).not.toContain(retired);
    expect((html.match(/aria-pressed=/g) ?? []).length).toBe(5 + 1); // 5 tabs + 关于你's history toggle
  });

  it('opens on 关于你', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected onToast={noop} />);
    expect(html).toContain('aria-label="关于你"');
    expect(html).toContain('正在读取…');
  });

  it('shows the offline note when the backend is not connected', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected={false} onToast={noop} />);
    expect(html).toContain('Atlas 后端未连接');
  });
});
