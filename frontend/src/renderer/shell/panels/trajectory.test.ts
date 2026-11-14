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

  it('accepts live runtime events that carry the name in `type`, identically to archived `event` rows', () => {
    // Live runtime frames (renderer AgentEvent) use `type`; archived rollout rows use `event`.
    expect(describeTrajectoryEvent({ type: 'tool.started', data: { name: 'terminal', arguments: { command: 'ls' } } }))
      .toEqual({ label: '开始工具 · terminal', detail: '{"command":"ls"}' });
    expect(describeTrajectoryEvent({ type: 'message.delta', data: { content: '正在写' } }))
      .toEqual({ label: '生成回复', detail: '正在写' });
    expect(describeTrajectoryEvent({ type: 'run.completed' }).label).toBe('运行完成');
    expect(describeTrajectoryEvent({ type: 'tool.completed', data: { name: 'local_file', result: { lines: 3 } } }))
      .toEqual({ label: '完成工具 · local_file', detail: '{"lines":3}' });
    // `type` wins when both keys are present, so live frames never fall through to replay spelling.
    expect(describeTrajectoryEvent({ type: 'run.failed', event: 'run.completed', data: { error: 'boom' } }))
      .toEqual({ label: '运行失败', detail: 'boom' });
    expect(describeTrajectoryEvent({}).label).toBe('unknown');
  });
});
