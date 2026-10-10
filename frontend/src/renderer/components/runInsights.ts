import type { AgentEvent } from '../../types/runtime';

/**
 * Derived views over one run's event stream for the token breakdown, the todo panel and the progress capsule.
 * Pure functions: everything is recomputed from events, nothing is stored.
 */

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';
export interface TodoItem { id: string; text: string; status: TodoStatus; parent?: string }

const TODO_STATUSES = new Set<TodoStatus>(['pending', 'in_progress', 'completed', 'cancelled']);

/** Latest todo list the Agent wrote (run.todos), with its revision; null when the run never made one. */
export function latestTodos(events: AgentEvent[]): { revision: number; todos: TodoItem[] } | null {
  for (let index = events.length - 1; index >= 0; index--) {
    const event = events[index];
    if (event.type !== 'run.todos') continue;
    const raw = Array.isArray(event.data.todos) ? event.data.todos : [];
    const todos = raw.flatMap((value, position): TodoItem[] => {
      if (!value || typeof value !== 'object') return [];
      const record = value as Record<string, unknown>;
      const text = String(record.text ?? record.content ?? '').trim();
      if (!text) return [];
      const status = TODO_STATUSES.has(record.status as TodoStatus) ? record.status as TodoStatus : 'pending';
      return [{ id: String(record.id ?? position + 1), text, status, ...(record.parent ? { parent: String(record.parent) } : {}) }];
    });
    return { revision: Number(event.data.revision ?? 0), todos };
  }
  return null;
}

/** Messages Atlas sends on the user's behalf when they edit the todo list start with this tag. */
export const TODO_EDIT_TAG = '[待办更新]';
export const isTodoEdit = (content: string) => content.trimStart().startsWith(TODO_EDIT_TAG);

/** The instruction handed to the Agent after the user edited its list (steered mid-run, or a new message after it ended). */
export function todoEditMessage(todos: TodoItem[], running: boolean): string {
  const lines = todos.map((item) => `- [${item.status}] ${item.id}: ${item.text}`);
  return [
    `${TODO_EDIT_TAG} 我手动调整了任务清单。请先调用 todo_list（merge=false）把清单整体替换成下面这样，id 保持不变，然后${running ? '按新清单继续当前任务' : '按新清单把没完成的项做完'}：`,
    ...lines,
  ].join('\n');
}

/** Parses a todo-edit message back into items, for showing it compactly in the thread. */
export function parseTodoEdit(content: string): TodoItem[] {
  return content.split('\n').flatMap((line): TodoItem[] => {
    const match = /^- \[(\w+)\] ([^:]+): (.*)$/.exec(line.trim());
    if (!match) return [];
    const status = TODO_STATUSES.has(match[1] as TodoStatus) ? match[1] as TodoStatus : 'pending';
    return [{ id: match[2], text: match[3], status }];
  });
}

export interface ModelUsage { model: string; requests: number; input: number; output: number; cached: number }
export interface ContextCategory { id: string; label: string; tokens: number }
export interface UsageSummary {
  requests: number;
  input: number;
  output: number;
  cached: number;
  cacheWrite: number;
  reasoning: number;
  /** Tokens spent by delegated sub-agents (already included in the totals). */
  subtaskTokens: number;
  /** Background calls such as titles and memory, not the conversation itself (already included). */
  sideTokens: number;
  cost: number | null;
  byModel: ModelUsage[];
  context: { used: number; limit: number; percent: number; estimated: boolean; categories: ContextCategory[] } | null;
  /** Total tokens of each request in order, for the sparkline. */
  perRequest: number[];
}

const num = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? value : 0;

const CONTEXT_LABEL: Record<string, string> = {
  system_prompt: '系统提示', tool_definitions: '工具定义', rules: '规则文件', skills: '技能',
  mcp: 'MCP 工具', subagent_definitions: '子 Agent', memory: '记忆', conversation: '对话内容',
};

