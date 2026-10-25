import { describe, expect, it } from 'vitest';
import { applyRuntimeEvent, MAX_RUN_EVENTS, normalizeRuntimeEvent } from './runtimeEvents';
import { useAtlasStore } from '../store/useAtlasStore';
import type { AgentEvent, AgentRun } from '../../types/runtime';

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

describe('new wire events are known', () => {
  it('recognizes lsp.diagnostics and review.findings without crashing', () => {
    expect(normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:10', run_id: 'run-1', sequence: 10,
      timestamp: '2026-10-02T00:00:00Z', event: 'lsp.diagnostics',
      data: { path: 'src/app.py', count: 2, diagnostics: [] },
    })?.type).toBe('lsp.diagnostics');
    expect(normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:11', run_id: 'run-1', sequence: 11,
      timestamp: '2026-10-02T00:00:00Z', event: 'review.findings',
      data: { scope: 'working_tree', findings: [] },
    })?.type).toBe('review.findings');
  });

  it('keeps live structured component pushes in the run event stream', () => {
    const event = normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:12', run_id: 'run-1', sequence: 12,
      timestamp: '2026-10-02T00:00:00Z', event: 'component.push',
      data: { component_id: 'color', title: '选个颜色', kind: 'buttons', data: { buttons: [{ label: '红', value: 'red' }, { label: '蓝', value: 'blue' }] } },
    });
    expect(event?.type).toBe('component.push');
    if (!event) throw new Error('component.push should be recognized');
    const run = applyRuntimeEvent({
      id: 'run-1', conversationId: 'c1', title: 'T', status: 'running', phase: 'execution',
      startedAt: '', updatedAt: '', lastEventSequence: 11, events: [],
    }, event);
    expect(run.events).toEqual([event]);
  });
});

describe('bounded run events', () => {
  const baseRun = (events: AgentEvent[] = []): AgentRun => ({
    id: 'run-1', conversationId: 'c1', title: 'T', status: 'running', phase: 'execution',
    startedAt: '', updatedAt: '',
    lastEventSequence: events.reduce((max, event) => Math.max(max, event.sequence), 0), events,
  });
  const at = (sequence: number, type: AgentEvent['type'] = 'message.delta'): AgentEvent =>
    ({ id: `e${sequence}`, runId: 'run-1', sequence, type, timestamp: '2026-10-02T00:00:00Z', data: { content: 'x' } });

  it('keeps events in arrival order without a per-event full sort', () => {
    let run = baseRun();
    for (let sequence = 1; sequence <= 200; sequence++) run = applyRuntimeEvent(run, at(sequence));
    expect(run.events.map((event) => event.sequence)).toEqual(Array.from({ length: 200 }, (_, index) => index + 1));
    expect(run.eventsTruncated).toBeFalsy();
  });

  it('drops the oldest events past the cap and marks the run for the UI', () => {
    let run = baseRun();
    const total = MAX_RUN_EVENTS + 120;
    for (let sequence = 1; sequence <= total; sequence++) run = applyRuntimeEvent(run, at(sequence));
    expect(run.events).toHaveLength(MAX_RUN_EVENTS);
    expect(run.events[0].sequence).toBe(total - MAX_RUN_EVENTS + 1);
    expect(run.eventsTruncated).toBe(true);
    expect(run.droppedEventCount).toBe(120);
    expect(run.lastEventSequence).toBe(total);
  });

  it('rejects replayed duplicates and restores order on the out-of-order path', () => {
    const run = baseRun([at(1), at(3)]);
    expect(applyRuntimeEvent(run, at(1)).events).toHaveLength(2);
    expect(applyRuntimeEvent(run, at(3)).events).toHaveLength(2);
    const repaired = applyRuntimeEvent(run, at(2));
    expect(repaired.events.map((event) => event.sequence)).toEqual([1, 2, 3]);
    expect(repaired.lastEventSequence).toBe(3);
  });
});
