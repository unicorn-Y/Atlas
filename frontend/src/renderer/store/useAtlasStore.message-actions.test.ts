import { afterEach, describe, expect, it, vi } from 'vitest';
import { backend, useAtlasStore } from './useAtlasStore';
import type { ConversationMessage, ConversationSummary, RewindResult } from '@atlas/backend-adapter';

describe('message-level conversation actions', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    useAtlasStore.setState({
      activeConversationId: '', activeRunId: null, conversations: [], conversationMessages: {}, runs: [],
    });
  });

  it('rewinds to a message with the selected file policy and reloads the transcript', async () => {
    const message = { id: 'kept-1', role: 'user', content: 'keep this' } as ConversationMessage;
    const rewind = { rewind_id: 'rewind-1' } as RewindResult;
    const rewindCall = vi.spyOn(backend, 'rewindConversation').mockResolvedValue(rewind);
    const messagesCall = vi.spyOn(backend, 'getMessages').mockResolvedValue([message]);
    useAtlasStore.setState({
      activeConversationId: 'conversation-1', activeRunId: 'run-1',
      conversationMessages: { 'conversation-1': [] },
    });

    await expect(useAtlasStore.getState().rewindTo('kept-1', true)).resolves.toBe(rewind);

    expect(rewindCall).toHaveBeenCalledWith('conversation-1', 'kept-1', true);
    expect(messagesCall).toHaveBeenCalledWith('conversation-1', { limit: expect.any(Number) });
    expect(useAtlasStore.getState().activeRunId).toBeNull();
    expect(useAtlasStore.getState().conversationMessages['conversation-1']).toEqual([message]);
  });

  it('redoes a rewind against its original conversation and reloads its transcript', async () => {
    const message = { id: 'restored-1', role: 'assistant', content: 'restored' } as ConversationMessage;
    const redoCall = vi.spyOn(backend, 'redoRewind').mockResolvedValue(undefined);
    vi.spyOn(backend, 'getMessages').mockResolvedValue([message]);
    useAtlasStore.setState({
      activeConversationId: 'another-conversation',
      conversationMessages: { 'rewound-conversation': [] },
    });

    await expect(useAtlasStore.getState().redoRewind('rewound-conversation', 'rewind-1')).resolves.toBe(true);

    expect(redoCall).toHaveBeenCalledWith('rewound-conversation', 'rewind-1');
    expect(useAtlasStore.getState().conversationMessages['rewound-conversation']).toEqual([message]);
  });

  it('passes the summarize choice through a message fork and preserves its workspace', async () => {
    const source = { id: 'source', title: 'Source', workspace: 'C:/workspace' } as ConversationSummary;
    const fork = { id: 'forked', title: 'Forked' } as ConversationSummary;
    const forkCall = vi.spyOn(backend, 'forkConversation').mockResolvedValue(fork);
    vi.spyOn(backend, 'getMessages').mockResolvedValue([]);
    vi.spyOn(backend, 'liveBackendRuns').mockResolvedValue([]);
    useAtlasStore.setState({ activeConversationId: source.id, conversations: [source] });

    await useAtlasStore.getState().forkFrom('message-7', true);

    expect(forkCall).toHaveBeenCalledWith('source', 'message-7', true);
    expect(useAtlasStore.getState().activeConversationId).toBe('forked');
    expect(useAtlasStore.getState().conversations[0]).toMatchObject({ id: 'forked', workspace: 'C:/workspace' });
  });
});
