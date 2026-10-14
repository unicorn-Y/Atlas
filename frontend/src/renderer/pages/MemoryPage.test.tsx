import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import MemoryPage from './MemoryPage';

const noop = () => undefined;

/** 静态渲染：effects 不执行，只验证页面骨架。 */
describe('MemoryPage', () => {
  it('shows the memory library tabs and none of the retired memory views', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected onToast={noop} />);
    for (const label of ['今天', '人和事', '变动记录', '提醒', '资料']) expect(html).toContain(label);
    for (const retired of ['待确认', '经验与技能', '记忆列表', '时间线']) expect(html).not.toContain(retired);
  });
});
