import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import type { AgentRun, AgentEvent } from '../../../types/runtime';
import { api } from '../../services/api';
import { usageSummary } from '../../components/runInsights';

const RUNNING = new Set(['running', 'planning', 'paused', 'waiting']);
const elapsed = (start: string, end = new Date().toISOString()) => {
  const seconds = Math.max(0, Math.floor((Date.parse(end) - Date.parse(start)) / 1000));
  return seconds < 60 ? `${seconds} 秒` : seconds < 3600 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分`;
};
const str = (value: unknown) => typeof value === 'string' ? value : '';

const RUN_STATUS_LABELS: Record<string, string> = { idle: '空闲', planning: '规划中', running: '运行中', waiting: '等待确认', paused: '已暂停', completed: '已完成', failed: '出错', cancelled: '已停止' };

export default function AgentsOverview({ runs, conversations, apiBaseUrl, onOpen, onStop, roster }: {
  runs: AgentRun[]; conversations: ConversationSummary[]; apiBaseUrl: string;
  onOpen: (conversation: ConversationSummary) => void; onStop: (runId: string) => void; roster: ReactNode;
}) {
  const [tab, setTab] = useState<'overview' | 'roster'>('overview');
  const [subtasks, setSubtasks] = useState<Record<string, PersistedSubtask[]>>({});
  const [notice, setNotice] = useState('');
  const runByConversation = new Map(runs.map((run) => [run.conversationId, run]));
  useEffect(() => {
    let current = true;
    void Promise.all(runs.map(async (run) => {
      try {
        const result = await api<{ items: PersistedSubtask[] }>(apiBaseUrl, `/api/runs/${encodeURIComponent(run.id)}/subtasks`);
        return [run.id, result.items] as const;
      } catch { return [run.id, []] as const; }
    })).then((rows) => { if (current) setSubtasks(Object.fromEntries(rows)); });
    return () => { current = false; };
  }, [runs, apiBaseUrl]);
  const recent = useMemo(() => [...conversations].sort((a, b) => Date.parse(b.updated_at ?? '') - Date.parse(a.updated_at ?? '')).slice(0, 40), [conversations]);
  const refreshSubtasks = async (runId: string) => { const result = await api<{ items: PersistedSubtask[] }>(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/subtasks`); setSubtasks((current) => ({ ...current, [runId]: result.items })); };
  const resumeChild = async (runId: string, childId: string) => {
    try { await api(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/subtasks/${encodeURIComponent(childId)}/resume`, { method: 'POST' }); await refreshSubtasks(runId); setNotice('已从原生子会话恢复任务'); }
    catch (error) { setNotice(error instanceof Error ? error.message : '恢复失败'); }
  };
  const closeChild = async (runId: string, childId: string) => {
    try { await api(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/subtasks/${encodeURIComponent(childId)}/close`, { method: 'POST' }); await refreshSubtasks(runId); setNotice('原生子 Agent 已关闭；会话记录已保留'); }
    catch (error) { setNotice(error instanceof Error ? error.message : '关闭失败'); }
  };
  if (tab === 'roster') return <div className="flex h-full min-h-0 flex-col"><Header tab={tab} setTab={setTab} />{roster}</div>;
  return <div className="flex h-full min-h-0 flex-col overflow-auto bg-panel p-5 text-fg">
    <Header tab={tab} setTab={setTab} />
    <div className="mx-auto w-full max-w-5xl py-5">
      <h1 className="m-0 text-[20px] font-semibold text-heading">会话与 Agent 总览</h1><p className="mt-1 text-[12.5px] text-fg-3">运行中、等待确认和最近更新的会话；活动会话约每次运行事件刷新。</p>
      {notice && <p role="status" className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-fg-2">{notice}</p>}
      <div className="grid gap-2">{recent.map((conversation) => {
        const run = runByConversation.get(conversation.id);
        const active = run && RUNNING.has(run.status);
        const usage = run ? usageSummary(run.events) : null;
        const children = run ? mergePersistedChildRows(childRows(run.events), subtasks[run.id] ?? []) : [];
        return <section key={conversation.id} className="rounded-xl border border-line bg-surface p-3">
          <div className="flex items-center gap-2"><span className={`size-2 rounded-full ${active ? 'bg-brand' : run?.status === 'failed' ? 'bg-danger' : 'bg-ok'}`} /><button type="button" onClick={() => onOpen(conversation)} className="min-w-0 flex-1 truncate text-left text-[13px] font-medium text-fg hover:underline">{conversation.title || '新对话'}</button><span className="text-[11px] text-fg-3">{run ? (RUN_STATUS_LABELS[run.status] ?? run.status) : '最近会话'}{run && active ? ` · ${elapsed(run.startedAt)}` : ''}</span>{run && active && <button type="button" onClick={() => onStop(run.id)} className="rounded-md px-2 py-1 text-[11px] text-danger hover:bg-danger/10">中断</button>}</div>
          {usage && <p className="mb-0 mt-1 text-[11px] text-fg-3">Token：输入 {usage.input.toLocaleString()} · 输出 {usage.output.toLocaleString()}</p>}
          {children.length > 0 && <div className="mt-2 grid gap-1 border-t border-line pt-2">{children.map((child) => <div key={`${run!.id}:${child.id}`} className="flex items-center gap-2 rounded-lg bg-sunken px-2.5 py-2 text-[11.5px]">
            <span className="min-w-0 flex-1 truncate text-fg">{child.name}</span><span className="max-w-[35%] truncate text-fg-3">{child.progress}</span><span className="shrink-0 text-fg-3">{child.duration}</span>{child.tokens > 0 && <span className="shrink-0 text-fg-3">{child.tokens.toLocaleString()} tokens</span>}
            {child.status === 'completed' && <span title="已完成的终态不能重新运行；保留的子会话可打开查看。" className="text-fg-3">已完成 · 不支持恢复</span>}
            {child.backend === 'atlas' && child.sessionId && (child.status === 'closed' || child.status === 'cancelled' || child.status === 'failed')
              ? <button type="button" onClick={() => void resumeChild(run!.id, child.id)} className="rounded px-2 py-1 text-brand hover:bg-hover">恢复</button>
              : child.backend === 'atlas' && (child.status === 'running' || child.status === 'closing') && <button type="button" onClick={() => void closeChild(run!.id, child.id)} className="rounded px-2 py-1 text-fg-3 hover:bg-hover">关闭子 Agent</button>}
            {child.backend === 'atlas' && ['closed', 'cancelled', 'failed'].includes(child.status) && !child.sessionId && <span title="子会话恢复点尚未记录。" className="text-fg-3">无可用恢复点</span>}
            {child.backend !== 'atlas' && <span title="当前执行后端未提供原生子会话生命周期接口。" className="text-fg-3">此后端不支持关闭/恢复</span>}
          </div>)}</div>}
        </section>;
      })}</div>
    </div>
  </div>;
}

