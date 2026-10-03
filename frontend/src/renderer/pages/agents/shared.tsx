import { HeartPulse, Radio } from 'lucide-react';
import { AGENT_STATUS_META } from '../../store/persistentSlice';
import type { AgentStatus, PersistentAgentRecord } from '../../services/persistentApi';
import { cn } from '../../ui/cn';

/** 输入框统一外观（与 TelegramPanel/GroupsView 的 field 保持一致）。 */
export const field = 'h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
export const fieldArea = 'rounded-[9px] bg-sunken px-3 py-2 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

/** 状态徽标：idle | working | waiting_user | offline（§3 运行投影）。 */
export function StatusBadge({ status, className }: { status?: AgentStatus | string; className?: string }) {
  const meta = AGENT_STATUS_META[(status ?? 'offline') as AgentStatus] ?? AGENT_STATUS_META.offline;
  return <span className={cn('inline-flex items-center gap-1 text-[12px]', meta.className, className)}>
    <i className={cn('size-1.5 rounded-full', status === 'working' ? 'animate-pulse bg-brand' : status === 'waiting_user' ? 'bg-danger' : 'bg-current')} />
    {meta.label}
  </span>;
}

/** 列表行的 heartbeat / 渠道标记。 */
export function AgentMarkers({ agent }: { agent: PersistentAgentRecord }) {
  const channels = agent.agent?.channels ?? [];
  return <span className="flex shrink-0 items-center gap-1.5 text-fg-3">
    {agent.agent?.heartbeat?.enabled && <HeartPulse size={12} className="text-brand" aria-label="心跳已开启" />}
    {channels.slice(0, 2).map((binding) => <Radio key={`${binding.channel}:${binding.target}`} size={12} aria-label={`渠道 ${binding.channel}`} />)}
    {channels.length > 2 && <span className="text-[10.5px]">+{channels.length - 2}</span>}
  </span>;
}

export function Label({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return <label className="grid gap-1 text-[13px] text-fg-2">
    {children}
    {hint && <small className="text-[11.5px] leading-[1.5] text-fg-3">{hint}</small>}
  </label>;
}
