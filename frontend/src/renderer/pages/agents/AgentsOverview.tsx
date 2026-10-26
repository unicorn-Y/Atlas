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
  const [onlineSubtasks, setOnlineSubtasks] = useState<PersistedSubtask[]>([]);
  const [notice, setNotice] = useState('');
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'active' | 'waiting' | 'ended'>('all');
  const [page, setPage] = useState(0);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState('');
  const [pickerIndex, setPickerIndex] = useState(0);
  const runByConversation = new Map(runs.map((run) => [run.conversationId, run]));
  const runIds = runs.map((run) => run.id).join('|');
  useEffect(() => {
    let current = true;
    void Promise.all(runs.map(async (run) => {
      try {
        const result = await api<{ items: PersistedSubtask[] }>(apiBaseUrl, `/api/runs/${encodeURIComponent(run.id)}/subtasks`);
        return [run.id, result.items] as const;
      } catch { return [run.id, []] as const; }
    })).then((rows) => { if (current) setSubtasks(Object.fromEntries(rows)); });
    return () => { current = false; };
  }, [runIds, apiBaseUrl]);
  useEffect(() => {
    let current = true;
    const refresh = () => void api<{ items: PersistedSubtask[] }>(apiBaseUrl, '/api/subtasks/online')
      .then((result) => { if (current) setOnlineSubtasks(result.items); })
      .catch(() => { if (current) setOnlineSubtasks([]); });
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { current = false; window.clearInterval(timer); };
  }, [apiBaseUrl]);
  useEffect(() => {
    const open = () => { setPickerOpen(true); setPickerQuery(''); setPickerIndex(0); };
    const keydown = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.key.toLowerCase() === 'a' && !event.altKey) {
        event.preventDefault(); open();
      }
    };
    window.addEventListener('atlas:open-agent-picker', open);
    window.addEventListener('keydown', keydown);
    return () => { window.removeEventListener('atlas:open-agent-picker', open); window.removeEventListener('keydown', keydown); };
  }, []);
  const refreshSubtasks = async (runId: string) => { const result = await api<{ items: PersistedSubtask[] }>(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/subtasks`); setSubtasks((current) => ({ ...current, [runId]: result.items })); };
  const resumeChild = async (runId: string, childId: string) => {
    try { await api(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/subtasks/${encodeURIComponent(childId)}/resume`, { method: 'POST' }); await refreshSubtasks(runId); setNotice('已从原生子会话恢复任务'); }
    catch (error) { setNotice(error instanceof Error ? error.message : '恢复失败'); }
  };
  const closeChild = async (runId: string, childId: string) => {
    try { await api(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/subtasks/${encodeURIComponent(childId)}/close`, { method: 'POST' }); await refreshSubtasks(runId); setNotice('原生子 Agent 已关闭；会话记录已保留'); }
    catch (error) { setNotice(error instanceof Error ? error.message : '关闭失败'); }
  };
  const ordered = useMemo(() => [...conversations].sort((a, b) => Date.parse(b.updated_at ?? '') - Date.parse(a.updated_at ?? '')), [conversations]);
  const matching = ordered.filter((conversation) => {
    const run = runByConversation.get(conversation.id);
    const active = Boolean(run && RUNNING.has(run.status));
    const waiting = run?.status === 'waiting';
    if (statusFilter === 'active' && !active) return false;
    if (statusFilter === 'waiting' && !waiting) return false;
    if (statusFilter === 'ended' && active) return false;
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return true;
    const children = run ? mergePersistedChildRows(childRows(run.events), [...(subtasks[run.id] ?? []), ...onlineSubtasks.filter((item) => item.parent_run_id === run.id)]) : [];
    return `${conversation.title} ${conversation.id} ${conversation.workspace ?? ''} ${children.map((item) => item.name).join(' ')}`.toLocaleLowerCase().includes(needle);
  });
  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(matching.length / pageSize));
  const visible = matching.slice(page * pageSize, (page + 1) * pageSize);
  const pickerItems = useMemo(() => {
    const sessions = conversations.map((conversation) => ({ conversation, label: conversation.title || '新对话', detail: conversation.workspace || conversation.id }));
    const children = onlineSubtasks.filter((child) => child.session_id).map((child) => ({
      conversation: conversations.find((item) => item.id === child.session_id) ?? { id: child.session_id!, title: child.goal || `子 Agent ${child.subtask_id.slice(0, 8)}`, workspace: child.workspace },
      label: `子 Agent · ${child.goal || child.subtask_id}`, detail: `${child.status} · ${child.parent_run_id}`,
    }));
    const byId = new Map([...sessions, ...children].map((item) => [item.conversation.id, item]));
    const needle = pickerQuery.trim().toLocaleLowerCase();
    return [...byId.values()].filter((item) => !needle || `${item.label} ${item.conversation.id} ${item.detail}`.toLocaleLowerCase().includes(needle));
  }, [conversations, onlineSubtasks, pickerQuery]);
  const selectPickerItem = (index: number) => {
    const item = pickerItems[index];
    if (!item) return;
    onOpen(item.conversation);
    setPickerOpen(false);
  };
  useEffect(() => {
    if (!pickerOpen) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        setPickerIndex((index) => Math.max(0, Math.min(pickerItems.length - 1, index + (event.key === 'ArrowDown' ? 1 : -1))));
      } else if (event.key === 'Enter') {
        event.preventDefault(); selectPickerItem(pickerIndex);
      } else if (event.key === 'Escape') setPickerOpen(false);
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, [pickerOpen, pickerIndex, pickerItems]);
  useEffect(() => { setPage(0); }, [query, statusFilter]);
  if (tab === 'roster') return <div className="flex h-full min-h-0 flex-col"><Header tab={tab} setTab={setTab} />{roster}</div>;
  return <div className="flex h-full min-h-0 flex-col overflow-auto bg-panel p-5 text-fg">
    <Header tab={tab} setTab={setTab} />
    <div className="mx-auto w-full max-w-5xl py-5">
      <div className="flex flex-wrap items-start gap-3"><div className="min-w-0 flex-1"><h1 className="m-0 text-[20px] font-semibold text-heading">会话与 Agent 总览</h1><p className="mt-1 text-[12.5px] text-fg-3">全部 {conversations.length} 个会话 · {onlineSubtasks.length} 个在线子 Agent；用 Ctrl+Shift+A 打开快捷导航。</p></div><button type="button" onClick={() => { setPickerOpen(true); setPickerQuery(''); setPickerIndex(0); }} className="btn ghost">Agent 快捷导航</button></div>
      {notice && <p role="status" className="rounded-lg bg-sunken px-3 py-2 text-[12px] text-fg-2">{notice}</p>}
      <div className="my-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px]"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索标题、会话 ID、工作区或子 Agent" aria-label="搜索会话总览" className="input h-9" /><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)} aria-label="按运行状态筛选会话" className="input h-9"><option value="all">全部状态</option><option value="active">活动中</option><option value="waiting">等待确认</option><option value="ended">已结束</option></select></div>
      {onlineSubtasks.length > 0 && <section aria-label="全部在线子 Agent" className="mb-3 rounded-xl border border-line bg-surface p-3"><h2 className="m-0 mb-2 text-[12px] font-medium text-heading">在线子 Agent（{onlineSubtasks.length}）</h2><div className="grid gap-1 sm:grid-cols-2">{onlineSubtasks.map((child) => { const childSession = child.session_id ? conversations.find((item) => item.id === child.session_id) ?? { id: child.session_id, title: child.goal || `子 Agent ${child.subtask_id.slice(0, 8)}`, workspace: child.workspace } : null; return <div key={`${child.parent_run_id}:${child.subtask_id}`} className="flex items-center gap-2 rounded-lg bg-sunken px-2.5 py-2 text-[11.5px]"><span className="size-2 shrink-0 animate-pulse rounded-full bg-brand" /><span className="min-w-0 flex-1 truncate text-fg">{child.goal || child.subtask_id}</span><span className="shrink-0 text-fg-3">{child.status === 'closing' ? '正在关闭' : '运行中'}</span>{childSession && <button type="button" onClick={() => onOpen(childSession)} className="shrink-0 rounded px-2 py-1 text-brand hover:bg-hover">打开</button>}</div>; })}</div></section>}
      <div className="grid gap-2">{visible.map((conversation) => {
        const run = runByConversation.get(conversation.id);
        const active = run && RUNNING.has(run.status);
        const usage = run ? usageSummary(run.events) : null;
        const children = run ? mergePersistedChildRows(childRows(run.events), [...(subtasks[run.id] ?? []), ...onlineSubtasks.filter((item) => item.parent_run_id === run.id)]) : [];
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
      })}{!visible.length && <p role="status" className="rounded-lg bg-sunken p-4 text-center text-[12px] text-fg-3">没有符合筛选条件的会话。</p>}</div>
      <div className="mt-3 flex items-center justify-center gap-3 text-[12px] text-fg-3"><button type="button" className="btn ghost" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>上一页</button><span>第 {page + 1} / {pageCount} 页 · {matching.length} 个会话</span><button type="button" className="btn ghost" disabled={page + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>下一页</button></div>
    </div>
    {pickerOpen && <div role="dialog" aria-modal="true" aria-label="Agent 快捷导航" className="fixed inset-0 z-[70] grid place-items-start justify-center bg-black/40 p-4 pt-[12vh]" onMouseDown={(event) => { if (event.target === event.currentTarget) setPickerOpen(false); }}><section className="card-surface flex max-h-[72vh] w-full max-w-xl flex-col gap-2 rounded-2xl p-4 shadow-xl"><header className="flex items-center gap-2"><h2 className="m-0 flex-1 text-[15px] font-semibold text-heading">Agent 快捷导航</h2><span className="text-[11px] text-fg-3">↑ ↓ 选择 · Enter 打开 · Esc 关闭</span></header><input autoFocus value={pickerQuery} onChange={(event) => { setPickerQuery(event.target.value); setPickerIndex(0); }} placeholder="搜索会话或在线子 Agent" aria-label="搜索 Agent 导航项" className="input h-9" /><div role="listbox" className="min-h-0 overflow-auto rounded-lg bg-sunken p-1">{pickerItems.map((item, index) => <button key={item.conversation.id} type="button" role="option" aria-selected={index === pickerIndex} onMouseEnter={() => setPickerIndex(index)} onClick={() => selectPickerItem(index)} className={`flex w-full items-center gap-2 rounded-md px-3 py-2 text-left ${index === pickerIndex ? 'bg-brand-soft' : 'hover:bg-hover'}`}><span className="min-w-0 flex-1 truncate text-[12.5px] text-fg">{item.label}</span><span className="max-w-[45%] truncate text-[10.5px] text-fg-3">{item.detail}</span></button>)}{!pickerItems.length && <p role="status" className="m-0 p-4 text-center text-[12px] text-fg-3">没有匹配项目。</p>}</div></section></div>}
  </div>;
}

function Header({ tab, setTab }: { tab: 'overview' | 'roster'; setTab: (tab: 'overview' | 'roster') => void }) {
  return <div className="flex shrink-0 items-center gap-2 border-b border-line px-5 py-2"><button type="button" aria-pressed={tab === 'overview'} onClick={() => setTab('overview')} className={`rounded-lg px-3 py-1.5 text-[12px] ${tab === 'overview' ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover'}`}>总览</button><button type="button" aria-pressed={tab === 'roster'} onClick={() => setTab('roster')} className={`rounded-lg px-3 py-1.5 text-[12px] ${tab === 'roster' ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover'}`}>常驻 Agent</button></div>;
}

type ChildRow = { id: string; name: string; progress: string; duration: string; tokens: number; status: string; backend: string; sessionId?: string; started: string };
type PersistedSubtask = { subtask_id: string; parent_run_id?: string; status: string; goal: string; backend: string; session_id?: string; workspace?: string };

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
