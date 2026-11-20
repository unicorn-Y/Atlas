import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PluginsPanel } from './ConsolePage';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('plugin peer compatibility risk acceptance', () => {
  it('requires a checked explicit acceptRisk before posting the exact plugin/runtime exemption', async () => {
    let current = {
      name: 'plugin-a', version: '2.4.1', display_name: 'Plugin A', enabled: false, loaded: false,
      compatibility: {
        name: 'plugin-a', version: '2.4.1', runtime_version: '0.1.0',
        peers: { atlas: '^9.0.0' }, exempted: false,
      },
    };
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      const body = url.endsWith('/api/plugins')
        ? { plugins: [current] }
        : url.endsWith('/api/plugin-marketplaces')
          ? { marketplaces: [] }
          : { report: { loaded: [], skipped: [] } };
      if (url.endsWith('/compatibility-exemption') && init?.method === 'POST') {
        current = { ...current, compatibility: { ...current.compatibility, exempted: true } };
      } else if (url.endsWith('/compatibility-exemption') && init?.method === 'DELETE') {
        current = { ...current, compatibility: { ...current.compatibility, exempted: false } };
      }
      return { ok: true, json: async () => body } as Response;
    }));

    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PluginsPanel apiBaseUrl="http://127.0.0.1:8765" />); });
    const visibleText = (role: 'alert' | 'status') => view.root.findAllByProps({ role })
      .flatMap((instance) => instance.findAll((node) => node.type === 'small'))
      .flatMap((node) => node.children)
      .filter((child): child is string => typeof child === 'string')
      .join('');
    expect(visibleText('alert')).toContain('peer 范围不兼容');
    const button = () => view.root.findAllByType('button').find((item) =>
      item.children.join('').includes('明确接受风险并豁免'))!;
    expect(button().props.disabled).toBe(true);
    expect(requests.some((request) => request.url.includes('/compatibility-exemption'))).toBe(false);

    const checkbox = view.root.findAllByType('input').find((item) => item.props.type === 'checkbox')!;
    act(() => { checkbox.props.onChange({ target: { checked: true } }); });
    expect(button().props.disabled).toBe(false);
    await act(async () => { await button().props.onClick(); });

    const grant = requests.find((request) => request.url.endsWith('/api/plugins/plugin-a/compatibility-exemption'))!;
    expect(grant.init?.method).toBe('POST');
    expect(JSON.parse(String(grant.init?.body))).toEqual({
      pluginVersion: '2.4.1', runtimeVersion: '0.1.0', acceptRisk: true,
    });

    await act(async () => { await Promise.resolve(); });
    expect(visibleText('status')).toContain('豁免只适用于');
    const revoke = view.root.findAllByType('button').find((item) =>
      item.children.join('').includes('撤销精确版本豁免'))!;
    await act(async () => { await revoke.props.onClick(); });
    expect(requests.some((request) => request.url.endsWith('/compatibility-exemption') && request.init?.method === 'DELETE')).toBe(true);
    expect(visibleText('alert')).toContain('peer 范围不兼容');
    act(() => view.unmount());
  });
});

