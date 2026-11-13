import type { AgentEvent } from '../../types/runtime';
import { describeTrajectoryEvent } from '../shell/panels/trajectory';

/** Readable event trajectory used as the alternate presentation of a conversation. */
export default function ConversationTrajectory({ events }: { events: AgentEvent[] }) {
  return <ol aria-label="会话轨迹" className="m-0 grid list-none gap-2 p-0">
    {events.map((event, index) => {
      const description = describeTrajectoryEvent(event as unknown as Record<string, unknown>);
      return <li key={event.id ?? `${event.timestamp}-${index}`} className="overflow-hidden rounded-xl card-surface">
        <div className="flex flex-wrap gap-x-2 border-b border-line px-3 py-2 text-[11px] text-fg-3">
          <time>{event.timestamp || '无时间戳'}</time>
          <b className="text-fg-2">{description.label}</b>
          <span className="font-mono">#{index + 1}</span>
        </div>
        {description.detail && <p className="m-0 whitespace-pre-wrap break-words px-3 py-2 text-[12px] text-fg-2">{description.detail}</p>}
      </li>;
    })}
  </ol>;
}