function Header({ tab, setTab }: { tab: 'overview' | 'roster'; setTab: (tab: 'overview' | 'roster') => void }) {
  return <div className="flex shrink-0 items-center gap-2 border-b border-line px-5 py-2"><button type="button" aria-pressed={tab === 'overview'} onClick={() => setTab('overview')} className={`rounded-lg px-3 py-1.5 text-[12px] ${tab === 'overview' ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover'}`}>总览</button><button type="button" aria-pressed={tab === 'roster'} onClick={() => setTab('roster')} className={`rounded-lg px-3 py-1.5 text-[12px] ${tab === 'roster' ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover'}`}>常驻 Agent</button></div>;
}

type ChildRow = { id: string; name: string; progress: string; duration: string; tokens: number; status: string; backend: string; sessionId?: string; started: string };
type PersistedSubtask = { subtask_id: string; status: string; goal: string; backend: string; session_id?: string; workspace?: string };

function mergePersistedChildRows(rows: ChildRow[], saved: PersistedSubtask[]): ChildRow[] {
  const merged = new Map(rows.map((row) => [row.id, row]));
  for (const item of saved) {
    const row = merged.get(item.subtask_id) ?? { id: item.subtask_id, name: item.goal || `子 Agent ${item.subtask_id.slice(0, 8)}`, progress: '', duration: '', tokens: 0, status: item.status, backend: item.backend, sessionId: item.session_id || undefined, started: '' };
    row.status = item.status;
    row.backend = item.backend;
    if (item.session_id) row.sessionId = item.session_id;
    merged.set(item.subtask_id, row);
  }
  return [...merged.values()];
}

function childRows(events: AgentEvent[]) {
  const rows = new Map<string, { id: string; name: string; progress: string; duration: string; tokens: number; status: string; backend: string; sessionId?: string; started: string }>();
  for (const event of events) {
    const data = event.data;
    const id = str(data.subtask_id);
    if (!id) continue;
    if (event.type === 'subtask.started') rows.set(id, { id, name: str(data.title) || str(data.goal) || `子 Agent ${id.slice(0, 8)}`, progress: '启动中', duration: '0 秒', tokens: 0, status: 'running', backend: str(data.backend) || 'atlas', sessionId: str(data.session_id) || undefined, started: event.timestamp });
    const row = rows.get(id);
    if (!row) continue;
    if (event.type === 'subtask.progress' || event.type === 'subtask.output') row.progress = str(data.text) || row.progress;
    if (event.type === 'subtask.completed') { row.status = str(data.status) || 'completed'; row.progress = str(data.summary) || row.progress; row.duration = typeof data.duration_ms === 'number' ? `${Math.round(data.duration_ms / 1000)} 秒` : elapsed(row.started, event.timestamp); }
    if (event.type === 'subtask.completed' && data.tokens && typeof data.tokens === 'object') {
      const tokenData = data.tokens as Record<string, unknown>;
      row.tokens = Number(tokenData.total ?? (Number(tokenData.input ?? 0) + Number(tokenData.output ?? 0))) || 0;
    }
    if (event.type === 'run.usage' && str(data.subtask_id) === id) row.tokens += Number(data.input_tokens ?? 0) + Number(data.output_tokens ?? 0);
    if (!row.sessionId && str(data.session_id)) row.sessionId = str(data.session_id);
  }
  return [...rows.values()];
}
