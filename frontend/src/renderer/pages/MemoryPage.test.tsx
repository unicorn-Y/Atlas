import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import MemoryPage from './MemoryPage';

afterEach(() => vi.unstubAllGlobals());

const noop = () => undefined;

/** 挂载测试（静态渲染）：effects 不执行，验证页面骨架与 S5 视图在场。 */
describe('MemoryPage mount (S5)', () => {
  it('keeps the S5 main tabs and hides frozen learning view entry', () => {
    const html = renderToStaticMarkup(
      <MemoryPage apiBaseUrl="http://x" connected onToast={noop} onPendingChange={noop} />,
    );
    // S5 主视图 tab：时间线、它对我的了解、记忆列表、人事、提醒与待办、状态
    expect(html).toContain('时间线');
    expect(html).toContain('它对我的了解');
    expect(html).toContain('记忆列表');
    expect(html).toContain('人事');
    expect(html).toContain('提醒与待办');
    expect(html).toContain('状态');
    // 旧入口兼容保留：待确认 / 资料
    expect(html).toContain('待确认');
    expect(html).toContain('资料');
    // S5 冻结功能隐藏：学到的方法 (LearningView) 入口不应出现
    expect(html).not.toContain('学到的方法');
    // 共 8 个 tab 按钮 (时间线, 它对我的了解, 记忆列表, 人事, 提醒与待办, 状态, 待确认, 资料)
    expect((html.match(/aria-pressed=/g) ?? []).length).toBe(8);
  });

  it('defaults to the timeline main view with its loading state', () => {
    const html = renderToStaticMarkup(
      <MemoryPage apiBaseUrl="http://x" connected onToast={noop} onPendingChange={noop} />,
    );
    expect(html).toContain('正在读取时间线…');
    expect(html).toContain('aria-label="日常时间线"');
  });

  it('shows the offline note instead of data when the backend is not connected', () => {
    const html = renderToStaticMarkup(
      <MemoryPage apiBaseUrl="http://x" connected={false} onToast={noop} />,
    );
    expect(html).toContain('Atlas 后端未连接');
  });

  it('hides the legacy search field and add buttons on the new main views', () => {
    const html = renderToStaticMarkup(
      <MemoryPage apiBaseUrl="http://x" connected onToast={noop} />,
    );
    expect(html).not.toContain('aria-label="搜索记忆"');
    expect(html).not.toContain('添加记忆');
  });
});
