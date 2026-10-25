import type { AgentEvent, AgentRun, AgentRunPhase, AgentRunStatus } from '../../types/runtime';

export interface RuntimeEventEnvelope {
  type: 'agent_event';
  event_id: string;
  run_id: string;
  sequence: number;
  timestamp: string;
  event: string;
  data?: Record<string, unknown>;
}

const statuses = new Set<AgentRunStatus>(['idle', 'planning', 'running', 'waiting', 'paused', 'completed', 'failed', 'cancelled']);
const phases = new Set<AgentRunPhase>(['planning', 'reasoning', 'execution', 'verification', 'final']);

export function isRuntimeEvent(value: unknown): value is RuntimeEventEnvelope {
  if (!value || typeof value !== 'object') return false;
  const event = value as Partial<RuntimeEventEnvelope>;
  return event.type === 'agent_event' && typeof event.event_id === 'string' && typeof event.run_id === 'string'
    && Number.isInteger(event.sequence) && typeof event.timestamp === 'string' && typeof event.event === 'string';
}

const DOCUMENT_KIND: Record<string, string> = { document: '生成了 Word 文档', spreadsheet: '生成了 Excel 表格', presentation: '生成了 PPT 演示文稿' };

export function normalizeRuntimeEvent(envelope: RuntimeEventEnvelope): AgentEvent | null {
  // 已知事件才会被渲染；新的 wire 事件（如 lsp.diagnostics、review.findings、X2 的 computer.* / browser.*）加入这里即可显示。
  const known = new Set(['run.started', 'run.status', 'run.phase', 'message.delta', 'message.completed', 'tool.preparing', 'tool.started', 'tool.output', 'tool.completed', 'approval.required', 'approval.responded', 'artifact.updated', 'run.paused', 'run.resumed', 'run.plan.updated', 'run.steered', 'run.usage', 'run.todos', 'rules.loaded', 'run.context.sources', 'input.required', 'run.plan.proposed', 'subtask.started', 'subtask.progress', 'subtask.output', 'subtask.completed', 'subtask.group_completed', 'check.results', 'rules.trust_required', 'hook.ran', 'run.model_switched', 'run.verify_nudge', 'session.title', 'process.completed', 'run.compaction.progress', 'run.recovery.notice', 'context.window.switched', 'chapter.marked', 'lsp.diagnostics', 'review.findings', 'run.completed', 'run.failed', 'run.cancelled',
    // X2 电脑操控：前台确认、恢复与每一步动作（供 ForegroundConfirmCard / ComputerEdgeBar / ComputerReplayPanel）。
    'computer.foreground_required', 'computer.foreground_resumed', 'computer.foreground_denied', 'computer.step', 'computer.frame',
    // X2 浏览器代理：交接确认与结果、面板地址同步、录制中的每一步（供 BrowserHandoffCard / BrowserRecorderPanel）。
    'browser.handoff_required', 'browser.handoff_resolved', 'browser.panel.sync', 'browser.step', 'browser.artifact',
    'browser.vault_fill_denied']);
  known.add('process.notification');
  const base = { id: envelope.event_id, runId: envelope.run_id, sequence: envelope.sequence, timestamp: envelope.timestamp };
  // Office files and other generated documents: shown like any other artifact.
  if (envelope.event === 'artifact.created') {
    const data = envelope.data ?? {};
    const path = String(data.path ?? '');
    return { ...base, type: 'artifact.updated', data: {
      ...data, artifact_id: `created:${path || envelope.event_id}`, artifact_type: 'file',
      name: path.split(/[\\/]/).pop() || '文件', summary: DOCUMENT_KIND[String(data.kind)] ?? '生成了文件',
    } };
  }
  if (!known.has(envelope.event)) return null;
  return { ...base, type: envelope.event as AgentEvent['type'], data: envelope.data ?? {} };
}

/** 每个运行最多保留的事件数；超出后丢最旧的，时间线头部显示「已折叠早期事件」。 */
export const MAX_RUN_EVENTS = 800;

export function applyRuntimeEvent(run: AgentRun, event: AgentEvent): AgentRun {
  const data = event.data;
  let status = run.status;
  let phase = run.phase;
  if (event.type === 'run.status' && typeof data.status === 'string' && statuses.has(data.status as AgentRunStatus)) status = data.status as AgentRunStatus;
  if (event.type === 'run.phase' && typeof data.phase === 'string' && phases.has(data.phase as AgentRunPhase)) phase = data.phase as AgentRunPhase;
  if (event.type === 'run.paused') status = 'paused';
  if (event.type === 'run.resumed') status = 'running';
  if (event.type === 'run.cancelled') status = 'cancelled';
  if (event.type === 'approval.required' || event.type === 'input.required' || event.type === 'run.plan.proposed' || event.type === 'rules.trust_required') status = 'waiting';
  // The answer to a question or plan arrives as ordinary progress, not as its own event.
  if ((event.type === 'message.delta' || event.type === 'tool.started') && status === 'waiting') status = 'running';
  if (event.type === 'run.completed') { status = 'completed'; phase = 'final'; }
  if (event.type === 'run.failed') status = 'failed';
  // 去重：sequence 单调递增是 wire 契约，新 sequence 不可能重复，免去每个事件两次 O(n) 扫描；
  // 乱序/重放（sequence <= lastEventSequence，例如断线续传）才做完整查重并按 sequence 排回原位。
  let events: AgentEvent[];
  if (event.type === 'tool.preparing' && event.sequence > run.lastEventSequence) {
    // Argument-growth updates replace the previous one for the same call, keeping when it started,
    // so a long write_file does not push older events past MAX_RUN_EVENTS.
    let previous: AgentEvent | undefined;
    for (let i = run.events.length - 1; i >= 0; i -= 1) {
      const item = run.events[i];
      if (item.type === 'tool.started' || item.type === 'run.started') break;
      if (item.type === 'tool.preparing' && item.data.index === data.index && item.data.attempt === data.attempt) { previous = item; break; }
    }
    if (previous) {
      const kept = { ...event, data: { ...data, started_at: previous.data.started_at ?? previous.timestamp } };
      events = run.events.filter((item) => item !== previous);
      events.push(kept);
    } else events = [...run.events, event];
  } else if (event.sequence > run.lastEventSequence) {
    events = [...run.events, event];
  } else {
    if (run.events.some((item) => item.id === event.id) || run.events.some((item) => item.sequence === event.sequence)) return run;
    events = [...run.events, event].sort((a, b) => a.sequence - b.sequence);
  }
  // 长会话有界化：丢最旧的事件并记录数量，UI 在时间线头部显示占位。
  let truncated = run.eventsTruncated ?? false;
  let dropped = run.droppedEventCount ?? 0;
  if (events.length > MAX_RUN_EVENTS) {
    dropped += events.length - MAX_RUN_EVENTS;
    events = events.slice(events.length - MAX_RUN_EVENTS);
    truncated = true;
  }
  return { ...run, status, phase, updatedAt: event.timestamp, lastEventSequence: Math.max(run.lastEventSequence, event.sequence), events, eventsTruncated: truncated, droppedEventCount: dropped };
}
