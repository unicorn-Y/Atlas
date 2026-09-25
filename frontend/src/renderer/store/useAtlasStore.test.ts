import { afterEach, describe, expect, it, vi } from 'vitest';
import { useAtlasStore } from './useAtlasStore';

afterEach(() => vi.unstubAllGlobals());

describe('conversation creation', () => {
  it('creates a conversation in backend state and selects it', async () => {
    const created = { id: 'conversation-new', title: 'New conversation', created_at: '2026-09-26', updated_at: '2026-09-26' };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ models: [], current: '' }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => [] } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => ({ servers: [], tool_count: 0, tools: [] }) } as Response)
      .mockResolvedValueOnce({ ok: true, json: async () => created } as Response);
    vi.stubGlobal('fetch', fetchMock);

    await useAtlasStore.getState().initialize();
    await useAtlasStore.getState().createConversation();

    const state = useAtlasStore.getState();
    expect(state.activeConversationId).toBe(created.id);
    expect(state.conversations[0]).toMatchObject({ id: created.id, title: created.title });
    expect(fetchMock.mock.calls[4][1]).toMatchObject({ method: 'POST' });
  });
});
