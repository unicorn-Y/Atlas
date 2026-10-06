import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import StatusPanel, { StatusPanelBody, WatermarkCards, fetchStatus } from './StatusPanel';

afterEach(() => vi.unstubAllGlobals());

const payload = {
  authority_id: 'authority-windows-01',
  contract_version: 'UM-WIN-1.0',
  passive_capture_watermark: 42,
  degraded: false,
  watermarks: {
    conversation: { captured: 100, pending: 0 },
    tool: { captured: 55, pending: 2 },
    passive: { captured: 42, gaps: 1 },
  },
  outbox: { pending: 2, last_error: '' },
  worker: { state: 'RUNNING', healthy: true },
};

describe('StatusPanel fetch', () => {
  it('reads GET /api/unified-memory/status', async () => {
    let asked = '';
    vi.stubGlobal('fetch', (async (input: RequestInfo | URL) => {
      asked = String(input);
      return new Response(JSON.stringify(payload), { status: 200 });
    }) as typeof fetch);
    const result = await fetchStatus('http://x');
    expect(asked).toBe('http://x/api/unified-memory/status');
    expect(result.raw.authority_id).toBe('authority-windows-01');
  });
});

describe('StatusPanelBody render', () => {
  it('renders the three watermarks separately (contract §6.1), plus outbox and degraded reason slots', () => {
    const html = renderToStaticMarkup(<StatusPanelBody payload={{ raw: payload }} loading={false} error="" />);
    // 三分水位分开显示，不合并成总水位
    expect(html).toContain('对话水位');
    expect(html).toContain('工具水位');
    expect(html).toContain('被动采集水位');
    expect(html).toContain('已捕获');
    expect(html).toContain('passive_capture_watermark');
    // 未知/嵌套字段以通用小节原样呈现（outbox / worker），不隐藏
    expect(html).toContain('outbox');
    expect(html).toContain('worker');
    expect(html).toContain('RUNNING');
    // 已知标量带中文标签（authority_id → 权威标识），原始值完整可见
    expect(html).toContain('权威标识');
    expect(html).toContain('authority-windows-01');
  });

  it('renders empty lists/objects without crashing and shows an explicit empty placeholder', () => {
    const html = renderToStaticMarkup(<StatusPanelBody payload={{ raw: { watermarks: { conversation: {} } } }} loading={false} error="" />);
    expect(html).toContain('对话水位');
    expect(html).toContain('（无数据）');
  });

  it('shows 501/404 as a degraded note and other failures as an error note', () => {
    const degraded = renderToStaticMarkup(<StatusPanelBody payload={null} loading={false} error="HTTP 501：FEATURE_NOT_READY" />);
    expect(degraded).toContain('服务状态不可用');
    const offline = renderToStaticMarkup(<StatusPanelBody payload={null} loading={false} error="HTTP 404：no route" />);
    expect(offline).toContain('服务状态不可用');
    const failed = renderToStaticMarkup(<StatusPanelBody payload={null} loading={false} error="HTTP 503：断连" />);
    expect(failed).toContain('读取服务状态失败：HTTP 503：断连');
    expect(renderToStaticMarkup(<StatusPanelBody payload={null} loading error="" />)).toContain('正在读取服务状态…');
  });
});

describe('WatermarkCards render', () => {
  it('renders known watermark kinds with Chinese labels and unknown kinds as-is', () => {
    const html = renderToStaticMarkup(<WatermarkCards watermarks={{ passive: 7, mystery: { captured: 1 } }} />);
    expect(html).toContain('被动采集水位');
    expect(html).toContain('mystery');
    expect(html).toContain('已捕获');
  });
});

describe('StatusPanel default export', () => {
  it('renders the refresh button and loading skeleton on mount', () => {
    const html = renderToStaticMarkup(<StatusPanel apiBaseUrl="http://x" connected />);
    expect(html).toContain('刷新');
    expect(html).toContain('正在读取服务状态…');
  });
});
