import type { ConversationSummary, ModelListResponse, RunStartRequest, RuntimeEventEnvelope, ToolListResponse } from './types';

export const mockModels: ModelListResponse = {
  models: [
    { id: 'gpt-5.6-luna', name: 'GPT-5.6 Luna', provider: 'OpenAI' },
    { id: 'claude-sonnet', name: 'Claude Sonnet', provider: 'Anthropic' },
  ],
  current: 'gpt-5.6-luna',
};

export const mockConversations: ConversationSummary[] = [
  { id: 'demo-planning', title: 'MemoryOS Protected State' },
  { id: 'demo-research', title: 'Atlas 工作区梳理' },
  { id: 'demo-writing', title: '起草产品更新说明' },
];

export const mockTools: ToolListResponse = {
  servers: ['Files', 'Terminal', 'Git', 'Browser'],
  tool_count: 12,
  tools: [],
};

export async function streamMockRun(request: RunStartRequest, onEvent: (event: RuntimeEventEnvelope) => void, shouldPause: () => boolean, shouldCancel: () => boolean, waitForApproval: (eventId: string) => Promise<'allow' | 'deny'>, registerControl: (send: (event: string, data?: Record<string, unknown>) => void) => void) {
  let sequence = 0;
  const emit = (event: string, data: Record<string, unknown> = {}) => onEvent({
    type: 'agent_event', run_id: request.run_id, event_id: `${request.run_id}:${++sequence}`,
    sequence, timestamp: new Date().toISOString(), event, data,
  });
  registerControl(emit);
  const delay = async () => {
    while (shouldPause() && !shouldCancel()) await new Promise((resolve) => setTimeout(resolve, 100));
    if (shouldCancel()) return false;
    await new Promise((resolve) => setTimeout(resolve, 180));
    return !shouldCancel();
  };
  emit('run.started', { status: 'running', phase: 'planning', content: request.content });
  if (!await delay()) { emit('run.cancelled'); return; }
  emit('run.status', { status: 'running' });
  emit('tool.started', { tool_call_id: `${request.run_id}:tool`, name: 'workspace.inspect', arguments: { query: request.content } });
  if (!await delay()) { emit('run.cancelled'); return; }
  emit('tool.completed', { tool_call_id: `${request.run_id}:tool`, name: 'workspace.inspect', result: { summary: 'Mock runtime 已完成工作区检查。' } });
  emit('artifact.updated', { artifact_id: `${request.run_id}:report`, artifact_type: 'report', name: 'runtime-report.md', summary: 'Mock Agent Runtime 事件流验收报告。', path: 'artifacts/runtime-report.md' });
  if (!await delay()) { emit('run.cancelled'); return; }
  const approval = { approval_id: `${request.run_id}:approval`, description: 'Mock Runtime 请求批准继续执行。', input: { action: 'continue', scope: '当前任务' } };
  const approvalEventId = `${request.run_id}:${sequence + 1}`;
  emit('approval.required', approval);
  const choice = await waitForApproval(approvalEventId);
  if (shouldCancel()) { emit('run.cancelled'); return; }
  emit('approval.responded', { approval_id: approval.approval_id, event_id: approvalEventId, choice });
  emit('run.status', { status: choice === 'allow' ? 'running' : 'completed', approval_choice: choice });
  emit('message.delta', { content: choice === 'allow' ? '批准已收到，Mock 运行已完成。' : '请求已拒绝，Mock 运行已安全结束。' });
  emit('run.completed', { result: choice === 'allow' ? 'completed' : 'approval_rejected' });
}
