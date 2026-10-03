import { useEffect, useState } from 'react';
import { Hand, MonitorUp, RefreshCw, ShieldAlert, Square } from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import type { HandoffCard, TakeoverSnapshot } from '../../services/persistentApi';

const STATE_META: Record<TakeoverSnapshot['state'], { label: string; className: string; hint: string }> = {
  FREE: { label: '空闲', className: 'bg-ok-soft text-fg', hint: '没有人也没有 Agent 在操作这台电脑' },
  HUMAN: { label: '人类在控制', className: 'bg-brand-soft text-fg', hint: '你正在用键鼠操作；Agent 的电脑工具会被拦下' },
  AGENT: { label: 'Agent 在控制', className: 'bg-danger-soft text-danger', hint: 'Agent 正在这台电脑上干活；你动之前先「接管」' },
};

const ts = (value?: number) => value ? new Date(value < 1e12 ? value * 1000 : value).toLocaleTimeString() : '';
const age = (value?: number) => {
  if (!value) return '';
  const seconds = Math.max(0, Date.now() / 1000 - (value < 1e12 ? value : value / 1000));
  return seconds < 60 ? `${Math.round(seconds)} 秒前` : seconds < 3600 ? `${Math.round(seconds / 60)} 分钟前` : `${Math.round(seconds / 3600)} 小时前`;
};

/**
 * 控制权（takeover）公共块：FREE/HUMAN/AGENT 状态机 + human_take/agent_take/release
 * + 活动流 + handoff 卡片（done / give_up）。Devices 页和 Agent 详情「电脑」tab 共用。
 */
