import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Archive, CircleAlert, CircleCheck, Clock3, FolderOpen, ListOrdered, LoaderCircle, MessageCircleQuestion, Plus, Square } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import type { AgentRun } from '../../types/runtime';
import type { QueuedMessage } from '../store/useAtlasStore';
import { relativeTime } from '../services/api';
import { cn } from '../ui/cn';
import { api } from '../services/api';

type Column = 'running' | 'attention' | 'queued' | 'done';

interface Card { conversation: ConversationSummary; run?: AgentRun; queued: number; unread: boolean }

const COLUMNS: Array<{ id: Column; title: string; hint: string; icon: ReactNode }> = [
  { id: 'running', title: '进行中', hint: 'Atlas 正在做', icon: <LoaderCircle size={15} className="spin text-brand" /> },
  { id: 'attention', title: '等你处理', hint: '要你确认、回答，或者出错了', icon: <MessageCircleQuestion size={15} className="text-danger" /> },
  { id: 'queued', title: '排队中', hint: '还有消息等着发', icon: <ListOrdered size={15} className="text-fg-2" /> },
  { id: 'done', title: '最近完成', hint: '做完了，或者最近动过', icon: <CircleCheck size={15} className="text-ok" /> },
];
const STATUS: Record<string, string> = { running: '正在处理', planning: '正在规划', waiting: '等你确认', paused: '已暂停', completed: '已完成', failed: '出错了', cancelled: '已停止' };

function columnOf(card: Card): Column {
  const status = card.run?.status;
  if (status === 'waiting' || status === 'failed' || status === 'paused') return 'attention';
  if (status === 'running' || status === 'planning') return 'running';
  if (card.queued) return 'queued';
  return 'done';
}

/** Every conversation at a glance, grouped by what it needs: the command centre for parallel work. */
export default function BoardPage({ conversations, runs, queue, unread, archived, onOpen, onStop, onArchive, apiBaseUrl }: {
  conversations: ConversationSummary[];
  runs: AgentRun[];
  queue: Record<string, QueuedMessage[]>;
  unread: string[];
  archived: string[];
  onOpen: (conversation: ConversationSummary) => void;
  onStop: (runId: string) => void;
  onArchive: (id: string) => void;
  apiBaseUrl: string;
}) {
  const latestRun = new Map<string, AgentRun>();
  for (const run of runs) latestRun.set(run.conversationId, run);
  const cards: Card[] = conversations.filter((conversation) => !archived.includes(conversation.id)).map((conversation) => ({
    conversation, run: latestRun.get(conversation.id), queued: queue[conversation.id]?.length ?? 0, unread: unread.includes(conversation.id),
  }));
  const grouped = new Map<Column, Card[]>(COLUMNS.map((column) => [column.id, []]));
  for (const card of cards) grouped.get(columnOf(card))!.push(card);
  grouped.set('done', grouped.get('done')!.slice(0, 24));

  return <div className="screen page"><div className="page-inner" style={{ maxWidth: 'none' }}>
    <header className="page-head">
      <div><h1>任务看板</h1><p>所有对话按状态排好，同时跑几件事时从这里照看。</p></div>
    </header>
    <KanbanTasksPanel apiBaseUrl={apiBaseUrl} />
    <div className="grid min-h-0 gap-4 [grid-template-columns:repeat(4,minmax(220px,1fr))] overflow-x-auto pb-4">
      {COLUMNS.map((column) => {
        const items = grouped.get(column.id)!;
        return <section key={column.id} aria-label={column.title} className="flex min-h-[320px] min-w-0 flex-col rounded-2xl bg-sunken p-3">
          <header className="mb-3 flex items-center gap-2 px-1">
            {column.icon}<b className="text-[13.5px] font-semibold text-fg">{column.title}</b>
            <span className="rounded-full bg-hover px-1.5 text-[11.5px] tabular-nums text-fg-3">{items.length}</span>
          </header>
          <div className="grid gap-2">
            {items.map((card) => <BoardCard key={card.conversation.id} card={card} onOpen={onOpen} onStop={onStop} onArchive={onArchive} />)}
            {!items.length && <p className="m-0 px-1 text-[12.5px] leading-[1.6] text-fg-3">{column.hint}，现在没有。</p>}
          </div>
        </section>;
      })}
    </div>
  </div></div>;
}

type TaskCard = { id: string; title: string; description: string; assignee: string; dependencies: string[]; status: string; output: string; run_id: string };
const TASK_COLUMNS = ['todo', 'running', 'blocked', 'review', 'done'] as const;
const TASK_LABELS: Record<string, string> = { todo: '待办', running: '运行中', blocked: '受阻', review: '审核', done: '完成' };

function KanbanTasksPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [boards, setBoards] = useState<Array<{ id: string; name: string }>>([]);
  const [boardId, setBoardId] = useState('');
  const [tasks, setTasks] = useState<TaskCard[]>([]);
  const [profiles, setProfiles] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [assignee, setAssignee] = useState('');
  const [parent, setParent] = useState('');
  const [detail, setDetail] = useState<{ task: string; runs: Array<Record<string, unknown>> } | null>(null);
  const [dragging, setDragging] = useState('');
  const [error, setError] = useState('');
  const reloadTasks = async (id = boardId) => {
    if (!id) { setTasks([]); return; }
    const value = await api<{ tasks: TaskCard[] }>(apiBaseUrl, `/api/kanban/boards/${encodeURIComponent(id)}/tasks`);
    setTasks(value.tasks);
  };
  useEffect(() => {
    let live = true;
    void Promise.all([
      api<{ boards: Array<{ id: string; name: string }> }>(apiBaseUrl, '/api/kanban/boards'),
      api<{ profiles: string[] }>(apiBaseUrl, '/api/kanban/profiles'),
    ]).then(([boardData, profileData]) => { if (live) { setBoards(boardData.boards); setBoardId(boardData.boards[0]?.id ?? ''); setProfiles(profileData.profiles); } })
      .catch((cause) => { if (live) setError(cause instanceof Error ? cause.message : String(cause)); });
    return () => { live = false; };
  }, [apiBaseUrl]);
  useEffect(() => { void reloadTasks(boardId).catch((cause) => setError(String(cause))); }, [boardId]);
  const createBoard = async () => {
    const name = window.prompt('看板名称'); if (!name?.trim()) return;
    const value = await api<{ id: string; name: string }>(apiBaseUrl, '/api/kanban/boards', { method: 'POST', json: { name } });
    setBoards((current) => [...current, value]); setBoardId(value.id);
  };
  const createTask = async (event: FormEvent) => {
    event.preventDefault(); if (!boardId || !title.trim()) return;
    await api<TaskCard>(apiBaseUrl, `/api/kanban/boards/${encodeURIComponent(boardId)}/tasks`, {
      method: 'POST', json: { title, assignee, ...(parent ? { parent, dependencies: [parent] } : {}) },
    });
    setTitle(''); setParent(''); await reloadTasks();
  };
  const move = async (task: TaskCard, status: string) => {
    try { await api(apiBaseUrl, `/api/kanban/boards/${encodeURIComponent(boardId)}/tasks/${encodeURIComponent(task.id)}`, { method: 'PATCH', json: { status } }); await reloadTasks(); setError(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  };
  const showDetail = async (task: TaskCard) => {
    const value = await api<{ runs: Array<Record<string, unknown>> }>(apiBaseUrl, `/api/kanban/boards/${encodeURIComponent(boardId)}/tasks/${encodeURIComponent(task.id)}/runs`);
    setDetail({ task: task.id, runs: value.runs });
  };
  return <section className="mb-5 rounded-2xl border border-line bg-surface p-4">
    <header className="flex flex-wrap items-center gap-3"><div className="mr-auto"><h2 className="m-0 text-[16px] font-semibold">档案协作任务</h2><p className="m-0 text-[12px] text-fg-3">依赖就绪后会自动派发，最多同时运行 3 项。</p></div>
      <select aria-label="协作看板" value={boardId} onChange={(event) => setBoardId(event.target.value)} className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]">{boards.map((board) => <option key={board.id} value={board.id}>{board.name}</option>)}</select>
      <button type="button" className="btn ghost" onClick={() => void createBoard()}><Plus size={14} />新建看板</button>
    </header>
    {error && <p role="alert" className="mt-2 text-[12px] text-danger">{error}</p>}
    {boardId && <form onSubmit={(event) => void createTask(event)} className="mt-3 flex flex-wrap gap-2">
      <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="任务名称" className="h-8 min-w-[180px] flex-1 rounded-md border border-line bg-surface px-2 text-[12px]" />
      <select aria-label="负责档案" value={assignee} onChange={(event) => setAssignee(event.target.value)} className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]"><option value="">选择档案</option>{profiles.map((profile) => <option key={profile}>{profile}</option>)}</select>
      <select aria-label="前置任务" value={parent} onChange={(event) => setParent(event.target.value)} className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]"><option value="">无依赖</option>{tasks.map((task) => <option key={task.id} value={task.id}>{task.title}</option>)}</select>
      <button className="btn primary" disabled={!title.trim()}><Plus size={14} />添加任务</button>
    </form>}
    {boardId && <div className="mt-3 grid min-w-[800px] grid-cols-5 gap-2 overflow-x-auto">
      {TASK_COLUMNS.map((status) => <section key={status} onDragOver={(event) => event.preventDefault()} onDrop={() => { const task = tasks.find((item) => item.id === dragging); if (task) void move(task, status); setDragging(''); }} className="min-h-36 rounded-xl bg-sunken p-2">
        <h3 className="mb-2 mt-0 text-[12px] font-semibold">{TASK_LABELS[status]} · {tasks.filter((task) => task.status === status).length}</h3>
        <div className="grid gap-1.5">{tasks.filter((task) => task.status === status).map((task) => <button key={task.id} draggable onDragStart={() => setDragging(task.id)} onClick={() => void showDetail(task)} className="rounded-lg border border-line bg-surface p-2 text-left text-[12px]">
          <b className="block">{task.title}</b><span className="text-fg-3">{task.assignee || '未分配'}{task.dependencies.length ? ` · 依赖 ${task.dependencies.length}` : ''}</span>
          {detail?.task === task.id && <span className="mt-1 block border-t border-line pt-1 text-fg-3">运行记录：{detail.runs.map((run) => String(run.status)).join('、') || '暂无'}{task.output ? `\n${task.output}` : ''}</span>}
        </button>)}</div>
      </section>)}
    </div>}
  </section>;
}

