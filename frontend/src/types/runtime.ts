export type AgentRunStatus = 'idle' | 'planning' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed' | 'cancelled';
export type AgentRunPhase = 'planning' | 'reasoning' | 'execution' | 'verification' | 'final';

export type AgentEventType =
  | 'run.started' | 'run.status' | 'run.phase'
  | 'message.delta' | 'message.completed'
  | 'tool.started' | 'tool.output' | 'tool.completed' | 'approval.required' | 'approval.responded'
  | 'artifact.updated' | 'run.paused' | 'run.resumed'
  | 'run.plan.updated'
  | 'run.steered' | 'run.usage' | 'rules.loaded' | 'input.required' | 'run.plan.proposed'
  | 'subtask.started' | 'subtask.progress' | 'subtask.output' | 'subtask.completed' | 'subtask.group_completed'
  | 'check.results'
  | 'rules.trust_required' | 'hook.ran'
  | 'run.model_switched' | 'run.verify_nudge'
  | 'session.title'
  | 'process.completed' | 'process.notification' | 'run.compaction.progress' | 'run.recovery.notice' | 'context.window.switched'
  | 'run.completed' | 'run.failed' | 'run.cancelled';

export interface AgentEvent {
  id: string;
  runId: string;
  sequence: number;
  type: AgentEventType;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface AgentRun {
  id: string;
  conversationId: string;
  title: string;
  status: AgentRunStatus;
  phase: AgentRunPhase;
  startedAt: string;
  updatedAt: string;
  lastEventSequence: number;
  events: AgentEvent[];
}
