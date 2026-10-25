import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { backend, useAtlasStore } from './useAtlasStore';
import SettingsPage from '../pages/SettingsPage';

const REASONING_STAGES = { enabled: false, planning: 'high', execution: 'medium', verification: 'high' } as const;

beforeEach(() => vi.stubGlobal('window', new EventTarget()));
afterEach(() => vi.unstubAllGlobals());

describe('conversation creation', () => {
  it('persists Skill activation by name for later run requests', () => {
    const values = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    });
    localStorage.removeItem('atlas.active-skills');
    useAtlasStore.setState({ activeSkills: [] });
    useAtlasStore.getState().applySkill('coding-discipline');
    useAtlasStore.getState().applySkill('coding-discipline');

    expect(useAtlasStore.getState().activeSkills).toEqual(['coding-discipline']);
    expect(localStorage.getItem('atlas.active-skills')).toBe('["coding-discipline"]');

    useAtlasStore.getState().removeSkill('coding-discipline');
    expect(useAtlasStore.getState().activeSkills).toEqual([]);
  });

  it('does not inject demo conversations when the backend history is empty', async () => {
    useAtlasStore.setState({ conversations: [], activeConversationId: '', conversationMessages: {} });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ profiles: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ recipes: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => REASONING_STAGES } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();

    expect(useAtlasStore.getState().conversations).toEqual([]);
    expect(useAtlasStore.getState().activeConversationId).toBe('');
  });

  it('creates a conversation in backend state and selects it', async () => {
    const created = { id: 'conversation-new', title: 'New conversation', created_at: '2026-09-26', updated_at: '2026-09-26' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ profiles: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ recipes: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => REASONING_STAGES } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => created } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();
    await useAtlasStore.getState().createConversation();

    const state = useAtlasStore.getState();
    expect(state.activeConversationId).toBe(created.id);
    expect(state.conversations[0]).toMatchObject({ id: created.id, title: created.title });
    expect(fetchMock.mock.calls[9][1]).toMatchObject({ method: 'POST' });
  });

  it('loads history and selects each opened conversation', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ profiles: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ recipes: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => REASONING_STAGES } as Response);
    vi.stubGlobal('fetch', fetchMock);
    await useAtlasStore.getState().initialize();

    let resolveMessages!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(new Promise<Response>((resolve) => { resolveMessages = resolve; }));
    const opening = useAtlasStore.getState().openConversation({ id: 'conversation-open', title: 'Existing chat' });

    expect(useAtlasStore.getState().loadingMessagesConversationId).toBe('conversation-open');
    resolveMessages({ ok: true, json: async () => [{ id: 'message-open', role: 'assistant', content: 'Loaded history', created_at: '2026-09-26' }] } as Response);
    await opening;
    expect(useAtlasStore.getState().loadingMessagesConversationId).toBeNull();
    expect(useAtlasStore.getState().activeConversationId).toBe('conversation-open');
    expect(useAtlasStore.getState().conversationMessages['conversation-open'][0].content).toBe('Loaded history');

    fetchMock.mockResolvedValueOnce({ ok: true, json: async () => [{ id: 'message-next', role: 'user', content: 'Switched history', created_at: '2026-09-26' }] } as Response);
    await useAtlasStore.getState().openConversation({ id: 'conversation-next', title: 'Another chat' });
    expect(useAtlasStore.getState().activeConversationId).toBe('conversation-next');
    expect(useAtlasStore.getState().conversationMessages['conversation-next'][0].content).toBe('Switched history');
  });
});

