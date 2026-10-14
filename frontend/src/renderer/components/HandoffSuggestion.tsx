import { ArrowRight } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';

export default function HandoffSuggestion({ event }: { event: AgentEvent }) {
  const reason = typeof event.data.reason === 'string' ? event.data.reason : '当前会话上下文已压缩多次';
  const goal = typeof event.data.suggested_goal === 'string' ? event.data.suggested_goal : '';
  return <div className="my-3 ml-10 flex flex-wrap items-center gap-2 text-[12.5px] text-fg-2" role="status">
    <span>{reason}。可以把下一阶段接力到新会话。</span>
    <button type="button" onClick={() => window.dispatchEvent(new CustomEvent('atlas:handoff-open', { detail: { goal } }))}
      className="inline-flex items-center gap-1 text-brand hover:underline">
      <ArrowRight size={13} />接力到新会话
    </button>
  </div>;
}