/** Sums every run.usage row of a run. Rows re-emitted with the same request_id replace the earlier one. */
export function usageSummary(events: AgentEvent[]): UsageSummary | null {
  const rows = new Map<string, Record<string, unknown>>();
  let anonymous = 0;
  for (const event of events) {
    if (event.type !== 'run.usage') continue;
    const id = typeof event.data.request_id === 'string' && event.data.request_id ? event.data.request_id : `anon-${anonymous++}`;
    rows.set(id, event.data);
  }
  if (!rows.size) return null;
  const summary: UsageSummary = { requests: 0, input: 0, output: 0, cached: 0, cacheWrite: 0, reasoning: 0, subtaskTokens: 0, sideTokens: 0, cost: 0, byModel: [], context: null, perRequest: [] };
  const models = new Map<string, ModelUsage>();
  let costKnown = false;
  for (const row of rows.values()) {
    const input = num(row.input_tokens);
    const output = num(row.output_tokens);
    const cached = num(row.cached_input_tokens);
    summary.requests += 1;
    summary.input += input;
    summary.output += output;
    summary.cached += cached;
    summary.cacheWrite += num(row.cache_write_tokens);
    summary.reasoning += num(row.reasoning_tokens);
    summary.perRequest.push(input + output);
    if (row.subtask_id) summary.subtaskTokens += input + output;
    if (row.purpose && row.purpose !== 'conversation') summary.sideTokens += input + output;
    const cost = typeof row.cost_usd === 'number' ? row.cost_usd : typeof row.est_cost === 'number' ? row.est_cost : null;
    if (cost !== null) { costKnown = true; summary.cost = (summary.cost ?? 0) + cost; }
    const model = String(row.model || row.wire_model || '未知模型');
    const entry = models.get(model) ?? { model, requests: 0, input: 0, output: 0, cached: 0 };
    entry.requests += 1; entry.input += input; entry.output += output; entry.cached += cached;
    models.set(model, entry);
  }
  if (!costKnown) summary.cost = null;
  summary.byModel = [...models.values()].sort((a, b) => (b.input + b.output) - (a.input + a.output));
  // The newest conversation row describes the context window right now.
  const latest = [...rows.values()].reverse().find((row) => (!row.purpose || row.purpose === 'conversation') && !row.subtask_id);
  if (latest) {
    const breakdown = latest.context_breakdown && typeof latest.context_breakdown === 'object' ? latest.context_breakdown as Record<string, unknown> : null;
    const used = num(breakdown?.context_used) || num(latest.context_tokens);
    const limit = num(breakdown?.context_max) || num(latest.context_limit);
    if (used && limit) {
      const categories = Array.isArray(breakdown?.categories) ? (breakdown!.categories as Array<Record<string, unknown>>)
        .map((item) => ({ id: String(item.id ?? ''), label: CONTEXT_LABEL[String(item.id ?? '')] ?? String(item.label ?? item.id ?? ''), tokens: num(item.tokens) }))
        .filter((item) => item.tokens > 0) : [];
      summary.context = { used, limit, percent: Math.min(100, Math.round(used / limit * 100)), estimated: Boolean(breakdown?.context_estimated), categories };
    }
  }
  return summary;
}

/** "12.3k" / "1.2M" style token counts. */
export function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 100_000 ? 0 : 1)}k`;
  return String(Math.round(value));
}

export function formatCost(value: number): string {
  return value >= 1 ? `$${value.toFixed(2)}` : value >= 0.01 ? `$${value.toFixed(3)}` : `$${value.toFixed(4)}`;
}

/** Live "1:05" style clock between two instants. */
export function clock(from: string, to?: string | number): string {
  const end = typeof to === 'number' ? to : to ? new Date(to).getTime() : Date.now();
  const seconds = Math.max(0, Math.floor((end - new Date(from).getTime()) / 1000));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}