describe('settings configuration', () => {
  it('saves provider settings through the backend and updates the rendered state', async () => {
    const configuration = { gateway_base_url: 'https://api.example.test/v1', api_key_configured: true, models: [{ id: 'gpt-4o', name: 'GPT-4o', provider: 'openai' }], current: 'gpt-4o', compression_model: '' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...configuration, api_key_configured: false, gateway_base_url: 'https://old.example.test', models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ profiles: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ recipes: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => REASONING_STAGES } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => configuration } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();
    const saved = await useAtlasStore.getState().saveProviderSettings(configuration.gateway_base_url, 'secret');

    expect(saved).toBe(true);
    expect(useAtlasStore.getState()).toMatchObject({ providerBaseUrl: configuration.gateway_base_url, apiKeyConfigured: true, model: 'gpt-4o' });
    expect(fetchMock.mock.calls[9][1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ gateway_base_url: configuration.gateway_base_url, api_key: 'secret', compression_model: '' }) });
  });

  it('loads and saves subagent enablement and default model together', async () => {
    const configuration = { gateway_base_url: 'https://api.example.test/v1', api_key_configured: true, models: [{ id: 'gpt-4o' }, { id: 'gpt-4o-mini' }], current: 'gpt-4o', compression_model: '', subagents_enabled: true, subagent_default_model: 'gpt-4o' };
    const savedConfiguration = { ...configuration, subagents_enabled: false, subagent_default_model: 'gpt-4o-mini' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => configuration } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ profiles: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ recipes: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => REASONING_STAGES } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => savedConfiguration } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();
    expect(useAtlasStore.getState()).toMatchObject({ subagentsEnabled: true, subagentDefaultModel: 'gpt-4o' });
    const saved = await useAtlasStore.getState().saveSubagentSettings(false, 'gpt-4o-mini');

    expect(saved).toBe(true);
    expect(useAtlasStore.getState()).toMatchObject({ subagentsEnabled: false, subagentDefaultModel: 'gpt-4o-mini' });
    expect(fetchMock.mock.calls[9][1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ subagents_enabled: false, subagent_default_model: 'gpt-4o-mini' }) });

    const renderSettings = (subagentsEnabled: boolean) => renderToStaticMarkup(React.createElement(SettingsPage, {
      username: 'User', onSaveUsername: () => undefined, apiBaseUrl: 'http://127.0.0.1:8765', providerBaseUrl: configuration.gateway_base_url,
      connected: true, apiKeyConfigured: true, busy: false, connectionTest: null, error: null, models: configuration.models,
      selectedModel: configuration.current, providers: [], reasoningStages: REASONING_STAGES, subagentsEnabled, subagentDefaultModel: 'gpt-4o-mini', subagentMaxConcurrent: 8, onBack: () => undefined,
      onSelectModel: () => undefined, onSaveSubagentSettings: async () => true, onSaveProvider: async () => true, onAddModel: async () => true,
      onTestConnection: () => undefined, onLoadProviders: () => undefined, onSaveProviderConfig: async () => true, onAddProviderKey: async () => true,
      onRemoveProviderKey: () => undefined, onUpdateModel: async () => true, onDeleteModel: async () => true, onSaveReasoningStages: () => undefined,
      statusBar: { model: false, reasoning: false, context: false, tokens: false, cost: false, git: false, permission: false, processes: false },
      onStatusBarChange: () => undefined,
    }));
    const enabledMarkup = renderSettings(true);
    expect(enabledMarkup).toMatch(/<input type="checkbox" checked=""\/>启用子 Agent/);
    expect(enabledMarkup).toContain('aria-label="默认子 Agent 模型"');
    expect(enabledMarkup).toMatch(/<option[^>]*value="gpt-4o-mini"[^>]*>gpt-4o-mini<\/option>/);
    expect(enabledMarkup).not.toContain('aria-label="默认子 Agent 模型" disabled=""');
    expect(renderSettings(false)).toContain('aria-label="默认子 Agent 模型" disabled=""');
  });
});

