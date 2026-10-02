import type { AgentEvent } from '../../types/runtime';

const TERMINAL = new Set(['run.completed', 'run.failed', 'run.cancelled']);

export interface EventBuffer {
  /** 送进一个事件：流式 delta 攒批，其余立即透传（透传前先冲出攒着的 delta，保证顺序）。 */
  push: (event: AgentEvent) => void;
  /** 立刻冲出攒着的 delta（合并成一条合成事件）。 */
  flush: () => void;
  /** 停止定时器并冲出剩余事件；之后送进的事件直接透传。 */
  dispose: () => void;
}

export interface EventBufferOptions {
  /** 攒批间隔（毫秒）；默认 80ms，约 12.5Hz。 */
  intervalMs?: number;
}

/**
 * 流式事件合流器：message.delta 按 ~12.5Hz 合并成一条合成 delta 再进 store（内容拼接、
 * id 取第一条保持时间线 reply 的稳定 key、sequence 取最后一条），让长回复流式时
 * React 每秒最多重渲染十几次而不是每个 delta 一次。其余事件零延迟透传。
 */
export function createEventBuffer(sink: (events: AgentEvent[]) => void, options: EventBufferOptions = {}): EventBuffer {
  const intervalMs = Math.max(1, options.intervalMs ?? 80);
  let pending: AgentEvent[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  const flush = () => {
    if (timer) { clearTimeout(timer); timer = null; }
    if (!pending.length) return;
    const events = coalesce(pending);
    pending = [];
    sink(events);
  };
  const schedule = () => {
    if (timer) return;
    timer = setTimeout(() => { timer = null; flush(); }, intervalMs);
  };
  const dispose = () => {
    disposed = true;
    flush();
  };

  return {
    push: (event) => {
      if (disposed || event.type !== 'message.delta') {
        // 非流式事件立即透传，但先把攒着的 delta 冲出去，run.events 的顺序保持到达顺序。
        flush();
        sink([event]);
        if (TERMINAL.has(event.type)) dispose();
        return;
      }
      pending.push(event);
      schedule();
    },
    flush,
    dispose,
  };
}

/** 相邻的 delta 合成一条；不同类型的事件之间保持独立（正常情况下攒批里只有 delta）。 */
function coalesce(deltas: AgentEvent[]): AgentEvent[] {
  const merged: AgentEvent[] = [];
  for (const event of deltas) {
    const previous = merged[merged.length - 1];
    if (previous && previous.type === 'message.delta' && event.type === 'message.delta') {
      merged[merged.length - 1] = {
        ...previous,
        sequence: event.sequence,
        timestamp: event.timestamp,
        data: { ...previous.data, content: String(previous.data.content ?? '') + String(event.data.content ?? '') },
      };
    } else {
      merged.push(event);
    }
  }
  return merged;
}
