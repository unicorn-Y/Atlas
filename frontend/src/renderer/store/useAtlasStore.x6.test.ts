import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ConversationMessage } from '@atlas/backend-adapter';
import type { AgentRun } from '../../types/runtime';
import { backend, useAtlasStore } from './useAtlasStore';

const message = (id: string, role: ConversationMessage['role'] = 'user'): ConversationMessage => ({ id, conversation_id: 'source', role, content: id, created_at: '' });

beforeEach(() => {
  vi.stubGlobal('window', new EventTarget());
  vi.spyOn(backend, 'liveBackendRuns').mockResolvedValue([]);
  vi.spyOn(backend, 'summarizeConversationBranch').mockResolvedValue({} as never);
  useAtlasStore.setState({ activeConversationId: 'source', activeRunId: null, conversations: [{ id: 'source', title: 'Source', workspace: 'D:/project' }],
    conversationMessages: {}, messagesHasEarlier: {}, loadingEarlierConversationId: null, runs: [], queue: {}, pendingSteers: {}, queuePaused: {}, error: null });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('observed history pagination', () => {
  it('does not offer another page when exactly one full page exists', async () => {
    const rows = Array.from({ length: 100 }, (_, index) => message(`m-${index}`));
    const getMessages = vi.spyOn(backend, 'getMessages').mockResolvedValue(rows);
    await useAtlasStore.getState().openConversation({ id: 'source', title: 'Source' });
    expect(getMessages).toHaveBeenCalledWith('source', { limit: 101 });
    expect(useAtlasStore.getState().conversationMessages.source).toEqual(rows);
    expect(useAtlasStore.getState().messagesHasEarlier.source).toBe(false);
  });

  it('keeps the lookahead row for the next cursor page without losing or duplicating messages', async () => {
    const latest = Array.from({ length: 101 }, (_, index) => message(`m-${index}`));
    const getMessages = vi.spyOn(backend, 'getMessages').mockResolvedValueOnce(latest).mockResolvedValueOnce([message('m-0')]);
    await useAtlasStore.getState().openConversation({ id: 'source', title: 'Source' });
    expect(useAtlasStore.getState().conversationMessages.source).toEqual(latest.slice(1));
    expect(useAtlasStore.getState().messagesHasEarlier.source).toBe(true);
    await useAtlasStore.getState().loadEarlier('source');
    expect(getMessages).toHaveBeenLastCalledWith('source', { limit: 101, beforeId: 'm-1' });
    expect(useAtlasStore.getState().conversationMessages.source).toEqual(latest);
    expect(useAtlasStore.getState().messagesHasEarlier.source).toBe(false);
  });
});

describe('stronger session operations regressions', () => {
  it.each([false, true])('forks an arbitrary assistant tail with summarize=%s', async (summarize) => {
    const fork = vi.spyOn(backend, 'forkConversation').mockResolvedValue({ id: 'fork', title: 'Fork' });
    vi.spyOn(backend, 'getMessages').mockResolvedValue([message('assistant-tail', 'assistant')]);
    await useAtlasStore.getState().forkFrom('assistant-tail', summarize);
    expect(fork).toHaveBeenCalledWith('source', 'assistant-tail', summarize);
    expect(useAtlasStore.getState().activeConversationId).toBe('fork');
    expect(useAtlasStore.getState().conversations.find((row) => row.id === 'fork')?.workspace).toBe('D:/project');
  });

  it.each([false, true])('rewinds conversation with files=%s and then redoes the exact rewind', async (files) => {
    const result = { rewind_id: 'rewind-1', removed_messages: 2, restored_files: files ? ['src/a.ts'] : [], skipped: [] } as Awaited<ReturnType<typeof backend.rewindConversation>>;
    const rewind = vi.spyOn(backend, 'rewindConversation').mockResolvedValue(result);
    const redo = vi.spyOn(backend, 'redoRewind').mockResolvedValue({} as never);
    vi.spyOn(backend, 'getMessages').mockResolvedValue([]);
    expect(await useAtlasStore.getState().rewindTo('user-tail', files)).toBe(result);
    expect(rewind).toHaveBeenCalledWith('source', 'user-tail', files);
    expect(await useAtlasStore.getState().redoRewind('source', 'rewind-1')).toBe(true);
    expect(redo).toHaveBeenCalledWith('source', 'rewind-1');
  });

  it('redirects a running conversation immediately and retains the unconfirmed message', async () => {
    const steer = vi.spyOn(backend, 'steerRun').mockImplementation(() => undefined);
    const run = { id: 'run', conversationId: 'source', status: 'running', events: [] } as unknown as AgentRun;
    useAtlasStore.setState({ runs: [run], followUpMode: 'redirect' });
    await useAtlasStore.getState().sendMessage('Change direction');
    expect(steer).toHaveBeenCalledWith('run', 'Change direction', expect.any(String), true);
    expect(useAtlasStore.getState().pendingSteers.run[0].content).toBe('Change direction');
    expect(useAtlasStore.getState().queue.source).toBeUndefined();
  });

  it('sends plan mode to the next run and submits the reviewed edits to that plan', async () => {
    const start = vi.spyOn(backend, 'startRun').mockResolvedValue(undefined);
    const approve = vi.spyOn(backend, 'approvePlan').mockImplementation(() => undefined);
    useAtlasStore.getState().setNextRunMode('plan');
    await useAtlasStore.getState().sendMessage('Plan this change');
    expect(start.mock.calls[0][0]).toMatchObject({ content: 'Plan this change', mode: 'plan' });
    useAtlasStore.getState().approvePlan('run-plan', 'plan-event', '  Keep the tests first.  ');
    expect(approve).toHaveBeenCalledWith('run-plan', 'plan-event', 'Keep the tests first.');
    expect(useAtlasStore.getState().answers['plan-event']).toBe('Keep the tests first.');
  });

  it('edits and resends a user message after truncating its old answer', async () => {
    const truncate = vi.spyOn(backend, 'truncateConversation').mockResolvedValue({} as never);
    const start = vi.spyOn(backend, 'startRun').mockResolvedValue(undefined);
    useAtlasStore.setState({ conversationMessages: { source: [message('user-1'), message('assistant-1', 'assistant'), message('user-2'), message('assistant-2', 'assistant')] } });
    await useAtlasStore.getState().editMessage('user-2', 'Revised question');
    expect(truncate).toHaveBeenCalledWith('source', 'user-2');
    expect(start.mock.calls[0][0]).toMatchObject({ content: 'Revised question', conversation_id: 'source' });
    expect(useAtlasStore.getState().conversationMessages.source.map((row) => row.id)).toEqual(['user-1', 'assistant-1']);
  });
});