describe('follow-up queue', () => {
  const running = (id: string, conversationId: string) => ({ id, conversationId, title: 'Busy', status: 'running' as const, phase: 'execution' as const, startedAt: '', updatedAt: '', lastEventSequence: 1, events: [] });

  it('shows a stop delivery error and leaves the run active until confirmed', () => {
    const cancel = vi.spyOn(backend, 'cancelRun').mockImplementation(() => { throw new Error('stop not delivered'); });
    try {
      useAtlasStore.setState({ runs: [running('r-stop-error', 'c-stop-error')], error: null, queue: {}, pendingSteers: {} });
      useAtlasStore.getState().stopRun('r-stop-error');
      expect(useAtlasStore.getState().error).toBe('停止请求失败');
      expect(useAtlasStore.getState().errorDetail).toContain('stop not delivered');
      expect(useAtlasStore.getState().getRun('r-stop-error')?.status).toBe('running');
    } finally { cancel.mockRestore(); }
  });

  it('queues messages sent while the conversation is running instead of starting a parallel run', async () => {
    useAtlasStore.setState({ activeConversationId: 'c-queue', conversations: [], runs: [running('r-busy', 'c-queue')], queue: {}, queuePaused: {} });

    await useAtlasStore.getState().sendMessage('and also check the tests');

    const state = useAtlasStore.getState();
    expect(state.runs).toHaveLength(1);
    expect(state.queue['c-queue'].map((item) => item.content)).toEqual(['and also check the tests']);

    const [item] = state.queue['c-queue'];
    expect(useAtlasStore.getState().takeQueued('c-queue', item.id)?.content).toBe('and also check the tests');
    expect(useAtlasStore.getState().queue['c-queue']).toEqual([]);
  });

  it('pauses the queue when the user stops the run, and resumes on request', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 } as Response));
    await useAtlasStore.getState().initialize();
    useAtlasStore.setState({ activeConversationId: 'c-stop', activeRunId: 'r-stop', conversations: [], runs: [running('r-stop', 'c-stop')], queue: {}, queuePaused: {}, runPrompts: {} });
    await useAtlasStore.getState().sendMessage('next step');

    useAtlasStore.getState().stopTask();
    expect(useAtlasStore.getState().queuePaused['c-stop']).toBe(true);

    useAtlasStore.getState().appendEvent({ id: 'e-cancel', runId: 'r-stop', sequence: 2, type: 'run.cancelled', timestamp: new Date().toISOString(), data: {} });
    expect(useAtlasStore.getState().runs).toHaveLength(1);
    expect(useAtlasStore.getState().queue['c-stop']).toHaveLength(1);

    useAtlasStore.getState().resumeQueue('c-stop');
    const state = useAtlasStore.getState();
    expect(state.queue['c-stop']).toEqual([]);
    expect(state.runs).toHaveLength(2);
    expect(state.runPrompts[state.runs[1].id].content).toBe('next step');
  });

  it('sends the next queued message as soon as the running one finishes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 } as Response));
    await useAtlasStore.getState().initialize();
    useAtlasStore.setState({ activeConversationId: 'c-done', activeRunId: 'r-done', conversations: [], runs: [running('r-done', 'c-done')], queue: {}, queuePaused: {}, unread: [] });
    await useAtlasStore.getState().sendMessage('first follow-up');
    await useAtlasStore.getState().sendMessage('second follow-up');

    useAtlasStore.getState().appendEvent({ id: 'e-done', runId: 'r-done', sequence: 2, type: 'run.completed', timestamp: new Date().toISOString(), data: {} });

    const state = useAtlasStore.getState();
    expect(state.queue['c-done'].map((item) => item.content)).toEqual(['second follow-up']);
    expect(state.runs.filter((run) => run.conversationId === 'c-done')).toHaveLength(2);
  });
});

