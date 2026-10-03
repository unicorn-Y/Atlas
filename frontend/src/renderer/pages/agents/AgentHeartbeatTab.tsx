import { useCallback, useEffect, useState } from 'react';
import { HeartPulse } from 'lucide-react';
import { agentsApi, type AgentHeartbeat as HeartbeatConfig, type AgentStatusProjection } from '../../services/persistentApi';
import { useAtlasStore } from '../../store/useAtlasStore';
import { relativeTime } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { field, fieldArea } from './shared';
import type { PersistentAgentRecord } from '../../services/persistentApi';

const DEFAULTS: HeartbeatConfig = {
  enabled: false, interval_minutes: 30, active_hours: '', prompt: '', delivery: 'owner', isolated_session: true,
};

/** Heartbeat：开关 / 间隔 / 活跃时间 / 检查指令 / 投递；运行投影（最后活动、下次检查）来自 status。 */
export default function AgentHeartbeatTab({ apiBaseUrl, agent, onToast }: {
  apiBaseUrl: string; agent: PersistentAgentRecord; onToast: (text: string) => void;
}) {
  const automations = useAtlasStore((state) => state.automations);
  const loadAutomations = useAtlasStore((state) => state.loadAutomations);
  const [form, setForm] = useState<HeartbeatConfig>({ ...DEFAULTS, ...(agent.agent?.heartbeat ?? {}) });
  const [status, setStatus] = useState<AgentStatusProjection | null>(null);
  const [busy, setBusy] = useState(false);
  const base = apiBaseUrl;
  const agentId = agent.id;

  useEffect(() => setForm({ ...DEFAULTS, ...(agent.agent?.heartbeat ?? {}) }), [agent.id, agent.agent?.heartbeat]);
  useEffect(() => { void loadAutomations(); }, [loadAutomations]);

  const reloadStatus = useCallback(async () => {
    try { setStatus(await agentsApi.status(base, agentId)); } catch { /* 列表状态兜底 */ }
  }, [base, agentId]);
  useEffect(() => { void reloadStatus(); }, [reloadStatus]);

  const save = async () => {
    setBusy(true);
    const ok = await useAtlasStore.getState().setAgentHeartbeat(agentId, {
      enabled: form.enabled,
      interval_minutes: Math.max(1, Math.floor(Number(form.interval_minutes) || 30)),
      active_hours: form.active_hours.trim(),
      prompt: form.prompt,
      delivery: form.delivery.trim() || 'owner',
      isolated_session: form.isolated_session,
    });
    setBusy(false);
    onToast(ok ? '心跳配置已保存' : '没有保存成功');
  };

  // 心跳的「动作」来自自动化引擎：payload.kind == heartbeat 且归这个 agent 的条目。
  const heartbeatJobs = automations.filter((item) => item.payload?.kind === 'heartbeat' && item.payload?.agent_id === agentId);
  const nextCheck = heartbeatJobs.map((item) => item.next_run_at).filter(Boolean).sort()[0];
  const lastCheck = heartbeatJobs.map((item) => item.last_run_at).filter(Boolean).sort().at(-1);

  return <div className="grid max-w-[620px] gap-4">
    <div className="flex flex-wrap items-center gap-x-5 gap-y-2 rounded-xl bg-sunken px-4 py-3 text-[12.5px] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">
      <span className="flex items-center gap-1.5"><HeartPulse size={14} className={form.enabled ? 'text-brand' : 'text-fg-3'} />
        {form.enabled ? '心跳已开启' : '心跳未开启'}</span>
      <span>最后活动：{agent.agent?.last_activity_at ? relativeTime(agent.agent.last_activity_at) : '还没有'}</span>
      <span>上次检查：{lastCheck ? relativeTime(lastCheck) : '—'}</span>
      <span>下次检查：{nextCheck ? relativeTime(nextCheck) : '—'}</span>
      {status?.error && <span className="w-full text-danger">上次出错：{status.error}</span>}
      <Button size="sm" variant="ghost" onClick={() => void reloadStatus()} aria-label="刷新状态">刷新</Button>
    </div>
    <label className="flex items-center gap-2.5 text-[13px] text-fg-2">
      <input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />
      开启心跳：它每隔一段时间自己醒来检查一次
    </label>
    <div className="grid grid-cols-2 gap-3">
      <label className="grid gap-1 text-[13px] text-fg-2">间隔（分钟）
        <input type="number" min={1} max={1440} value={form.interval_minutes}
          onChange={(event) => setForm({ ...form, interval_minutes: Number(event.target.value) })} className={field} />
      </label>
      <label className="grid gap-1 text-[13px] text-fg-2">活跃时间（留空 = 全天）
        <input value={form.active_hours} onChange={(event) => setForm({ ...form, active_hours: event.target.value })}
          placeholder="09:00-23:00" className={cn(field, 'font-mono text-[12.5px]')} />
      </label>
    </div>
    <label className="grid gap-1 text-[13px] text-fg-2">检查指令（它醒来时问自己什么）
      <textarea rows={3} value={form.prompt} onChange={(event) => setForm({ ...form, prompt: event.target.value })}
        placeholder="检查收件箱和任务列表，有要我的事就整理出来" className={cn(fieldArea, 'resize-y leading-[1.6]')} />
    </label>
    <div className="grid grid-cols-2 gap-3">
      <label className="grid gap-1 text-[13px] text-fg-2">检查结果投递
        <select value={form.delivery === 'owner' || form.delivery === 'none' || !form.delivery ? form.delivery : 'custom'}
          onChange={(event) => setForm({ ...form, delivery: event.target.value === 'custom' ? 'channel:' : event.target.value })} className={field}>
          <option value="owner">发给我（默认会话）</option>
          <option value="none">不打扰我</option>
          <option value="custom">发到渠道…</option>
        </select>
      </label>
      {form.delivery !== 'owner' && form.delivery !== 'none' && <label className="grid gap-1 text-[13px] text-fg-2">渠道:目标
        <input value={form.delivery} onChange={(event) => setForm({ ...form, delivery: event.target.value })}
          placeholder="telegram:123456789" className={cn(field, 'font-mono text-[12.5px]')} />
      </label>}
    </div>
    <label className="flex items-center gap-2.5 text-[13px] text-fg-2">
      <input type="checkbox" checked={form.isolated_session} onChange={(event) => setForm({ ...form, isolated_session: event.target.checked })} />
      每次心跳用独立会话（不弄脏聊天上下文）
    </label>
    <div><Button variant="primary" disabled={busy} onClick={() => void save()}>{busy ? '保存中…' : '保存心跳'}</Button></div>
  </div>;
}
