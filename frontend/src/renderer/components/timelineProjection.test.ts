import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import { buildTimeline } from './timeline';
import { compactTimelineReplay, TimelineProjection } from './timelineProjection';

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

  it('keeps the current node baseline while replaying events that do not add timeline rows', () => {
    const projection = new TimelineProjection();
    const input = event('input', 1, 'run.started', 'hello');
    const initial = projection.project([input]);
    const baselineNode = initial[0];
    const updated = projection.project([
      input,
      event('phase', 2, 'run.phase', 'execution'),
      event('usage', 3, 'run.usage', 'tokens'),
    ]);
    expect(updated).toBe(initial);
    expect(updated[0]).toBe(baselineNode);
  });

  it('compacts a reconnect chunk burst without changing timeline semantics or its first node id', () => {
    const input = event('input', 1, 'run.started', 'hello');
    const chunks = Array.from({ length: 500 }, (_, index) => event(`chunk-${index}`, index + 2, 'message.delta', `word ${index} `));
    const replay = [input, ...chunks, event('final', 502, 'message.completed', chunks.map((chunk) => chunk.data.content).join(''))];
    const compacted = compactTimelineReplay(replay);
    expect(compacted).toHaveLength(3);
    expect(compacted[1].id).toBe('chunk-0');
    expect(buildTimeline(compacted)).toEqual(buildTimeline(replay));
    expect(new TimelineProjection().project(replay)).toEqual(buildTimeline(replay));
  });

  it('recognizes identical reconnected events and preserves unchanged structural nodes', () => {
    const projection = new TimelineProjection();
    const input = event('input', 1, 'run.started', 'hello');
    const initial = projection.project([input]);
    const replay = JSON.parse(JSON.stringify([input])) as AgentEvent[];
    expect(projection.project(replay)).toBe(initial);
    const updated = projection.project([...replay, event('reply', 2, 'message.completed', 'done')]);
    expect(updated[0]).toBe(initial[0]);
    expect(updated).toEqual(buildTimeline([...replay, event('reply', 2, 'message.completed', 'done')]));
  });

  it('incrementally assembles structural nodes while keeping earlier published snapshots immutable', () => {
    const make = (id: string, type: AgentEvent['type'], data: AgentEvent['data']): AgentEvent => ({
      id, runId: 'run-1', sequence: 1, type, timestamp: new Date(0).toISOString(), data,
    });
    const events = [
      make('input', 'run.started', { content: 'Inspect and update the file' }),
      make('thinking', 'run.status', { status: 'reasoning', text: 'Read first' }),
      make('preparing', 'tool.preparing', { index: 0, name: 'read_file', chars: 4, preview: 'src/' }),
      make('start', 'tool.started', { name: 'read_file', tool_call_id: 'call-1', arguments: { path: 'src/app.ts' } }),
      make('output', 'tool.output', { tool_call_id: 'call-1', content: 'source' }),
      make('finish', 'tool.completed', { name: 'read_file', tool_call_id: 'call-1', result: { content: 'source' } }),
      make('approval', 'approval.required', { tool: 'local_edit', approval_id: 'approval-1' }),
      make('answer', 'approval.responded', { approval_id: 'approval-1', choice: 'allow_once' }),
      make('chunk-1', 'message.delta', { content: 'Done ' }),
      make('chunk-2', 'message.delta', { content: 'now' }),
      make('message', 'message.completed', { content: 'Done now' }),
      make('done', 'run.completed', { changes: { files: 1, additions: 2, deletions: 1 } }),
    ];
    const projection = new TimelineProjection();
    const snapshots: Array<{ items: ReturnType<typeof buildTimeline>; serialized: string }> = [];
    for (let length = 1; length <= events.length; length += 1) {
      const items = projection.project(events.slice(0, length));
      expect(items).toEqual(buildTimeline(events.slice(0, length)));
      for (const snapshot of snapshots) expect(JSON.stringify(snapshot.items)).toBe(snapshot.serialized);
      snapshots.push({ items, serialized: JSON.stringify(items) });
    }
    expect(snapshots.at(-1)!.items[0]).toBe(snapshots[0].items[0]);
    const reconnect = JSON.parse(JSON.stringify(events)) as AgentEvent[];
    expect(new TimelineProjection().project(reconnect)).toEqual(snapshots.at(-1)!.items);
  });
});