describe('steering a running run', () => {
  const running = (id: string, conversationId: string) => ({ id, conversationId, title: 'Busy', status: 'running' as const, phase: 'execution' as const, startedAt: '', updatedAt: '', lastEventSequence: 1, events: [] });

  it('sends follow-ups into the run and forgets them once the backend confirms', async () => {
    const sent: string[] = [];
    vi.spyOn(backend, 'steerRun').mockImplementation((_run, content) => { sent.push(content); });
    useAtlasStore.setState({ activeConversationId: 'c-steer', conversations: [], runs: [running('r-steer', 'c-steer')], queue: {}, pendingSteers: {}, followUpMode: 'steer' });

    await useAtlasStore.getState().sendMessage('focus on the failing test');

    expect(sent).toEqual(['focus on the failing test']);
    expect(useAtlasStore.getState().queue['c-steer'] ?? []).toEqual([]);
    const [pending] = useAtlasStore.getState().pendingSteers['r-steer'];
    useAtlasStore.getState().appendEvent({ id: 'e-steered', runId: 'r-steer', sequence: 2, type: 'run.steered', timestamp: new Date().toISOString(), data: { event_id: pending.id, content: pending.content } });
    expect(useAtlasStore.getState().pendingSteers['r-steer']).toEqual([]);
    vi.restoreAllMocks();
  });

  it('runs an unconfirmed steer next when the run ends before picking it up', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 } as Response));
    await useAtlasStore.getState().initialize();
    vi.spyOn(backend, 'steerRun').mockImplementation(() => undefined);
    useAtlasStore.setState({ activeConversationId: 'c-late', activeRunId: 'r-late', conversations: [], runs: [running('r-late', 'c-late')], queue: {}, queuePaused: {}, pendingSteers: {}, followUpMode: 'steer', runPrompts: {} });
    await useAtlasStore.getState().sendMessage('one more thing');

    useAtlasStore.getState().appendEvent({ id: 'e-late', runId: 'r-late', sequence: 2, type: 'run.completed', timestamp: new Date().toISOString(), data: {} });

    const state = useAtlasStore.getState();
    const next = state.runs.filter((run) => run.conversationId === 'c-late');
    expect(next).toHaveLength(2);
    expect(state.runPrompts[next[1].id].content).toBe('one more thing');
    vi.restoreAllMocks();
  });

  it('queues instead of steering when the user prefers it or attaches files', async () => {
    const steerRun = vi.spyOn(backend, 'steerRun').mockImplementation(() => undefined);
    useAtlasStore.setState({ activeConversationId: 'c-pref', conversations: [], runs: [running('r-pref', 'c-pref')], queue: {}, pendingSteers: {}, followUpMode: 'queue' });
    await useAtlasStore.getState().sendMessage('later please');
    useAtlasStore.setState({ followUpMode: 'steer' });
    await useAtlasStore.getState().sendMessage('see file', [], [{ name: 'a.txt', mime: 'text/plain', data_base64: 'YQ==' }]);

    expect(steerRun).not.toHaveBeenCalled();
    expect(useAtlasStore.getState().queue['c-pref'].map((item) => item.content)).toEqual(['later please', 'see file']);
    vi.restoreAllMocks();
  });
});

describe('custom command run overrides', () => {
  const conversation = { id: 'c-cmd', title: 'Existing chat', created_at: '2026-09-26', updated_at: '2026-09-26' };

  it('applies rendered command metadata to the next run only', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 } as Response));
    useAtlasStore.setState({
      activeConversationId: 'c-cmd', conversations: [conversation], model: 'm1',
      runs: [], queue: {}, queuePaused: {}, pendingSteers: {}, runPrompts: {}, worktreeRequests: {}, unread: [], followUpMode: 'steer',
      pendingRunOverrides: { model: 'm2', tool_allow: ['read_office'], tool_deny: ['execute_command'] },
    });
    const startRun = vi.spyOn(backend, 'startRun').mockImplementation(() => Promise.resolve());

    await useAtlasStore.getState().sendMessage('hi');

    const first = startRun.mock.calls[0][0];
    expect(first).toMatchObject({ model: 'm2', tool_allow: ['read_office'], tool_deny: ['execute_command'] });
    expect(useAtlasStore.getState().pendingRunOverrides).toBeNull();

    useAtlasStore.getState().appendEvent({ id: 'e-done', runId: first.run_id, sequence: 1, type: 'run.completed', timestamp: new Date().toISOString(), data: {} });

    await useAtlasStore.getState().sendMessage('again');

    const second = startRun.mock.calls[1][0];
    expect(second.model).toBe('m1');
    expect('tool_allow' in second).toBe(false);
    expect('tool_deny' in second).toBe(false);
    vi.restoreAllMocks();
  });
});

