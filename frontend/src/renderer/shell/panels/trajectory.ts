export interface TrajectoryDescription { label: string; detail?: string }

const text = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return undefined;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try { return JSON.stringify(value); } catch { return undefined; }
};

/**
 * Runtime events carry their name in `type`; archived transcript/rollout rows carried `event`.
 * Accept both so live runs and replayed history describe identically.
 */
export function describeTrajectoryEvent(event: Record<string, unknown>): TrajectoryDescription {
  const type = typeof event.type === 'string' ? event.type
    : typeof event.event === 'string' ? event.event : 'unknown';
  const data = event.data && typeof event.data === 'object' && !Array.isArray(event.data)
    ? event.data as Record<string, unknown>
    : {};
  const tool = typeof data.name === 'string' ? data.name : typeof data.tool_name === 'string' ? data.tool_name : '工具';
  const content = typeof data.content === 'string' ? data.content : undefined;
  switch (type) {
    case 'tool.started': return { label: `开始工具 · ${tool}`, detail: text(data.arguments) };
    case 'tool.completed': return { label: data.is_error === true || data.status === 'failed' ? `工具失败 · ${tool}` : `完成工具 · ${tool}`,
      detail: typeof data.content === 'string' ? data.content : text(data.result) };
    case 'tool.output': return { label: `工具输出 · ${tool}`, detail: content };
    case 'message.delta': return { label: '生成回复', detail: content };
    case 'message.completed': return { label: data.role === 'user' ? '用户消息' : '助手回复', detail: content };
    case 'approval.required': return { label: `等待审批 · ${typeof data.tool_name === 'string' ? data.tool_name : '请求'}` };
    case 'approval.responded': return { label: '审批已处理', detail: typeof data.outcome === 'string' ? data.outcome : undefined };
    case 'run.completed': return { label: '运行完成' };
    case 'run.failed': return { label: '运行失败', detail: typeof data.error === 'string' ? data.error : undefined };
    case 'run.cancelled': return { label: '运行已取消' };
    default: return { label: type };
  }
}
