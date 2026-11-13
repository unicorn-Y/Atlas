import { describe, expect, it } from 'vitest';
import { describeTrajectoryEvent } from './trajectory';

describe('trajectory event descriptions', () => {
  it('turns tool lifecycle events into readable steps', () => {
    expect(describeTrajectoryEvent({ event: 'tool.started', data: { name: 'local_file', action: 'read' } }).label)
      .toBe('开始工具 · local_file');
    expect(describeTrajectoryEvent({ event: 'tool.completed', data: { name: 'local_file', is_error: true } }).label)
      .toBe('工具失败 · local_file');
  });

  it('summarizes message, approval, and unknown events without losing the event name', () => {
    expect(describeTrajectoryEvent({ event: 'message.completed', data: { role: 'assistant', content: 'Done' } }))
      .toEqual({ label: '助手回复', detail: 'Done' });
    expect(describeTrajectoryEvent({ event: 'approval.required', data: { tool_name: 'terminal' } }).label)
      .toBe('等待审批 · terminal');
    expect(describeTrajectoryEvent({ event: 'custom.event' }).label).toBe('custom.event');
  });
});
