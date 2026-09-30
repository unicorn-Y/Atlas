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

export function normalizeRuntimeEvent(envelope: RuntimeEventEnvelope): AgentEvent | null {
  const known = new Set(['run.started', 'run.status', 'run.phase', 'message.delta', 'message.completed', 'tool.started', 'tool.output', 'tool.completed', 'approval.required', 'approval.responded', 'artifact.updated', 'run.paused', 'run.resumed', 'run.plan.updated', 'run.steered', 'run.usage', 'rules.loaded', 'input.required', 'run.plan.proposed', 'run.completed', 'run.failed', 'run.cancelled']);
  if (!known.has(envelope.event)) return null;
  return { id: envelope.event_id, runId: envelope.run_id, sequence: envelope.sequence, type: envelope.event as AgentEvent['type'], timestamp: envelope.timestamp, data: envelope.data ?? {} };
}

export function applyRuntimeEvent(run: AgentRun, event: AgentEvent): AgentRun {
  if (run.id !== event.runId || run.events.some((item) => item.id === event.id) || run.events.some((item) => item.sequence === event.sequence)) return run;
  const data = event.data;
  let status = run.status;
  let phase = run.phase;
  if (event.type === 'run.status' && typeof data.status === 'string' && statuses.has(data.status as AgentRunStatus)) status = data.status as AgentRunStatus;
  if (event.type === 'run.phase' && typeof data.phase === 'string' && phases.has(data.phase as AgentRunPhase)) phase = data.phase as AgentRunPhase;
  if (event.type === 'run.paused') status = 'paused';
  if (event.type === 'run.resumed') status = 'running';
  if (event.type === 'run.cancelled') status = 'cancelled';
  if (event.type === 'approval.required' || event.type === 'input.required' || event.type === 'run.plan.proposed') status = 'waiting';
  // The answer to a question or plan arrives as ordinary progress, not as its own event.
  if ((event.type === 'message.delta' || event.type === 'tool.started') && status === 'waiting') status = 'running';
  if (event.type === 'run.completed') { status = 'completed'; phase = 'final'; }
  if (event.type === 'run.failed') status = 'failed';
  return { ...run, status, phase, updatedAt: event.timestamp, lastEventSequence: Math.max(run.lastEventSequence, event.sequence), events: [...run.events, event].sort((a, b) => a.sequence - b.sequence) };
}
