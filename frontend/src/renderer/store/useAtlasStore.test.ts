import { afterEach, describe, expect, it, vi } from 'vitest';
import { useAtlasStore } from './useAtlasStore';

afterEach(() => vi.unstubAllGlobals());

describe('conversation creation', () => {
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
