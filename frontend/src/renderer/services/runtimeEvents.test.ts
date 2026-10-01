import { describe, expect, it } from 'vitest';
import { normalizeRuntimeEvent } from './runtimeEvents';
import { useAtlasStore } from '../store/useAtlasStore';

describe('session title runtime events', () => {
  it('updates the conversation list only for an accepted automatic title', () => {
    useAtlasStore.setState({
      conversations: [{ id: 'conversation-1', title: 'New conversation' } as never],
      runs: [{
        id: 'run-1', conversationId: 'conversation-1', title: 'New conversation',
        status: 'running', phase: 'execution', startedAt: '', updatedAt: '',
        lastEventSequence: 0, events: [],
      }],
      activeRunId: 'run-1',
    });
    const event = normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:1', run_id: 'run-1', sequence: 1,
      timestamp: '2026-10-02T00:00:00Z', event: 'session.title',
      data: { title: 'Generated title', title_source: 'derived', accepted: true },
    });

    expect(event?.type).toBe('session.title');
    if (!event) throw new Error('session.title should be recognized');
    useAtlasStore.getState().appendEvent(event);

    expect(useAtlasStore.getState().conversations[0].title).toBe('Generated title');

    useAtlasStore.getState().appendEvent({
      ...event, id: 'run-1:2', sequence: 2,
      data: { title: 'Rejected title', title_source: 'llm', accepted: false },
    });
    expect(useAtlasStore.getState().conversations[0].title).toBe('Generated title');
  });
});
