import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import MemoryPage from './MemoryPage';

afterEach(() => vi.unstubAllGlobals());

const noop = () => undefined;

/** 挂载测试（静态渲染）：effects 不执行，验证页面骨架与新旧入口同时在场。 */
describe('MemoryPage mount', () => {
  it('keeps the legacy facts/pending/knowledge entries alongside the new main tabs', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected onToast={noop} onPendingChange={noop} />);
    // 新主视图六个 tab（T12.1）
    expect(html).toContain('时间线');
    expect(html).toContain('当前理解');
    expect(html).toContain('人事');
    expect(html).toContain('待办');
    expect(html).toContain('学到的方法');
    expect(html).toContain('服务状态');
    // 旧入口兼容保留：记忆 / 待确认 / 资料 三个 seg 按钮仍在
    expect(html).toContain('待确认');
    expect(html).toContain('资料');
    // 新旧共 9 个 tab 按钮
    expect((html.match(/aria-pressed=/g) ?? []).length).toBe(9);
  });

  it('defaults to the timeline main view with its loading state', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected onToast={noop} onPendingChange={noop} />);
    expect(html).toContain('正在读取时间线…');
    expect(html).toContain('aria-label="日常时间线"');
  });

  it('shows the offline note instead of data when the backend is not connected', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected={false} onToast={noop} />);
    expect(html).toContain('Atlas 后端未连接');
  });

  it('hides the legacy search field and add buttons on the new main views', () => {
    const html = renderToStaticMarkup(<MemoryPage apiBaseUrl="http://x" connected onToast={noop} />);
    expect(html).not.toContain('aria-label="搜索记忆"');
    expect(html).not.toContain('添加记忆');
  });
});
