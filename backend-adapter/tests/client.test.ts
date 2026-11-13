import { afterEach, describe, expect, it, vi } from 'vitest';
import { BackendAdapter, BackendError } from '../src/client';

class MockWebSocket extends EventTarget {
  static OPEN = 1;
  static instances: MockWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];

  constructor(readonly url: string) {
    super();
    MockWebSocket.instances.push(this);
  }

  send(data: string) { this.sent.push(data); }
  open() { this.readyState = 1; this.dispatchEvent(new Event('open')); }
  receive(data: unknown) { this.dispatchEvent(Object.assign(new Event('message'), { data: JSON.stringify(data) })); }
  disconnect() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
  close() { this.disconnect(); }
}

const runtimeEvent = (sequence: number, event: string) => ({
  type: 'agent_event', event_id: `event-${sequence}`, run_id: 'run-1', sequence,
  timestamp: new Date(0).toISOString(), event, data: {},
});

const flushAsync = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  MockWebSocket.instances = [];
});

describe('BackendAdapter availability and recovery', () => {
  it('reports an undelivered stop instead of silently ignoring it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true } as Response)));
    vi.stubGlobal('WebSocket', MockWebSocket);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    expect(() => adapter.cancelRun('disconnected-run')).toThrow(BackendError);
  });

  it('sends subtask steering over its owning run socket with run and event ids', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.3' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const running = adapter.startRun({ type: 'run.start', run_id: 'run-1', content: 'delegate', conversation_id: 'conv-1' }, () => undefined);
    while (!MockWebSocket.instances.length) await flushAsync();
    const socket = MockWebSocket.instances[0];
    socket.open();
    adapter.steerSubtask('run-1', 'child-1', 'check one more edge case', 'steer-1');

    expect(JSON.parse(socket.sent[1])).toEqual({
      type: 'subtask.message', run_id: 'run-1', subtask_id: 'child-1', text: 'check one more edge case', event_id: 'steer-1',
    });
    socket.receive(runtimeEvent(1, 'run.started'));
    socket.receive(runtimeEvent(2, 'run.completed'));
    await running;
  });

  it('loads and saves provider configuration without a mock-only path', async () => {
    const configuration = { gateway_base_url: 'https://api.example.test/v1', api_key_configured: true, models: [], current: '' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => configuration } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => configuration } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.getConfiguration()).resolves.toEqual(configuration);
    await adapter.updateConfiguration(configuration.gateway_base_url, 'secret');
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/settings/configuration');
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ gateway_base_url: configuration.gateway_base_url, api_key: 'secret' }) });
  });

  it('creates a conversation through the backend API', async () => {
    const created = { id: 'conversation-1', title: '新对话' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => created } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.createConversation()).resolves.toEqual(created);
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/conversations');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST', body: JSON.stringify({ title: '新对话' }) });
  });

  it('can recover from an unavailable backend when initialized again', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: true } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });

    await expect(adapter.initialize()).resolves.toBe('mock');
    expect(adapter.availabilityError).toBe('连不上 Atlas 后端，请确认它已经启动');
    await expect(adapter.initialize()).resolves.toBe('backend');
    expect(adapter.availabilityError).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('keeps the backend live on a server failure and clears the error after a health check', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'temporarily unavailable' }) } as Response)
      .mockResolvedValueOnce({ ok: true } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.getModels()).rejects.toThrow('temporarily unavailable');
    // A 5xx proves the backend answered; only network failures drop to mock (BOOT-1 review).
    expect(adapter.mode).toBe('backend');
    expect(adapter.availabilityError).toBe('temporarily unavailable');
    await expect(adapter.initialize()).resolves.toBe('backend');
    expect(adapter.availabilityError).toBeNull();
  });

  it('throws Chinese-primary errors and keeps the raw English line in detail', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    const error = await adapter.getModels().then(() => null, (caught: unknown) => caught);
    expect(error).toBeInstanceOf(BackendError);
    expect((error as BackendError).message).toBe('后端请求失败（HTTP 500）');
    expect((error as BackendError).detail).toBe('Backend request failed (500)');
  });

  it('accepts successful empty responses for void backend operations', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, status: 204, json: async () => { throw new SyntaxError('empty response'); } } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.deleteFact('temporary')).resolves.toBeUndefined();
  });

  it('resumes the same run after disconnect and ignores replayed events', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', { setTimeout: (callback: TimerHandler, delay?: number) => setTimeout(callback, delay) });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.2' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', {
      values: new Map<string, string>(),
      getItem(key: string) { return this.values.get(key) ?? null; },
      setItem(key: string, value: string) { this.values.set(key, value); },
      removeItem(key: string) { this.values.delete(key); },
    });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const events: number[] = [];
    const running = adapter.startRun({ type: 'run.start', run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' }, (event) => events.push(event.sequence));

    await vi.advanceTimersByTimeAsync(0);
    const first = MockWebSocket.instances[0];
    first.open();
    expect(JSON.parse(first.sent[0]).type).toBe('run.start');
    first.receive(runtimeEvent(1, 'run.started'));
    first.disconnect();
    await vi.advanceTimersByTimeAsync(1_000);

    const resumed = MockWebSocket.instances[1];
    expect(resumed).toBeDefined();
    resumed.open();
    expect(JSON.parse(resumed.sent[0])).toEqual({ type: 'resume', run_id: 'run-1', after_sequence: 1 });
    resumed.receive(runtimeEvent(1, 'run.started'));
    resumed.receive(runtimeEvent(2, 'message.completed'));
    resumed.receive(runtimeEvent(3, 'run.completed'));
    await running;

    expect(events).toEqual([1, 2, 3]);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('repairs a sequence gap by replaying from the last contiguous cursor', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', { setTimeout: (callback: TimerHandler, delay?: number) => setTimeout(callback, delay) });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/api/health')
      ? { ok: true } as Response
      : { ok: true, json: async () => ({ version: '1.2' }) } as Response));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const events: number[] = [];
    const running = adapter.startRun({ type: 'run.start', run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' }, (event) => events.push(event.sequence));

    await vi.advanceTimersByTimeAsync(0);
    const first = MockWebSocket.instances[0];
    first.open();
    first.receive(runtimeEvent(1, 'run.started'));
    first.receive(runtimeEvent(3, 'run.completed'));
    await vi.advanceTimersByTimeAsync(1_000);

    const repair = MockWebSocket.instances[1];
    repair.open();
    expect(JSON.parse(repair.sent[0])).toEqual({ type: 'resume', run_id: 'run-1', after_sequence: 1 });
    repair.receive(runtimeEvent(2, 'message.completed'));
    repair.receive(runtimeEvent(3, 'run.completed'));
    await running;
    expect(events).toEqual([1, 2, 3]);
  });

  it('repairs a sequence gap while following an already-running run', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', { setTimeout: (callback: TimerHandler, delay?: number) => setTimeout(callback, delay) });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true } as Response)));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const events: number[] = [];
    const following = adapter.attachRun('run-1', (event) => events.push(event.sequence));

    await vi.advanceTimersByTimeAsync(0);
    const first = MockWebSocket.instances[0];
    first.open();
    first.receive(runtimeEvent(2, 'message.completed'));
    await vi.advanceTimersByTimeAsync(1_000);
    const repair = MockWebSocket.instances[1];
    repair.open();
    expect(JSON.parse(repair.sent[0])).toEqual({ type: 'resume', run_id: 'run-1', after_sequence: 0 });
    repair.receive(runtimeEvent(1, 'run.started'));
    repair.receive(runtimeEvent(2, 'message.completed'));
    repair.receive(runtimeEvent(3, 'run.completed'));
    await following;
    expect(events).toEqual([1, 2, 3]);
  });

  it('starts runs on any runtime protocol from 1.2 up and refuses older ones', async () => {
    const connect = async (version: string) => {
      vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version }) } as Response));
      vi.stubGlobal('WebSocket', MockWebSocket);
      vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
      const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
      await adapter.initialize();
      return adapter.startRun({ type: 'run.start', run_id: `run-${version}`, content: 'hello', conversation_id: 'conv-1' }, () => undefined);
    };

    for (const version of ['1.3', '1.10', '2.0']) {
      MockWebSocket.instances = [];
      const running = connect(version);
      await flushAsync();
      expect(MockWebSocket.instances, `protocol ${version}`).toHaveLength(1);
      MockWebSocket.instances[0].open();
      MockWebSocket.instances[0].receive({ ...runtimeEvent(1, 'run.completed'), run_id: `run-${version}` });
      await running;
    }
    await expect(connect('1.1')).rejects.toThrow('版本太旧');
    // 中文主文案之外，原始英文保留在 detail 里供界面展开。
    await expect(connect('1.1').catch((error: BackendError) => error.detail)).resolves.toBe('Backend Agent Runtime 1.2 is required for event runs and approvals');
  });

  it('rejects a second start for a run that is already connecting', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.2' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const request = { type: 'run.start' as const, run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' };
    const running = adapter.startRun(request, () => undefined);

    await flushAsync();
    await expect(Promise.race([
      adapter.startRun(request, () => undefined),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('duplicate start did not reject')), 50)),
    ])).rejects.toThrow('这个任务已经在运行了');
    expect(MockWebSocket.instances).toHaveLength(1);
    MockWebSocket.instances[0].open();
    MockWebSocket.instances[0].receive(runtimeEvent(1, 'run.completed'));
    await running;
  });

  it('surfaces a websocket connection failure and releases the run reservation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.2' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const request = { type: 'run.start' as const, run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' };
    const failed = adapter.startRun(request, () => undefined);
    await flushAsync();
    MockWebSocket.instances[0].dispatchEvent(new Event('error'));
    await expect(failed).rejects.toThrow('连不上后端的任务通道');

    await expect(adapter.initialize()).resolves.toBe('backend');
    const retried = adapter.startRun(request, () => undefined);
    await flushAsync();
    MockWebSocket.instances[1].open();
    MockWebSocket.instances[1].receive(runtimeEvent(1, 'run.completed'));
    await retried;
    expect(MockWebSocket.instances).toHaveLength(2);
  });
});

