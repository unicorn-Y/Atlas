import { useCallback, useEffect, useState } from 'react';
import { Plus, Radio, Trash2 } from 'lucide-react';
import { agentsApi, channelsApi, type AgentChannelBinding } from '../../services/persistentApi';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { field } from './shared';
import type { PersistentAgentRecord } from '../../services/persistentApi';

/** Channels：这个 Agent 收得到消息的入站绑定（channel + target + 账号）。 */
export default function AgentChannelsTab({ apiBaseUrl, agent, onToast }: {
  apiBaseUrl: string; agent: PersistentAgentRecord; onToast: (text: string) => void;
}) {
  const [channels, setChannels] = useState<AgentChannelBinding[]>(agent.agent?.channels ?? []);
  const [gateway, setGateway] = useState<string[]>([]);
  const [form, setForm] = useState({ channel: '', target: '', account: '', mentionNames: '' });
  const [busy, setBusy] = useState(false);
  const base = apiBaseUrl;
  const agentId = agent.id;

  const reload = useCallback(async () => {
    try { setChannels((await agentsApi.listChannels(base, agentId)).channels); } catch { /* 详情由列表兜底 */ }
  }, [base, agentId]);
  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    let active = true;
    channelsApi.status(base).then((status) => {
      if (!active) return;
      const registered = status.channels.map((row) => row.name);
      setGateway(registered);
      setForm((current) => ({ ...current, channel: registered.includes(current.channel) ? current.channel : registered[0] ?? '' }));
    }).catch(() => {
      if (!active) return;
      setGateway([]);
      setForm((current) => ({ ...current, channel: '' }));
    });
    return () => { active = false; };
  }, [base]);

  const add = async () => {
    if (!form.channel || !gateway.includes(form.channel) || !form.target.trim()) return;
    setBusy(true);
    try {
      setChannels((await agentsApi.addChannel(base, agentId, {
        channel: form.channel, target: form.target.trim(), ...(form.account.trim() ? { account: form.account.trim() } : {}),
        ...(form.mentionNames.trim() ? { mention_names: form.mentionNames.split(',').map((name) => name.trim().replace(/^@/, '')).filter(Boolean) } : {}),
      })).channels);
      setForm({ ...form, target: '', account: '', mentionNames: '' });
      onToast('绑定已添加');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusy(false);
  };
  const remove = async (binding: AgentChannelBinding) => {
    setBusy(true);
    try {
      setChannels((await agentsApi.removeChannel(base, agentId, binding.channel, binding.target, binding.account)).channels);
      onToast('绑定已移除');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setBusy(false);
  };

  return <div className="grid max-w-[620px] gap-4">
    <p className="m-0 text-[12.5px] leading-[1.6] text-fg-3">
      绑定后，来自这个渠道 + 目标（群 / 聊天 ID）的消息会交给这个 Agent，而不是主 Atlas。渠道账号的密钥在「设置 → 渠道与 Gateway」里配。
    </p>
    <div className="grid gap-1.5">
      {channels.map((binding, index) => <div key={`${binding.channel}:${binding.target}:${index}`}
        className="flex items-center gap-2.5 rounded-xl bg-sunken px-3 py-2 text-[13px] shadow-[inset_0_0_0_1px_var(--line)]">
        <Radio size={14} className="shrink-0 text-brand" />
        <b className="shrink-0 font-medium text-fg">{binding.channel}</b>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg-2">{binding.target}</span>
        {!!binding.mention_names?.length && <span className="shrink-0 text-[11.5px] text-fg-3">@{binding.mention_names.join(' / @')}</span>}
        {binding.account && <span className="shrink-0 text-[11.5px] text-fg-3">账号 {binding.account}</span>}
        <Button size="icon-sm" variant="ghost" aria-label="移除绑定" disabled={busy} onClick={() => void remove(binding)}><Trash2 /></Button>
      </div>)}
      {!channels.length && <p className="text-[12.5px] text-fg-3">还没有绑定。请选择已注册渠道并填写目标 chat id。</p>}
    </div>
    <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); void add(); }}>
      <label className="grid gap-1 text-[12.5px] text-fg-2">渠道
        <select value={form.channel} disabled={!gateway.length} onChange={(event) => setForm({ ...form, channel: event.target.value })} className={cn(field, 'w-32')}>
          {!gateway.length && <option value="">暂无已注册渠道</option>}{gateway.map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <label className="grid min-w-[180px] flex-1 gap-1 text-[12.5px] text-fg-2">目标（chat id / 群 id）
        <input required value={form.target} onChange={(event) => setForm({ ...form, target: event.target.value })} placeholder="123456789" className={cn(field, 'font-mono text-[12.5px]')} />
      </label>
      <label className="grid gap-1 text-[12.5px] text-fg-2">账号（可选）
        <input value={form.account} onChange={(event) => setForm({ ...form, account: event.target.value })} className={cn(field, 'w-36 text-[12.5px]')} />
      </label>
      <label className="grid min-w-[180px] flex-1 gap-1 text-[12.5px] text-fg-2">群聊提及名（逗号分隔）
        <input value={form.mentionNames} onChange={(event) => setForm({ ...form, mentionNames: event.target.value })} placeholder={`@${agent.id}, ${agent.name}`} className={cn(field, 'text-[12.5px]')} />
      </label>
      <Button type="submit" variant="primary" disabled={busy || !form.channel || !gateway.includes(form.channel) || !form.target.trim()}><Plus />添加绑定</Button>
    </form>
  </div>;
}
