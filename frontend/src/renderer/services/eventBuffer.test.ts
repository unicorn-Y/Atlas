import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createEventBuffer } from './eventBuffer';
import type { AgentEvent } from '../../types/runtime';

const delta = (sequence: number, content: string): AgentEvent =>
  ({ id: `e${sequence}`, runId: 'r1', sequence, type: 'message.delta', timestamp: '2026-10-02T00:00:00Z', data: { content } });
const event = (sequence: number, type: AgentEvent['type'], data: Record<string, unknown> = {}): AgentEvent =>
  ({ id: `e${sequence}`, runId: 'r1', sequence, type, timestamp: '2026-10-02T00:00:00Z', data });

describe('eventBuffer', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('coalesces a burst of deltas into one merged event at ~12.5Hz', () => {
    const out: AgentEvent[] = [];
    const buffer = createEventBuffer((events) => out.push(...events), { intervalMs: 80 });
    for (let sequence = 1; sequence <= 50; sequence++) buffer.push(delta(sequence, '字'));
    expect(out).toHaveLength(0);
    vi.advanceTimersByTime(81);
    expect(out).toHaveLength(1);
    expect(out[0].type).toBe('message.delta');
    // id 取第一条（时间线 reply 的稳定 key），sequence 取最后一条，内容按顺序拼接。
    expect(out[0].id).toBe('e1');
    expect(out[0].sequence).toBe(50);
    expect(out[0].data.content).toBe('字'.repeat(50));
  });

  it('passes non-delta events through immediately and flushes pending deltas first', () => {
    const out: AgentEvent[] = [];
    const buffer = createEventBuffer((events) => out.push(...events), { intervalMs: 80 });
    buffer.push(delta(1, 'hello '));
    buffer.push(delta(2, 'world'));
    buffer.push(event(3, 'tool.started', { name: 'local_shell' }));
    expect(out.map((item) => item.type)).toEqual(['message.delta', 'tool.started']);
    expect(out[0].data.content).toBe('hello world');
    expect(out[0].sequence).toBe(2);
  });

  it('keeps ordering across alternating deltas and control events', () => {
    const out: AgentEvent[] = [];
    const buffer = createEventBuffer((events) => out.push(...events), { intervalMs: 80 });
    buffer.push(delta(1, 'one'));
    buffer.push(event(2, 'run.started', { content: 'q' }));
    buffer.push(delta(3, 'two'));
    expect(out.map((item) => [item.type, item.data.content])).toEqual([
      ['message.delta', 'one'],
      ['run.started', 'q'],
    ]);
    vi.advanceTimersByTime(81);
    expect(out.map((item) => item.type)).toEqual(['message.delta', 'run.started', 'message.delta']);
    expect(out[2].data.content).toBe('two');
  });

  it('flushes and disposes on a terminal event, then passes later events straight through', () => {
    const out: AgentEvent[] = [];
    const buffer = createEventBuffer((events) => out.push(...events), { intervalMs: 80 });
    buffer.push(delta(1, 'tail'));
    buffer.push(event(2, 'run.completed', {}));
    expect(out.map((item) => item.type)).toEqual(['message.delta', 'run.completed']);
    buffer.push(delta(3, 'late'));
    expect(out).toHaveLength(3);
    expect(out[2].data.content).toBe('late');
    vi.advanceTimersByTime(400);
    expect(out).toHaveLength(3);
  });
});