describe('BackendAdapter provider catalog and reasoning stages', () => {
  it('reads providers and reasoning stages from the backend API', async () => {
    const providers = [{ id: 'deepseek', label: '深度求索', hermes_provider: 'deepseek', api_mode: 'openai', default_base_url: 'https://api.deepseek.com/v1', configured: true, base_url: null, key_count: 1, keys: [{ id: 'k_ab12cd', label: '主密钥', cooldown_until: null, last_error: null, request_count: 3 }] }];
    const stages = { enabled: false, planning: 'high', execution: 'medium', verification: 'high' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => providers } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => stages } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.getProviders()).resolves.toEqual(providers);
    await expect(adapter.getReasoningStages()).resolves.toEqual(stages);
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/providers');
    expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8765/api/models/reasoning-stages');
  });

  it('saves provider configuration, keys and reasoning stages through the backend API', async () => {
    const empty = { ok: true, status: 204, json: async () => { throw new SyntaxError('empty response'); } } as Response;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ id: 'k_ef23gh', label: '备用' }) } as Response)
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ enabled: true, planning: 'low', execution: 'medium', verification: 'high' }) } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.updateProviderConfig('deepseek', 'https://api.deepseek.com/v1')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/providers/deepseek/config');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ base_url: 'https://api.deepseek.com/v1' }) });

    await expect(adapter.addProviderKey('deepseek', 'sk-secret', '备用')).resolves.toEqual({ id: 'k_ef23gh', label: '备用' });
    expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8765/api/providers/deepseek/keys');
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'POST', body: JSON.stringify({ secret: 'sk-secret', label: '备用' }) });
    expect(String(fetchMock.mock.calls[2][1].body)).not.toContain('k_ab12cd');

    await expect(adapter.removeProviderKey('deepseek', 'k_ab12cd')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[3][0]).toBe('http://localhost:8765/api/providers/deepseek/keys/k_ab12cd');
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'DELETE' });

    const stages = { enabled: true, planning: 'low', execution: 'medium', verification: 'high' } as const;
    await expect(adapter.saveReasoningStages({ ...stages })).resolves.toEqual({ ...stages });
    expect(fetchMock.mock.calls[4][0]).toBe('http://localhost:8765/api/models/reasoning-stages');
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ ...stages }) });
  });

  it('edits, deletes and tests custom models through the backend API', async () => {
    const updated = { id: 'deepseek/deepseek-chat', name: '深度求索', litellm_model: 'deepseek/deepseek-chat' };
    const empty = { ok: true, status: 204, json: async () => { throw new SyntaxError('empty response'); } } as Response;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => updated } as Response)
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true, latency_ms: 420 }) } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    const patch = { name: '深度求索', litellm_model: 'deepseek/deepseek-chat', native_model: 'deepseek-v4.1-flash', capabilities: { supports_tools: true } };
    await expect(adapter.updateCustomModel('deepseek/deepseek-chat', patch)).resolves.toEqual(updated);
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/models/custom/deepseek%2Fdeepseek-chat');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'PUT', body: JSON.stringify(patch) });

    await expect(adapter.deleteCustomModel('deepseek/deepseek-chat')).resolves.toBeUndefined();
    expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8765/api/models/custom/deepseek%2Fdeepseek-chat');
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ method: 'DELETE' });

    await expect(adapter.testModelById('deepseek/deepseek-chat')).resolves.toEqual({ ok: true, latency_ms: 420 });
    expect(fetchMock.mock.calls[3][0]).toBe('http://localhost:8765/api/models/test');
    expect(fetchMock.mock.calls[3][1]).toMatchObject({ method: 'POST', body: JSON.stringify({ model_id: 'deepseek/deepseek-chat' }) });
  });

  it('serves provider reads from mock data and refuses mock writes when the backend is away', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValueOnce(new Error('offline')));
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.getProviders()).resolves.toEqual([]);
    await expect(adapter.getReasoningStages()).resolves.toEqual({ enabled: false, planning: 'high', execution: 'medium', verification: 'high' });
    await expect(adapter.updateProviderConfig('deepseek', null)).rejects.toThrow('连接 Atlas 后端后才能保存服务商设置');
    await expect(adapter.deleteCustomModel('deepseek/deepseek-chat')).rejects.toThrow('连接 Atlas 后端后才能删除自定义模型');
  });
});

