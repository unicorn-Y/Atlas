// 当前对话的独立会话条：它开出的子会话（状态、打开、停止、开始提议），
// 以及它自己是谁开出来的。顺带把后端已在跑、界面还没接上的运行接上直播
// （子会话、回报唤醒、自动化、渠道消息都会在后端直接开跑）。
import { useEffect, useState } from 'react';
import { ArrowUpRight, CornerLeftUp, Play, Square, SplitSquareHorizontal, X } from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { cn } from '../../ui/cn';
import { openConversationById, sessionsApi, sessionsChanged, STATUS_LABEL, type LinkedSession } from './sessionsApi';

const LIVE = new Set(['starting', 'running', 'waiting']);

export default function LinkedSessions({ conversationId }: { conversationId: string }) {
  const [children, setChildren] = useState<LinkedSession[]>([]);
  const [self, setSelf] = useState<LinkedSession | null>(null);
  const [busy, setBusy] = useState('');
  const parentTitle = useAtlasStore((state) => self?.parent_conversation_id
    ? state.conversations.find((item) => item.id === self.parent_conversation_id)?.title ?? '主会话' : '');

  useEffect(() => {
    setChildren([]); setSelf(null);
    if (!conversationId) return undefined;
    let stale = false;
    const refresh = async () => {
      try {
        const all = (await sessionsApi.list()).sessions;
        if (stale) return;
        setChildren(all.filter((item) => item.parent_conversation_id === conversationId && !['dismissed', 'expired'].includes(item.status)));
        setSelf(all.find((item) => item.conversation_id === conversationId) ?? null);
      } catch { /* backend without sessions support */ }
      try {
        const active = await sessionsApi.activeRun(conversationId);
        if (!stale && active.run) useAtlasStore.getState().attachRun(conversationId, active.run.run_id);
      } catch { /* ignore */ }
    };
    void refresh();
    const timer = window.setInterval(() => { if (document.visibilityState !== 'hidden') void refresh(); }, 3000);
    window.addEventListener('atlas:linked-sessions', refresh);
    return () => { stale = true; window.clearInterval(timer); window.removeEventListener('atlas:linked-sessions', refresh); };
  }, [conversationId]);

  const act = async (id: string, fn: () => Promise<unknown>) => {
    setBusy(id);
    try { await fn(); sessionsChanged(); } catch { /* card shows the state on next refresh */ } finally { setBusy(''); }
  };

  if (!children.length && !self) return null;
  return <div className="mb-2 flex flex-col gap-1" aria-label="独立会话">
    {self?.parent_conversation_id && <button className="flex w-fit items-center gap-1.5 rounded-lg px-2 py-1 text-[12px] text-fg-3 hover:bg-hover hover:text-fg"
      onClick={() => void openConversationById(self.parent_conversation_id!)}>
      <CornerLeftUp size={12} />这是「{parentTitle}」开出来的独立会话，停下时会自动回报 · 回到主会话
    </button>}
    {children.map((item) => <div key={item.session_id} className="flex min-w-0 items-center gap-2 rounded-lg bg-sunken px-2.5 py-1.5 text-[12.5px] shadow-[inset_0_0_0_1px_var(--line)]">
      <SplitSquareHorizontal size={13} className="shrink-0 text-brand" />
      <span className={cn('size-1.5 shrink-0 rounded-full', LIVE.has(item.status) ? 'animate-pulse bg-brand' : item.status === 'failed' ? 'bg-danger' : item.status === 'proposed' ? 'bg-brand-soft' : 'bg-ok')} />
      <span className="min-w-0 truncate text-fg" title={item.prompt}>{item.title}</span>
      <span className="shrink-0 text-fg-3">{item.waiting_for ? '等你确认' : STATUS_LABEL[item.status]}</span>
      <span className="flex-1" />
      {item.status === 'proposed' && <>
        <button disabled={busy === item.session_id} className="inline-flex items-center gap-1 text-brand hover:brightness-110" onClick={() => void act(item.session_id, () => sessionsApi.start(item.session_id))}><Play size={12} />开始</button>
        <button disabled={busy === item.session_id} aria-label="忽略提议" className="text-fg-3 hover:text-fg" onClick={() => void act(item.session_id, () => sessionsApi.dismiss(item.session_id))}><X size={13} /></button>
      </>}
      {LIVE.has(item.status) && <button disabled={busy === item.session_id} className="inline-flex items-center gap-1 text-fg-3 hover:text-danger" onClick={() => void act(item.session_id, () => sessionsApi.stop(item.session_id))}><Square size={11} />停止</button>}
      {item.conversation_id && <button className="inline-flex items-center gap-1 text-fg-2 hover:text-fg" onClick={() => void openConversationById(item.conversation_id!)}>打开<ArrowUpRight size={12} /></button>}
    </div>)}
  </div>;
}
