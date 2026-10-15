// 独立会话在主会话时间线里的卡片：提议（开始 / 在这里做 / 忽略）、已开始、回报。
// 交互照 Claude Desktop 的 start_session 提议卡与「New session / Do it here」二选一。
import { useState } from 'react';
import { ArrowUpRight, CircleCheck, GitBranch, Play, SplitSquareHorizontal, X } from 'lucide-react';
import type { AgentEvent } from '../../../types/runtime';
import { useAtlasStore } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { openConversationById, sessionsApi, sessionsChanged, STATUS_LABEL, type LinkedSession } from './sessionsApi';

export default function SessionEventCard({ event }: { event: AgentEvent }) {
  const kind = String(event.data.kind ?? '');
  const initial = event.data.session as LinkedSession | undefined;
  const [session, setSession] = useState<LinkedSession | undefined>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (kind === 'next_step') return <NextStepBox event={event} />;
  if (!session) return null;

  const act = async (fn: () => Promise<{ session: LinkedSession }>) => {
    setBusy(true); setError('');
    try { setSession((await fn()).session); sessionsChanged(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const doHere = async () => {
    await act(() => sessionsApi.dismiss(session.session_id, 'do_here'));
    void useAtlasStore.getState().sendMessage(session.prompt);
  };
  const open = () => { if (session.conversation_id) void openConversationById(session.conversation_id); };

  if (kind === 'proposed' || (kind === '' && session.status === 'proposed')) {
    const pending = session.status === 'proposed';
    return <div className="my-4 rounded-xl bg-sunken px-4 py-3 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="独立会话提议">
      <div className="flex items-center gap-2 text-[12px] text-fg-3">
        <SplitSquareHorizontal size={13} className="text-brand" />
        {session.initiation === 'offer' ? '要不要单独开个会话来做？' : 'Atlas 建议开一个独立会话'}
        {!pending && <span className="ml-auto">{STATUS_LABEL[session.status]}</span>}
      </div>
      <div className="mt-1.5 text-[14px] font-medium text-fg">{session.title}</div>
      <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-[12.5px] text-fg-2">{session.prompt}</p>
      {session.use_worktree && <div className="mt-1.5 flex items-center gap-1 text-[11.5px] text-fg-3"><GitBranch size={12} />会在独立的 git 工作目录里改代码</div>}
      {pending && <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="primary" disabled={busy} onClick={() => void act(() => sessionsApi.start(session.session_id))}><Play />开新会话</Button>
        {session.initiation === 'offer' && <Button size="sm" disabled={busy} onClick={() => void doHere()}>就在这里做</Button>}
        <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => sessionsApi.dismiss(session.session_id))}><X />忽略</Button>
      </div>}
      {!pending && session.conversation_id && <div className="mt-2"><Button size="sm" variant="ghost" onClick={open}><ArrowUpRight />打开会话</Button></div>}
      {error && <div role="alert" className="mt-2 text-[12px] text-danger">{error}</div>}
    </div>;
  }

  if (kind === 'report') {
    const report = String(event.data.report ?? session.last_report ?? '');
    return <div className="my-3 rounded-xl px-4 py-2.5 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="独立会话回报">
      <div className="flex items-center gap-2 text-[12px] text-fg-3">
        <SplitSquareHorizontal size={13} className="text-brand" />
        独立会话「{session.title}」{session.status === 'failed' ? '失败了' : session.status === 'stopped' ? '被停止了' : '回报'}
        <button className="ml-auto inline-flex items-center gap-1 text-fg-2 hover:text-fg" onClick={open}>打开<ArrowUpRight size={12} /></button>
      </div>
      {report && <p className="mt-1 line-clamp-6 whitespace-pre-wrap text-[12.5px] text-fg-2">{report}</p>}
    </div>;
  }

  const text = kind === 'started' ? '已开始独立会话' : kind === 'dismissed' ? '已忽略提议' : kind === 'failed' ? '独立会话没能开始' : '独立会话';
  return <div className="my-3 flex items-center gap-2 text-[12.5px] text-fg-2">
    <SplitSquareHorizontal size={13} className="shrink-0 text-brand" />
    <span className="truncate">{text}「{session.title}」{session.worktree_branch ? ` · ${session.worktree_branch}` : ''}{session.error && kind === 'failed' ? `：${session.error}` : ''}</span>
    {session.conversation_id && kind !== 'dismissed' && <button className="inline-flex shrink-0 items-center gap-1 text-fg-3 hover:text-fg" onClick={open}>打开<ArrowUpRight size={12} /></button>}
  </div>;
}

/** Claude Desktop「下一步」框：回顾 + 一个问题 + 一两个按钮；按钮把话发回当前对话。 */
function NextStepBox({ event }: { event: AgentEvent }) {
  const recap = String(event.data.recap ?? '');
  const ask = String(event.data.ask ?? '');
  const actions = Array.isArray(event.data.actions) ? event.data.actions as Array<{ label: string; message?: string }> : [];
  const [chosen, setChosen] = useState('');
  const answered = useAtlasStore((state) => {
    const run = state.runs.find((item) => item.id === event.runId);
    return Boolean(run && state.runs.some((item) => item.conversationId === run.conversationId && item.startedAt > run.startedAt));
  });
  return <div className="my-4 rounded-xl bg-sunken px-4 py-3 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="下一步">
    <div className="flex items-start gap-2 text-[13px] text-fg-2"><CircleCheck size={14} className="mt-0.5 shrink-0 text-ok" /><span className="whitespace-pre-wrap">{recap}</span></div>
    {ask && actions.length > 0 && <div className="mt-2.5">
      <div className="text-[13px] font-medium text-fg">{ask}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {actions.map((action, index) => <Button key={action.label} size="sm" variant={index === 0 ? 'primary' : 'secondary'}
          disabled={Boolean(chosen) || answered}
          onClick={() => { setChosen(action.label); void useAtlasStore.getState().sendMessage(action.message || action.label); }}>
          {action.label}</Button>)}
      </div>
    </div>}
  </div>;
}
