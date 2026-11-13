import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import { buildTimeline } from './timeline';
import { TimelineProjection } from './timelineProjection';

const event = (id: string, sequence: number, type: AgentEvent['type'], content: string): AgentEvent => ({
  id, runId: 'run-1', sequence, type, timestamp: new Date(0).toISOString(), data: { content },
});

describe('TimelineProjection', () => {
  it('folds streamed deltas into one node while preserving unaffected node identities', () => {
    const projection = new TimelineProjection();
    const input = event('input', 1, 'run.started', 'hello');
    const firstDelta = event('delta-1', 2, 'message.delta', 'Atlas ');
    const secondDelta = event('delta-2', 3, 'message.delta', 'here');

    const initial = projection.project([input, firstDelta]);
    const userNode = initial[0];
    const firstReplyNode = initial[1];
    const updated = projection.project([input, firstDelta, secondDelta]);

    expect(updated).toEqual(buildTimeline([input, firstDelta, secondDelta]));
    expect(updated[0]).toBe(userNode);
    expect(updated[1]).not.toBe(firstReplyNode);
  });

  it('rebuilds when the event prefix is replaced or truncated', () => {
    const projection = new TimelineProjection();
    const original = event('input', 1, 'run.started', 'old');
    const replacement = event('input', 1, 'run.started', 'new');

    projection.project([original]);
    expect(projection.project([replacement])).toEqual(buildTimeline([replacement]));
    expect(projection.project([])).toEqual([]);
  });
});