describe('message pagination and bounded cache', () => {
  const message = (id: string) => ({ id, conversation_id: 'c', role: 'user' as const, content: id, created_at: '' });

  it('defaults to the latest page and prepends an earlier one on loadEarlier', async () => {
    useAtlasStore.setState({ configLoaded: false, activeConversationId: '', activeRunId: null });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [{ id: 'conversation-open', title: 'Open chat', updated_at: '' }] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [{ id: 'm-100', role: 'user', content: 'latest', created_at: '' }] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ profiles: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ recipes: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => REASONING_STAGES } as Response);
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes('/messages?limit=100&before_id=m-100')) {
        return Promise.resolve({ ok: true, json: async () => [message('m-20'), message('m-21')] } as Response);
      }
      return Promise.resolve({ ok: true, json: async () => [] } as Response);
    });
    vi.stubGlobal('fetch', fetchMock);
    await useAtlasStore.getState().initialize();

    const messagesUrl = String(fetchMock.mock.calls.find(([target]) => String(target).includes('/messages'))?.[0]);
    expect(messagesUrl).toContain('/api/conversations/conversation-open/messages?limit=100');
    expect(useAtlasStore.getState().conversationMessages['conversation-open'][0].content).toBe('latest');

    useAtlasStore.setState({
      activeConversationId: 'c-early', conversations: [{ id: 'c-early', title: 'Early' }],
      conversationMessages: { 'c-early': [message('m-100')] }, messagesHasEarlier: { 'c-early': true },
    });
    await useAtlasStore.getState().loadEarlier('c-early');

    const state = useAtlasStore.getState();
    const earlierUrl = String(fetchMock.mock.calls.find(([target]) => String(target).includes('before_id'))?.[0]);
    expect(earlierUrl).toContain('/api/conversations/c-early/messages?limit=100&before_id=m-100');
    expect(state.conversationMessages['c-early'].map((item) => item.id)).toEqual(['m-20', 'm-21', 'm-100']);
    // 一页没满 100 条 → 前面没有更早的了
    expect(state.messagesHasEarlier['c-early']).toBe(false);
    expect(state.loadingEarlierConversationId).toBeNull();
  });

  it('evicts the least recently viewed conversation history past 10 entries, never the active one', async () => {
    const fetchMock = vi.fn((url: string) => {
      const match = /\/api\/conversations\/([^/]+)\/messages/.exec(String(url));
      if (match) return Promise.resolve({ ok: true, json: async () => [message(`m-${match[1]}`)] } as Response);
      return Promise.resolve({ ok: false, status: 503 } as Response);
    });
    vi.stubGlobal('fetch', fetchMock);
    useAtlasStore.setState({ conversations: [], conversationMessages: {}, messagesHasEarlier: {}, activeConversationId: '', runs: [] });

    for (let index = 0; index < 12; index++) {
      await useAtlasStore.getState().openConversation({ id: `c-lru-${index}`, title: `Chat ${index}` });
    }

    const state = useAtlasStore.getState();
    expect(state.activeConversationId).toBe('c-lru-11');
    expect(state.conversationMessages['c-lru-11']).toHaveLength(1);
    expect(state.conversationMessages['c-lru-0']).toBeUndefined();
    expect(state.conversationMessages['c-lru-1']).toBeUndefined();
    expect(Object.keys(state.conversationMessages)).toHaveLength(10);
  });
});

