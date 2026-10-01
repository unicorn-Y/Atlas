import { expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import { buildTimeline, splitMoa } from './timeline';
import { latestTodos } from './TodoStrip';

let sequence = 0;
const event = (type: AgentEvent['type'], data: Record<string, unknown>): AgentEvent =>
  ({ id: `e${++sequence}`, runId: 'run', sequence, type, timestamp: '2026-10-02T00:00:00Z', data });

it('keeps only the newest todo revision even when an older one arrives late', () => {
  const todos = latestTodos([
    event('run.todos', { revision: 2, todos: [{ id: 'a', text: '写测试', status: 'completed' }] }),
    event('run.todos', { revision: 1, todos: [{ id: 'a', text: '写测试', status: 'pending' }] }),
  ]);
  expect(todos).toEqual([{ id: 'a', text: '写测试', status: 'completed' }]);
});

it('shows sub-agent type, steering and background completion', () => {
  const items = buildTimeline([
    event('run.started', { content: '查一下' }),
    event('subtask.started', { subtask_id: 's1', goal: '看代码', agent: 'explore', background: true, depth: 1, model: 'fast-model' }),
    event('subtask.steered', { subtask_id: 's1', text: '只看 core/' }),
    event('subtask.completed', { subtask_id: 's1', status: 'completed', summary: '找到了' }),
    event('subtask.background_completed', { subtask_id: 's1', summary: '找到了' }),
  ]);
  const steps = items.find((item) => item.kind === 'steps');
  expect(steps && steps.kind === 'steps' && steps.steps[0].agent).toMatchObject({ type: 'explore', background: true, model: 'fast-model' });
  expect(steps && steps.kind === 'steps' && steps.steps[0].steers).toEqual(['只看 core/']);
  expect(items.some((item) => item.kind === 'background' && item.summary === '找到了')).toBe(true);
});

it('carries verification results and consultation references into cards', () => {
  const items = buildTimeline([
    event('subtask.group_completed', { summary: '汇总', results: [
      { index: 0, title: 'A', status: 'completed', verified: true },
      { index: 1, title: 'B', status: 'completed', verified: false, verifier_note: '缺测试' },
    ] }),
    event('moa.references', { models: ['m1'], references: [{ model: 'm1', text: '建议先读日志' }], latency_ms: 1200 }),
  ]);
  const group = items.find((item) => item.kind === 'group');
  expect(group && group.kind === 'group' && group.results[1]).toMatchObject({ verified: false, verifier_note: '缺测试' });
  expect(items.find((item) => item.kind === 'moa')).toMatchObject({ latencyMs: 1200, references: [{ model: 'm1', text: '建议先读日志' }] });
});

it('strips the /moa prefix and marks the message as a consultation', () => {
  expect(splitMoa('/moa 这个方案行吗')).toEqual({ moa: true, text: '这个方案行吗' });
  expect(splitMoa('/moat 不是会诊')).toEqual({ moa: false, text: '/moat 不是会诊' });
  const items = buildTimeline([event('run.started', { content: '/moa 这个方案行吗' })]);
  expect(items[0]).toMatchObject({ kind: 'user', content: '这个方案行吗', moa: true });
});