function BoardCard({ card, onOpen, onStop, onArchive }: { card: Card; onOpen: (conversation: ConversationSummary) => void; onStop: (runId: string) => void; onArchive: (id: string) => void }) {
  const { conversation, run } = card;
  const live = run && ['running', 'planning', 'waiting', 'paused'].includes(run.status);
  const lastStep = run ? [...run.events].reverse().find((event) => event.type === 'tool.started' || event.type === 'input.required' || event.type === 'run.plan.proposed' || event.type === 'approval.required') : undefined;
  const detail = lastStep?.type === 'input.required' ? `问你：${String(lastStep.data.question ?? '')}`
    : lastStep?.type === 'run.plan.proposed' ? '计划等你批准'
    : lastStep?.type === 'approval.required' ? '有一步等你确认'
    : run?.status === 'failed' ? String([...run.events].reverse().find((event) => event.type === 'run.failed')?.data.detail ?? '出错了')
    : lastStep ? `在用 ${String(lastStep.data.name ?? '工具')}` : '';
  const workspace = typeof conversation.workspace === 'string' ? conversation.workspace.split(/[\\/]/).filter(Boolean).pop() : '';
  return <div className="group rounded-xl card-surface">
    <button onClick={() => onOpen(conversation)} className="block w-full px-3 pt-2.5 pb-2 text-left">
      <span className="flex items-start gap-2">
        {card.unread && <i className="mt-[7px] size-1.5 shrink-0 rounded-full bg-ok" aria-label="有新结果" />}
        <b className="line-clamp-2 text-[13px] font-medium text-fg">{conversation.title}</b>
      </span>
      {detail && <span className={cn('mt-1 line-clamp-2 block text-[12px]', run?.status === 'failed' ? 'text-danger' : 'text-fg-3')}>{detail}</span>}
      <span className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-fg-3">
        {run && <span className={cn(run.status === 'failed' && 'text-danger')}>{run.status === 'failed' ? <CircleAlert size={11} className="mr-0.5 inline" /> : null}{STATUS[run.status] ?? run.status}</span>}
        {card.queued > 0 && <span>还有 {card.queued} 条待发</span>}
        {workspace && <span className="inline-flex items-center gap-0.5"><FolderOpen size={11} />{workspace}</span>}
        <span className="inline-flex items-center gap-0.5"><Clock3 size={11} />{relativeTime(run?.updatedAt ?? conversation.updated_at)}</span>
      </span>
    </button>
    <div className="flex justify-end gap-0.5 px-2 pb-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
      {live && run && <button aria-label="停止" onClick={() => onStop(run.id)} className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[12px] text-fg-3 hover:bg-hover hover:text-danger"><Square size={11} />停止</button>}
      {!live && <button aria-label="归档" onClick={() => onArchive(conversation.id)} className="inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[12px] text-fg-3 hover:bg-hover hover:text-fg"><Archive size={12} />归档</button>}
    </div>
  </div>;
}