describe('backend connection recovery', () => {
  const histories = [{ id: 'first', title: 'First' }, { id: 'selected', title: 'Selected' }];
  const response = (target: RequestInfo | URL) => ({
    ok: true,
    json: async () => {
      const url = String(target);
      if (url.endsWith('/api/settings/configuration')) return { models: [], current: 'm', gateway_base_url: '', api_key_configured: true };
      if (url.endsWith('/api/conversations')) return histories;
      if (url.endsWith('/api/tools')) return { tools: [] };
      if (url.endsWith('/api/skills')) return { skills: [] };
      if (url.endsWith('/api/agent/capabilities')) return { capabilities: [] };
      if (url.endsWith('/api/profiles')) return { profiles: [] };
      if (url.endsWith('/api/recipes')) return { recipes: [] };
      return {};
    },
  } as Response);

  it('coalesces connection recovery and preserves the selected conversation', async () => {
    const fetchMock = vi.fn(async (target: RequestInfo | URL) => response(target));
    vi.stubGlobal('fetch', fetchMock);
    useAtlasStore.setState({ configLoaded: true, connected: false, activeConversationId: 'selected', conversations: histories });
    const first = useAtlasStore.getState().initialize();
    const second = useAtlasStore.getState().initialize();
    expect(first).toBe(second);
    await Promise.all([first, second]);
    expect(useAtlasStore.getState().activeConversationId).toBe('selected');
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/health'))).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/messages'))).toBe(false);
  });

  it('keeps real history and a new conversation draft when the probe fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 } as Response)));
    useAtlasStore.setState({ configLoaded: true, connected: true, conversations: histories, activeConversationId: '', draftWorkspace: 'D:/workspace' });
    await useAtlasStore.getState().initialize();
    expect(useAtlasStore.getState().conversations).toEqual(histories);
    expect(useAtlasStore.getState().activeConversationId).toBe('');
    expect(useAtlasStore.getState().draftWorkspace).toBe('D:/workspace');
    expect(useAtlasStore.getState().connected).toBe(false);
  });

  it('retries a ready notification that arrives during a failed initial probe', async () => {
    let rejectProbe!: (error: Error) => void;
    const fetchMock = vi.fn(async (target: RequestInfo | URL) => response(target));
    fetchMock.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectProbe = reject; }));
    vi.stubGlobal('fetch', fetchMock);
    useAtlasStore.setState({ configLoaded: true, connected: false, backendStarting: true, activeConversationId: 'selected', conversations: histories });
    const initializing = useAtlasStore.getState().initialize();
    useAtlasStore.getState().applyStartupProgress({ phase: 'ready', managed: true, elapsedMs: 10 });
    rejectProbe(new Error('initial probe failed'));
    await initializing;
    await useAtlasStore.getState().initialize();
    expect(useAtlasStore.getState().connected).toBe(true);
    expect(useAtlasStore.getState().activeConversationId).toBe('selected');
  });
});