export default function TakeoverSection({ selfDeviceId, agentId, onToast, compact = false }: {
  selfDeviceId: string;
  /** 「让 Agent 干」时代表哪个 Agent（Agent 详情页传入自己）。 */
  agentId?: string;
  onToast: (text: string) => void;
  compact?: boolean;
}) {
  const devices = useAtlasStore((state) => state.devices);
  const takeover = useAtlasStore((state) => state.takeover);
  const activity = useAtlasStore((state) => state.deviceActivity);
  const cards = useAtlasStore((state) => state.handoffCards);
  const takeoverAction = useAtlasStore((state) => state.takeoverAction);
  const loadTakeoverContext = useAtlasStore((state) => state.loadTakeoverContext);
  const handoffAction = useAtlasStore((state) => state.handoffAction);
  const agents = useAtlasStore((state) => state.agents);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');
  const [newCard, setNewCard] = useState('');
  const [pickAgent, setPickAgent] = useState(agentId ?? '');

  useEffect(() => { void loadTakeoverContext(); }, [loadTakeoverContext]);
  useEffect(() => { if (agentId) setPickAgent(agentId); }, [agentId]);

  const act = async (action: 'human_take' | 'agent_take' | 'release') => {
    setBusy(true);
    // 释放 AGENT 控制权时后端要求携带持有者的 agent_id；其余动作带当前选中的 Agent。
    const agent = action === 'human_take' ? undefined
      : action === 'release'
        ? (takeover?.state === 'AGENT' ? takeover?.holder || pickAgent || undefined : undefined)
        : pickAgent || undefined;
    const ok = await takeoverAction(action, { agentId: agent, note });
    setBusy(false);
    onToast(ok ? '控制权已变更' : useAtlasStore.getState().devicesError || '控制权操作失败');
  };
  const resolve = async (card: HandoffCard, action: 'done' | 'give_up') => {
    setBusy(true);
    const ok = await handoffAction(action, { cardId: card.card_id });
    setBusy(false);
    onToast(ok ? action === 'done' ? '卡片已办结' : '已放弃，Agent 会换个办法' : '操作失败');
  };

  const state = takeover?.state ?? 'FREE';
  const meta = STATE_META[state];
  const pending = cards.filter((card) => String(card.status).toUpperCase() === 'PENDING');
  const deviceName = (id: string) => devices.find((device) => device.id === id)?.display_name ?? id;

  return <section aria-label="电脑控制权" className="grid gap-3">
    <div className={cn('flex flex-wrap items-center gap-3 rounded-[14px] px-4 py-3.5', meta.className)}>
      {state === 'AGENT' ? <MonitorUp size={18} /> : state === 'HUMAN' ? <Hand size={18} /> : <ShieldAlert size={18} />}
      <div className="min-w-0">
        <b className="block text-[14px] font-semibold">{meta.label}</b>
        <small className="block text-[12px] opacity-80">{meta.hint}</small>
      </div>
      <span className="flex-1" />
      <div className="flex flex-wrap items-center gap-2">
        {state !== 'HUMAN' && <Button size="sm" variant="secondary" disabled={busy} onClick={() => void act('human_take')}>我接管</Button>}
        {state !== 'AGENT' && <Button size="sm" variant="secondary" disabled={busy || (state === 'FREE' && !pickAgent)} onClick={() => void act('agent_take')}>交给 Agent</Button>}
        {state !== 'FREE' && <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act('release')}><Square size={13} />释放</Button>}
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 text-[12px] text-fg-3">
      <span>设备：{takeover?.device_id ? deviceName(takeover.device_id) : selfDeviceId || '本机'}</span>
      {takeover?.holder && <span>持有者：{takeover.holder === 'user' ? '你' : takeover.holder}</span>}
      {takeover?.since_ts ? <span>自 {ts(takeover.since_ts)}（{age(takeover.since_ts)}）</span> : null}
      <Button size="sm" variant="ghost" aria-label="刷新控制权" onClick={() => void loadTakeoverContext()}><RefreshCw size={13} />刷新</Button>
      {state !== 'AGENT' && !agentId && agents.filter((item) => item.kind === 'persistent').length > 0 && <label className="flex items-center gap-1.5">
        交给
        <select value={pickAgent} onChange={(event) => setPickAgent(event.target.value)}
          className="h-7 rounded-lg bg-sunken px-2 text-[12px] text-fg shadow-[inset_0_0_0_1px_var(--line)] outline-none">
          <option value="">选 Agent…</option>
          {agents.filter((item) => item.kind === 'persistent').map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>}
      <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="备注（可选）"
        className="h-7 min-w-0 flex-1 rounded-lg bg-sunken px-2 text-[12px] text-fg shadow-[inset_0_0_0_1px_var(--line)] outline-none" />
    </div>

    {pending.length > 0 && <div className="grid gap-2" aria-label="待办交接卡片">
      {pending.map((card) => <div key={card.card_id} className="flex flex-wrap items-center gap-2.5 rounded-xl bg-brand-soft px-3.5 py-2.5">
        <ShieldAlert size={15} className="shrink-0 text-brand" />
        <span className="min-w-0 flex-1 text-[13px] leading-[1.55] text-fg">
          {card.note || '（没有说明）'}
          <small className="block text-[11.5px] text-fg-3">{card.created_by ? `${card.created_by} · ` : ''}{age(card.created_ts)}留下</small>
        </span>
        <Button size="sm" variant="primary" disabled={busy} onClick={() => void resolve(card, 'done')}>办好了</Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void resolve(card, 'give_up')}>办不了，放弃</Button>
      </div>)}
    </div>}
    {!compact && <form className="flex items-center gap-2 px-1" onSubmit={(event) => {
      event.preventDefault();
      const text = newCard.trim();
      if (!text) return;
      setNewCard('');
      void handoffAction('open', { note: text }).then((ok) => onToast(ok ? '已留卡片给 Agent' : '卡片创建失败'));
    }}>
      <input value={newCard} onChange={(event) => setNewCard(event.target.value)} placeholder="给 Agent 留张卡片：回来后要先办的事…"
        className="h-9 min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[13px] text-fg shadow-[inset_0_0_0_1px_var(--line)] outline-none focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <Button type="submit" variant="secondary" disabled={!newCard.trim() || busy}>留卡片</Button>
    </form>}

    {!compact && <div aria-label="控制权动态" className="max-h-52 overflow-auto rounded-xl bg-sunken px-3.5 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]">
      {[...activity].reverse().slice(0, 30).map((event, index) => <p key={index} className="m-0 flex gap-2 py-0.5 text-[12px] text-fg-3">
        <span className="shrink-0 tabular-nums">{ts(event.ts)}</span>
        <span className="min-w-0 flex-1 truncate">{event.event}{event.actor ? ` · ${event.actor === 'user' ? '你' : event.actor}` : ''}{event.detail ? ` · ${event.detail}` : ''}</span>
      </p>)}
      {!activity.length && <p className="m-0 py-1 text-[12px] text-fg-3">还没有动态。</p>}
    </div>}
  </section>;
}
