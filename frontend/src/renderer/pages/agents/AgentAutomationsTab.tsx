import { useEffect, useState } from 'react';
import { ExternalLink, HeartPulse, LoaderCircle, Pause, Play, Zap } from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { relativeTime } from '../../services/api';
import { Button } from '../../ui/Button';
import { describeAutomation } from '../automations/describe';
import type { PersistentAgentRecord } from '../../services/persistentApi';

/** Automations：owner_agent_id 过滤出的该 Agent 的自动化（心跳条目只读）。 */
export default function AgentAutomationsTab({ agent, onToast }: {
  agent: PersistentAgentRecord; onToast: (text: string) => void;
}) {
  const automations = useAtlasStore((state) => state.automations);
  const loading = useAtlasStore((state) => state.automationsLoading);
  const loadAutomations = useAtlasStore((state) => state.loadAutomations);
  const runAutomationNow = useAtlasStore((state) => state.runAutomationNow);
  const pauseAutomation = useAtlasStore((state) => state.pauseAutomation);
  const resumeAutomation = useAtlasStore((state) => state.resumeAutomation);
  useEffect(() => { void loadAutomations(); }, [loadAutomations]);

  const mine = automations.filter((item) => item.owner_agent_id === agent.id || (item.payload?.kind === 'heartbeat' && item.payload?.agent_id === agent.id));
  const [busyId, setBusyId] = useState('');
  const act = async (id: string, action: () => Promise<unknown>, done: string) => {
    setBusyId(id);
    await action();
    setBusyId('');
    onToast(useAtlasStore.getState().automationsError || done);
  };

  if (loading && !mine.length) return <p className="flex items-center gap-2 py-6 text-[13px] text-fg-3"><LoaderCircle size={15} className="spin" />正在读取自动化…</p>;

  return <div className="grid max-w-[680px] gap-3">
    {mine.map((item) => {
      const heartbeat = item.payload?.kind === 'heartbeat';
      const paused = !item.enabled || Boolean(item.paused_reason);
      return <article key={item.id} className="rounded-xl bg-sunken px-4 py-3 shadow-[inset_0_0_0_1px_var(--line)]">
        <header className="flex flex-wrap items-center gap-2">
          {heartbeat ? <HeartPulse size={14} className="text-brand" aria-label="心跳" /> : <Zap size={14} className="text-fg-3" />}
          <b className="text-[13.5px] text-fg">{item.name}</b>
          {heartbeat && <span className="rounded-full bg-brand-soft px-2 py-0.5 text-[11px] text-fg">心跳 · 只读</span>}
          {paused && <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] text-fg-3">已暂停{item.paused_reason ? `：${item.paused_reason}` : ''}</span>}
          <span className="flex-1" />
          {!heartbeat && <>
            <Button size="icon-sm" variant="ghost" aria-label="立即运行" disabled={busyId === item.id} onClick={() => void act(item.id, () => runAutomationNow(item.id), '已触发一次')}><Play /></Button>
            <Button size="icon-sm" variant="ghost" aria-label={paused ? '恢复' : '暂停'} disabled={busyId === item.id}
              onClick={() => void act(item.id, () => paused ? resumeAutomation(item.id) : pauseAutomation(item.id), paused ? '已恢复' : '已暂停')}>
              {paused ? <Play /> : <Pause />}
            </Button>
          </>}
        </header>
        <p className="mb-1 mt-1.5 text-[12.5px] leading-[1.6] text-fg-2">{describeAutomation(item)}</p>
        <p className="m-0 text-[11.5px] text-fg-3">
          {item.trigger.kind !== 'event' && item.trigger.kind !== 'webhook' && <>下次：{item.next_run_at ? relativeTime(item.next_run_at) : '未排期'} · </>}
          上次：{item.last_run_at ? relativeTime(item.last_run_at) : '还没跑过'}
          {Boolean(item.consecutive_errors) && <span className="text-danger"> · 连续出错 {item.consecutive_errors} 次</span>}
        </p>
      </article>;
    })}
    {!mine.length && <div className="empty py-10"><Zap size={20} /><b>这个 Agent 还没有自动化</b>心跳开启后这里会出现一条「心跳」；定时任务去「自动化」页新建。</div>}
    <p className="m-0 flex items-center gap-1 text-[12px] text-fg-3">
      <ExternalLink size={12} />在「自动化」页可以新建、编辑和看运行历史（owner 选这个 Agent）。
    </p>
  </div>;
}