describe('/init flow', () => {
  const proposal = {
    path: 'C:/ws/AGENTS.md', exists: false, existing_content: '', proposed_content: '# Atlas',
    scan: { languages: [{ name: 'Python', count: 3 }], package_managers: ['pip'], build_commands: [], test_commands: ['pytest'], lint_commands: [], typecheck_commands: [], entrypoints: [], existing: { 'AGENTS.md': false } },
    diff: '--- \n+++ AGENTS.md',
  };
  const withWorkspace = { activeConversationId: 'c-init', conversations: [{ id: 'c-init', title: 'Chat', workspace: 'C:/ws' }] };
  const resetInit = { initOpen: false, initBusy: false, initApplying: false, initError: null as string | null, initProposal: null as typeof proposal | null };

  afterEach(() => { useAtlasStore.setState({ ...resetInit, error: null }); });

  it('refuses /init without a workspace, then previews with the conversation workspace', async () => {
    useAtlasStore.setState({ activeConversationId: 'c-init', conversations: [], ...resetInit });
    await useAtlasStore.getState().runInit();
    expect(useAtlasStore.getState().error).toBe('请先选择工作目录');
    expect(useAtlasStore.getState().initOpen).toBe(false);

    const fetchMock = vi.fn((url: string, _init?: RequestInit) => String(url).endsWith('/api/init/preview')
      ? Promise.resolve({ ok: true, json: async () => proposal } as Response)
      : Promise.resolve({ ok: false, status: 503 } as Response));
    vi.stubGlobal('fetch', fetchMock);
    useAtlasStore.setState(withWorkspace);
    await useAtlasStore.getState().runInit();

    expect(useAtlasStore.getState().initOpen).toBe(true);
    expect(useAtlasStore.getState().initBusy).toBe(false);
    expect(useAtlasStore.getState().initProposal?.path).toBe('C:/ws/AGENTS.md');
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/init/preview'));
    expect(String(call?.[0])).toBe('http://127.0.0.1:8765/api/init/preview');
    expect(call?.[1]).toMatchObject({ method: 'POST', body: JSON.stringify({ workspace: 'C:/ws' }) });
  });

  it('sends the conflict seam exactly: expected_existing is null for a new file, verbatim content for an existing one', async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) => Promise.resolve({ ok: true, json: async () => ({ written: true }) } as Response));
    vi.stubGlobal('fetch', fetchMock);
    useAtlasStore.setState({ ...withWorkspace, ...resetInit, initProposal: proposal, initOpen: true });
    await useAtlasStore.getState().applyInit();

    expect(String(fetchMock.mock.calls[0][0])).toBe('http://127.0.0.1:8765/api/init/apply');
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST', body: JSON.stringify({ workspace: 'C:/ws', content: '# Atlas', expected_existing: null }) });
    expect(useAtlasStore.getState().initOpen).toBe(false);
    expect(useAtlasStore.getState().initProposal).toBeNull();

    useAtlasStore.setState({ initProposal: { ...proposal, exists: true, existing_content: '# 人工写的内容' }, initOpen: true });
    await useAtlasStore.getState().applyInit();
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ body: JSON.stringify({ workspace: 'C:/ws', content: '# Atlas', expected_existing: '# 人工写的内容' }) });
  });

  it('keeps the dialog open and shows the backend detail when the write is rejected (422)', async () => {
    vi.stubGlobal('fetch', vi.fn((_url: string, _init?: RequestInit) => Promise.resolve({ ok: false, status: 422, json: async () => ({ detail: '磁盘上的 AGENTS.md 已被别人改过，请重新预览' }) } as Response)));
    useAtlasStore.setState({ ...withWorkspace, ...resetInit, initProposal: proposal, initOpen: true });
    const written = await useAtlasStore.getState().applyInit();

    expect(written).toBe(false);
    expect(useAtlasStore.getState().initApplying).toBe(false);
    expect(useAtlasStore.getState().initError).toBe('磁盘上的 AGENTS.md 已被别人改过，请重新预览');
    expect(useAtlasStore.getState().initOpen).toBe(true);
  });

  it('closeInit clears the whole dialog state', () => {
    useAtlasStore.setState({ ...withWorkspace, initOpen: true, initProposal: proposal, initError: 'x' });
    useAtlasStore.getState().closeInit();
    expect(useAtlasStore.getState()).toMatchObject({ initOpen: false, initProposal: null, initError: null });
  });
});

describe('requestFileOpen', () => {
  afterEach(() => { useAtlasStore.setState({ fileOpenRequest: null }); });

  it('records the file with an increasing nonce and defaults line to null', () => {
    useAtlasStore.setState({ fileOpenRequest: null });
    useAtlasStore.getState().requestFileOpen('src/app.py', 12);
    const first = useAtlasStore.getState().fileOpenRequest;
    expect(first).toEqual({ file: 'src/app.py', line: 12, column: null, nonce: expect.any(Number) });
    expect(first!.nonce).toBeGreaterThan(0);

    useAtlasStore.getState().requestFileOpen('src/b.py');
    const second = useAtlasStore.getState().fileOpenRequest;
    expect(second).toEqual({ file: 'src/b.py', line: null, column: null, nonce: expect.any(Number) });
    expect(second!.nonce).toBeGreaterThan(first!.nonce);

    useAtlasStore.getState().requestFileOpen('src/c.py', null);
    const third = useAtlasStore.getState().fileOpenRequest;
    expect(third).toEqual({ file: 'src/c.py', line: null, column: null, nonce: expect.any(Number) });
    expect(third!.nonce).toBeGreaterThan(second!.nonce);
  });
});
