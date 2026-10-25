export type AgentRunStatus = 'idle' | 'planning' | 'running' | 'waiting' | 'paused' | 'completed' | 'failed' | 'cancelled';
export type AgentRunPhase = 'planning' | 'reasoning' | 'execution' | 'verification' | 'final';

export type AgentEventType =
  | 'run.started' | 'run.status' | 'run.phase' | 'run.background'
  | 'message.delta' | 'message.completed'
  | 'tool.preparing' | 'tool.started' | 'tool.output' | 'tool.completed' | 'approval.required' | 'approval.responded'
  | 'artifact.updated' | 'run.paused' | 'run.resumed'
  | 'run.plan.updated'
  | 'run.steered' | 'run.usage' | 'run.todos' | 'rules.loaded' | 'run.context.sources' | 'input.required' | 'run.plan.proposed'
  | 'subtask.started' | 'subtask.progress' | 'subtask.output' | 'subtask.completed' | 'subtask.group_completed'
  | 'subtask.steered' | 'subtask.steer_rejected'
  | 'check.results'
  | 'rules.trust_required' | 'hook.ran'
  | 'run.model_switched' | 'run.verify_nudge' | 'canvas.update'
  | 'mcp.startup.progress'
  | 'session.title'
  | 'process.completed' | 'process.notification' | 'run.compaction.progress' | 'run.recovery.notice' | 'context.window.switched' | 'chapter.marked'
  | 'run.completed' | 'run.failed' | 'run.cancelled'
  | 'lsp.diagnostics' | 'review.findings'
  | 'computer.foreground_required' | 'computer.foreground_resumed' | 'computer.foreground_denied' | 'computer.step' | 'computer.frame'
  | 'browser.handoff_required' | 'browser.handoff_resolved' | 'browser.panel.sync' | 'browser.step' | 'browser.artifact'
  | 'browser.vault_fill_denied';

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
  /** True when this conversation's run is continuing without owning the chat pane. */
  background?: boolean;
  /** 长会话有界化：events 超出上限后丢掉了最旧的事件，时间线头部会显示占位。 */
  eventsTruncated?: boolean;
  /** 已被丢弃的最旧事件条数。 */
  droppedEventCount?: number;
}