describe('plugin install operation recovery', () => {
  it('starts marketplace installs through the marketplace request endpoint', async () => {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
      removeItem: (key: string) => { storage.delete(key); },
    });
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    let requestId = '';
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith('/api/plugins')) return { ok: true, json: async () => ({ plugins: [] }) } as Response;
      if (url.endsWith('/api/plugin-marketplaces')) return { ok: true, json: async () => ({ marketplaces: [{ name: 'fixture-market', source: 'local' }] }) } as Response;
      if (url.endsWith('/api/plugin-marketplaces/fixture-market/plugins')) {
        return { ok: true, json: async () => ({ plugins: [{ name: 'market-plugin', displayName: 'Market plugin' }] }) } as Response;
      }
      if (url.endsWith('/api/plugin-marketplaces/fixture-market/install') && init?.method === 'POST') {
        requestId = String((JSON.parse(String(init.body)) as { requestId: string }).requestId);
        return { ok: true, status: 200, json: async () => ({ requestId, status: 'queued' }) } as Response;
      }
      if (url.includes(`/api/plugins/install/${requestId}?`)) {
        return { ok: true, json: async () => ({ requestId, status: 'running' }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }));
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PluginsPanel apiBaseUrl="http://127.0.0.1:8918" />); });
    const browse = view.root.findAllByType('button').find((item) => item.children.join('') === '浏览')!;
    await act(async () => { await browse.props.onClick(); });
    const install = view.root.findAllByType('button').find((item) => item.children.join('') === '安装')!;
    await act(async () => { await install.props.onClick(); });
    const post = requests.find((item) => item.url.endsWith('/api/plugin-marketplaces/fixture-market/install') && item.init?.method === 'POST');
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ plugin: 'market-plugin' });
    expect(storage.get('atlas.plugin.install.requestId')).toBe(requestId);
    act(() => view.unmount());
  });

  it('routes scoped npm specs directly into the cancellable npm request lifecycle', async () => {
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => { storage.set(key, value); },
      removeItem: (key: string) => { storage.delete(key); },
    });
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    let requestId = '';
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith('/api/plugins')) return { ok: true, json: async () => ({ plugins: [] }) } as Response;
      if (url.endsWith('/api/plugin-marketplaces')) return { ok: true, json: async () => ({ marketplaces: [] }) } as Response;
      if (url.endsWith('/api/plugins/install') && init?.method === 'POST') {
        requestId = String((JSON.parse(String(init.body)) as { requestId: string }).requestId);
        return { ok: true, status: 200, json: async () => ({ requestId, status: 'queued' }) } as Response;
      }
      if (url.includes(`/api/plugins/install/${requestId}?`)) {
        return { ok: true, json: async () => ({ requestId, status: 'running' }) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }));
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PluginsPanel apiBaseUrl="http://127.0.0.1:8918" />); });
    const source = view.root.findAllByType('input').find((item) => item.props['aria-label'] === '插件来源')!;
    act(() => { source.props.onChange({ target: { value: '@fixture/npm-plugin@^1.0.0' } }); });
    await act(async () => { await view.root.findAllByType('form')[0].props.onSubmit({ preventDefault() {} }); });
    const post = requests.find((item) => item.url.endsWith('/api/plugins/install') && item.init?.method === 'POST');
    expect(post).toBeDefined();
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ source: '@fixture/npm-plugin@^1.0.0', sourceType: 'npm' });
    expect(requests.some((item) => item.url.endsWith('/api/plugins/validate'))).toBe(false);
    expect(storage.get('atlas.plugin.install.requestId')).toBe(requestId);
    act(() => view.unmount());
  });

  it('keeps the request id pollable while the first POST is pending and GET reports unknown', async () => {
    vi.useFakeTimers();
    const storage = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => { storage.delete(key); },
    });
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    let operationId = '';
    let stateReads = 0;
    let releasePost!: (response: Response) => void;
    let announcePost!: () => void;
    const postStarted = new Promise<void>((resolve) => { announcePost = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      if (url.endsWith('/api/plugins')) return { ok: true, json: async () => ({ plugins: [] }) } as Response;
      if (url.endsWith('/api/plugin-marketplaces')) return { ok: true, json: async () => ({ marketplaces: [] }) } as Response;
      if (url.endsWith('/api/plugins/validate')) return { ok: true, json: async () => ({
        valid: true, source: 'fixture', plugin: { name: 'fixture-plugin', version: '1.0.0' },
        diagnostics: [], summary: { errors: 0, warnings: 0 },
      }) } as Response;
      if (url.endsWith('/api/plugins/install') && init?.method === 'POST') {
        operationId = String((JSON.parse(String(init.body)) as { requestId: string }).requestId);
        announcePost();
        return await new Promise<Response>((resolve) => { releasePost = resolve; });
      }
      if (url.includes(`/api/plugins/install/${operationId}?`)) {
        stateReads += 1;
        const body = stateReads === 1
          ? { requestId: operationId, status: 'unknown' }
          : stateReads < 3 ? { requestId: operationId, status: 'queued' }
            : { requestId: operationId, status: 'completed', report: { loaded: [] } };
        return { ok: true, json: async () => body } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    }));

    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PluginsPanel apiBaseUrl="http://127.0.0.1:8918" />); });
    const source = view.root.findAllByType('input').find((item) => item.props['aria-label'] === '插件来源')!;
    act(() => { source.props.onChange({ target: { value: 'C:/fixture/plugin' } }); });
    await act(async () => { await view.root.findAllByType('form')[0].props.onSubmit({ preventDefault() {} }); });
    const continueInstall = () => view.root.findAllByType('button').find((item) => item.children.join('').includes('校验通过，继续安装'))!;
    await act(async () => { void continueInstall().props.onClick(); await Promise.resolve(); });
    await postStarted;
    await act(async () => { await vi.advanceTimersByTimeAsync(300); });
    expect(storage.get('atlas.plugin.install.requestId')).toBe(operationId);
    expect(stateReads).toBeGreaterThan(0);
    const cancel = view.root.findAllByType('button').find((item) => item.children.join('').includes('取消安装'))!;
    expect(cancel.props.disabled).toBe(true);
    expect(view.root.findAllByType('p').some((node) => node.children.join('').includes('正在校验来源并创建安装任务'))).toBe(true);

    await act(async () => {
      releasePost({ ok: true, status: 200, json: async () => ({ requestId: operationId, status: 'queued' }) } as Response);
      await Promise.resolve(); await Promise.resolve();
    });
    expect(requests.filter((request) => request.url.endsWith('/api/plugins/install') && request.init?.method === 'POST')).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1200); });
    expect(view.root.findAll((node) => node.props.role === 'status').some((node) => node.children.join('').includes('插件安装完成'))).toBe(true);
    act(() => view.unmount());
  });

  it('does not re-POST a pending descriptor when the service reports an unknown id after restart', async () => {
    vi.useFakeTimers();
    const storage = new Map<string, string>([
      ['atlas.plugin.install.requestId', 'old-runtime-id'],
      ['atlas.plugin.install.pending', JSON.stringify({ requestId: 'old-runtime-id', source: 'C:/fixture/plugin' })],
    ]);
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => { storage.delete(key); },
    });
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      const body = url.endsWith('/api/plugins') ? { plugins: [] }
        : url.endsWith('/api/plugin-marketplaces') ? { marketplaces: [] }
          : url.includes('/api/plugins/install/old-runtime-id?') ? { requestId: 'old-runtime-id', status: 'unknown' } : {};
      return { ok: true, status: 200, json: async () => body } as Response;
    }));
    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PluginsPanel apiBaseUrl="http://127.0.0.1:8918" />); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(requests.some((request) => request.url.endsWith('/api/plugins/install') && request.init?.method === 'POST')).toBe(false);
    expect(view.root.findAll((node) => node.props.role === 'status').some((node) =>
      node.children.join('').includes('找不到该安装任务'))).toBe(true);
    act(() => view.unmount());
  });

  it('polls a request id, approves only the package reported by pnpm, and shows completion', async () => {
    vi.useFakeTimers();
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    let stateReads = 0;
    let approved = false;
    let operationId = '';
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      requests.push({ url, init });
      let body: unknown = {};
      if (url.endsWith('/api/plugins')) body = { plugins: [] };
      else if (url.endsWith('/api/plugin-marketplaces')) body = { marketplaces: [] };
      else if (url.endsWith('/api/plugins/validate')) body = {
        valid: true, source: 'fixture', plugin: { name: 'fixture-plugin', version: '1.0.0' },
        diagnostics: [], summary: { errors: 0, warnings: 0 },
      };
      else if (url.endsWith('/api/plugins/install') && init?.method === 'POST') {
        operationId = String((JSON.parse(String(init.body)) as { requestId: string }).requestId);
        body = { requestId: operationId, status: 'queued' };
      } else if (url.includes(`/api/plugins/install/${operationId}?`)) {
        stateReads += 1;
        body = approved
          ? { requestId: operationId, status: 'completed', result: { name: 'fixture-plugin' }, report: { loaded: [] } }
          : { requestId: operationId, status: 'awaiting_approval', approvalRequired: ['@fixture/native-build'] };
      } else if (url.endsWith('/api/plugins/script-approvals')) {
        approved = true;
        body = { packageName: '@fixture/native-build', expiresAt: '2099-01-01T00:00:00Z' };
      }
      return { ok: true, status: 200, json: async () => body } as Response;
    }));

    let view!: ReactTestRenderer;
    await act(async () => { view = create(<PluginsPanel apiBaseUrl="http://127.0.0.1:8918" />); });
    const source = view.root.findAllByType('input').find((item) => item.props['aria-label'] === '插件来源')!;
    act(() => { source.props.onChange({ target: { value: 'C:/fixture/plugin' } }); });
    const form = view.root.findAllByType('form')[0];
    await act(async () => { await form.props.onSubmit({ preventDefault() {} }); });
    const continueInstall = () => view.root.findAllByType('button').find((item) => item.children.join('').includes('校验通过，继续安装'))!;
    await act(async () => { await continueInstall().props.onClick(); });
    expect(requests.some((request) => request.url.endsWith('/api/plugins/install') && request.init?.method === 'POST')).toBe(true);

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const approve = view.root.findAllByType('button').find((item) => item.children.join('').includes('允许此包脚本（30 天）'))!;
    expect(JSON.stringify(view.toJSON())).toContain('@fixture/native-build');
    await act(async () => { await approve.props.onClick(); });
    const approval = requests.find((request) => request.url.endsWith('/api/plugins/script-approvals'))!;
    expect(JSON.parse(String(approval.init?.body))).toEqual({ packageName: '@fixture/native-build', days: 30, requestId: operationId });

    await act(async () => { await vi.advanceTimersByTimeAsync(600); });
    expect(view.root.findAll((node) => node.props.role === 'status').some((node) => node.children.join('').includes('插件安装完成'))).toBe(true);
    act(() => view.unmount());
    vi.useRealTimers();
  });
});
