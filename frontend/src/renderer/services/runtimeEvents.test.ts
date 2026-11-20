import { afterEach, describe, expect, it, vi } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { applyRuntimeEvent, normalizeRuntimeEvent, reduceAttemptText } from './runtimeEvents';
import { useAtlasStore } from '../store/useAtlasStore';
import ConversationActivity from '../components/ConversationActivity';

afterEach(() => vi.unstubAllGlobals());
import type { AgentEvent, AgentRun } from '../../types/runtime';

describe('attempt-scoped streamed text', () => {
  it('removes only failed output on rollback and preserves successful continuation text', () => {
    const failed = reduceAttemptText({ text: '', attemptChunks: {} }, 'message.delta', {
      content: 'OLD', attempt_id: 'attempt-old',
    });
    const unrelatedRollback = reduceAttemptText(failed, 'message.rollback', { attempt_id: 'other' });
    expect(unrelatedRollback).toEqual(failed);
    const withdrawn = reduceAttemptText(unrelatedRollback, 'message.rollback', { attempt_id: 'attempt-old' });
    expect(withdrawn).toEqual({ text: '', attemptChunks: {} });
    const successful = reduceAttemptText(withdrawn, 'message.delta', {
      content: 'NEW prefix', attempt_id: 'attempt-new',
    });
    const continued = reduceAttemptText(successful, 'message.delta', {
      content: ' continuation', attempt_id: 'attempt-continuation',
    });
    expect(continued.text).toBe('NEW prefix continuation');
    expect(reduceAttemptText(continued, 'message.rollback', {
      attempt_id: 'attempt-continuation',
    }).text).toBe('NEW prefix');
  });

  it('normalizes the rollback event through the renderer wire gate', () => {
    expect(normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'rollback-1', run_id: 'run-1', sequence: 1,
      timestamp: new Date(0).toISOString(), event: 'message.rollback',
      data: { attempt: 1, attempt_id: 'attempt-old' },
    })).toMatchObject({ type: 'message.rollback', data: { attempt_id: 'attempt-old' } });
  });

  it('renders the real runtime envelope sequence without rolled-back text and keeps cancelled state', () => {
    vi.stubGlobal('window', new EventTarget());
    const timestamp = new Date(0).toISOString();
    const run: AgentRun = {
      id: 'run-cancel-visible', conversationId: 'conversation-cancel-visible', title: 'cancelled attempt',
      status: 'running', phase: 'execution', startedAt: timestamp, updatedAt: timestamp,
      lastEventSequence: 0, events: [],
    };
    useAtlasStore.setState({ runs: [run], activeRunId: run.id, activeConversationId: run.conversationId, busy: true });

    const envelopes = [
      { event: 'run.started', data: { content: 'prompt' } },
      { event: 'message.delta', data: { content: 'OLD answer', attempt_id: 'attempt-old' } },
      { event: 'message.rollback', data: { attempt_id: 'attempt-old', category: 'cancelled' } },
      { event: 'message.delta', data: { content: 'NEW answer', attempt_id: 'attempt-new' } },
      { event: 'run.cancelled', data: { category: 'cancelled' } },
    ] as const;
    envelopes.forEach(({ event, data }, index) => {
      const normalized = normalizeRuntimeEvent({
        type: 'agent_event', event_id: `run-cancel-visible:${index + 1}`, run_id: run.id,
        sequence: index + 1, timestamp, event, data,
      });
      expect(normalized).not.toBeNull();
      if (normalized) useAtlasStore.getState().appendEvent(normalized);
    });

    const finalRun = useAtlasStore.getState().getRun(run.id)!;
    expect(finalRun.status).toBe('cancelled');
    expect(finalRun.events.map((event) => event.type)).toEqual([
      'run.started', 'message.delta', 'message.rollback', 'message.delta', 'run.cancelled',
    ]);
    const markup = renderToStaticMarkup(React.createElement(ConversationActivity, {
      events: finalRun.events, store: useAtlasStore.getState(), username: 'Atlas', setTab: () => undefined,
    }));
    expect(markup).toContain('NEW answer');
    expect(markup).not.toContain('OLD answer');
  });
});

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
    expect(normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:13', run_id: 'run-1', sequence: 13,
      timestamp: '2026-10-02T00:00:00Z', event: 'subtask.background_completed',
      data: { subtask_id: 'child-1', summary: 'done' },
    })?.type).toBe('subtask.background_completed');
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

describe('declared deliverables', () => {
  it('turns the present event into a titled artifact card in the renderer store', () => {
    useAtlasStore.setState({
      artifacts: [],
      runs: [{
        id: 'run-1', conversationId: 'conversation-1', title: 'Run',
        status: 'running', phase: 'execution', startedAt: '', updatedAt: '',
        lastEventSequence: 0, events: [],
      }],
      activeRunId: 'run-1',
    });
    const event = normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:14', run_id: 'run-1', sequence: 14,
      timestamp: '2026-10-02T00:00:00Z', event: 'artifact.created',
      data: {
        path: 'deliverables/plan.md', kind: 'document', tool: 'present',
        title: 'Implementation plan', summary: 'Ready for review',
      },
    });

    expect(event?.type).toBe('artifact.updated');
    if (!event) throw new Error('artifact.created should normalize');
    useAtlasStore.getState().appendEvent(event);

    expect(useAtlasStore.getState().artifacts).toContainEqual(expect.objectContaining({
      runId: 'run-1', type: 'file', name: 'Implementation plan',
      path: 'deliverables/plan.md', summary: 'Ready for review',
    }));
  });
});

describe('run event retention', () => {
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

  it('keeps every event when a long run exceeds the former 800 event limit', () => {
    let run = baseRun();
    const total = 920;
    for (let sequence = 1; sequence <= total; sequence++) run = applyRuntimeEvent(run, at(sequence));
    expect(run.events).toHaveLength(total);
    expect(run.events[0].sequence).toBe(1);
    expect(run.eventsTruncated).toBeFalsy();
    expect(run.droppedEventCount).toBe(0);
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
