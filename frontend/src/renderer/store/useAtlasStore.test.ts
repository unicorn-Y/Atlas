import { afterEach, describe, expect, it, vi } from 'vitest';
import { backend, useAtlasStore } from './useAtlasStore';

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
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response);
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
      .mockResolvedValueOnce({ ok: true, json: async () => created } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();
    await useAtlasStore.getState().createConversation();

    const state = useAtlasStore.getState();
    expect(state.activeConversationId).toBe(created.id);
    expect(state.conversations[0]).toMatchObject({ id: created.id, title: created.title });
    expect(fetchMock.mock.calls[6][1]).toMatchObject({ method: 'POST' });
  });

  it('loads history and selects each opened conversation', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response);
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
    const configuration = { gateway_base_url: 'https://api.example.test/v1', api_key_configured: true, models: [{ id: 'gpt-4o', name: 'GPT-4o', provider: 'openai' }], current: 'gpt-4o' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...configuration, api_key_configured: false, gateway_base_url: 'https://old.example.test', models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ skills: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ capabilities: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => configuration } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();
    const saved = await useAtlasStore.getState().saveProviderSettings(configuration.gateway_base_url, 'secret');

    expect(saved).toBe(true);
    expect(useAtlasStore.getState()).toMatchObject({ providerBaseUrl: configuration.gateway_base_url, apiKeyConfigured: true, model: 'gpt-4o' });
    expect(fetchMock.mock.calls[6][1]).toMatchObject({ method: 'PUT', body: JSON.stringify({ gateway_base_url: configuration.gateway_base_url, api_key: 'secret' }) });
  });
});

describe('follow-up queue', () => {
  const running = (id: string, conversationId: string) => ({ id, conversationId, title: 'Busy', status: 'running' as const, phase: 'execution' as const, startedAt: '', updatedAt: '', lastEventSequence: 1, events: [] });

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