describe('BackendAdapter C6 init, diagnostics and lsp status', () => {
  const proposal = {
    path: 'C:/ws/AGENTS.md', exists: true, existing_content: '# 旧内容', proposed_content: '# 新内容',
    scan: { languages: [{ name: 'Python', count: 3 }], package_managers: ['pip'], build_commands: [], test_commands: [], lint_commands: [], typecheck_commands: [], entrypoints: [], existing: { 'AGENTS.md': true } },
    diff: '--- \n+++ AGENTS.md',
  };

  it('previews and applies the AGENTS.md proposal with the conflict seam intact', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => proposal } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ written: true }) } as Response)
      .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail: '磁盘上的 AGENTS.md 已被改过' }) } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.initPreview('C:/ws')).resolves.toEqual(proposal);
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/init/preview');
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST', body: JSON.stringify({ workspace: 'C:/ws' }) });

    await expect(adapter.initApply('C:/ws', '# 新内容', '# 旧内容')).resolves.toEqual({ written: true });
    expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8765/api/init/apply');
    // 存在时必须原样回传 existing_content；不存在时应为 null
    expect(fetchMock.mock.calls[2][1]).toMatchObject({ body: JSON.stringify({ workspace: 'C:/ws', content: '# 新内容', expected_existing: '# 旧内容' }) });

    await expect(adapter.initApply('C:/ws', '# 新内容', '# 旧内容')).rejects.toThrow('磁盘上的 AGENTS.md 已被改过');
  });

  it('reads per-run diagnostics and lsp server status', async () => {
    const diagnostics = { files: [{ path: 'src/a.py', count: 1, diagnostics: [{ line: 3, column: 7, severity: 'error', code: 'E501', message: 'too long' }] }] };
    const status = { servers: [{ id: 'pylsp', languages: ['python'], available: false, hint: 'pip install python-lsp-server' }] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => diagnostics } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => status } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.getRunDiagnostics('run-9')).resolves.toEqual(diagnostics);
    expect(fetchMock.mock.calls[1][0]).toBe('http://localhost:8765/api/runs/run-9/diagnostics');

    await expect(adapter.getLspStatus('C:/ws')).resolves.toEqual(status);
    expect(fetchMock.mock.calls[2][0]).toBe('http://localhost:8765/api/lsp/status?workspace=C%3A%2Fws');
  });
});
