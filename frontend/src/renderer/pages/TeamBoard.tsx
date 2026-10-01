import { useCallback, useEffect, useMemo, useState, type DragEvent, type FormEvent, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, CircleCheck, CircleDashed, CircleDot, Clock3, ExternalLink, Link2, MoreHorizontal, OctagonPause, Plus, RefreshCw, SearchCheck } from 'lucide-react';
import type { AgentTypeInfo, KanbanBoard, KanbanStatus, KanbanTask } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from '../ui/Menu';
import { cn } from '../ui/cn';

const COLUMNS: Array<{ id: KanbanStatus; title: string; icon: ReactNode }> = [
  { id: 'todo', title: '待办', icon: <CircleDashed size={14} className="text-fg-3" /> },
  { id: 'running', title: '进行中', icon: <CircleDot size={14} className="text-brand" /> },
  { id: 'blocked', title: '受阻', icon: <OctagonPause size={14} className="text-danger" /> },
  { id: 'review', title: '待验收', icon: <SearchCheck size={14} className="text-fg-2" /> },
  { id: 'done', title: '完成', icon: <CircleCheck size={14} className="text-ok" /> },
];
const AGENT_LABEL: Record<string, string> = { explore: '探索', researcher: '调研', plan: '规划', oracle: '深度分析', verifier: '验收', general: '通用' };
const agentLabel = (name: string) => AGENT_LABEL[name] ?? name;
const LAST_BOARD = 'atlas.kanban.board';
const field = 'rounded-[9px] bg-sunken px-2.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

/**
 * The team board: tasks a coordinator split up for workers, with who owns each, what it waits on,
 * and what it produced. Agents move cards themselves; you can too, by dragging or from the card menu.
 */
export default function TeamBoard({ workspace, onOpenRun, canOpenRun }: {
  workspace: string; onOpenRun: (runId: string) => void; canOpenRun: (runId: string) => boolean;
}) {
  const [boards, setBoards] = useState<KanbanBoard[] | null>(null);
  const [boardId, setBoardId] = useState(() => { try { return localStorage.getItem(LAST_BOARD) ?? ''; } catch { return ''; } });
  const [tasks, setTasks] = useState<KanbanTask[]>([]);
  const [types, setTypes] = useState<AgentTypeInfo[]>([]);
  const [error, setError] = useState('');
  const [collapsed, setCollapsed] = useState<KanbanStatus[]>([]);
  const [dragging, setDragging] = useState<string | null>(null);
  const [newBoard, setNewBoard] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const say = (exc: unknown) => setError(exc instanceof Error ? exc.message : String(exc));
  const loadBoards = useCallback(() => backend.getKanbanBoards().then((list) => {
    setBoards(list);
    setBoardId((current) => list.some((board) => board.id === current) ? current : list[0]?.id ?? '');
  }).catch(say), []);
  const loadTasks = useCallback(() => {
    if (!boardId) { setTasks([]); return Promise.resolve(); }
    return backend.getKanbanTasks(boardId).then(setTasks).catch(say);
  }, [boardId]);

  useEffect(() => { void loadBoards(); void backend.getAgentTypes(workspace || null).then(setTypes).catch(() => setTypes([])); }, [loadBoards, workspace]);
  useEffect(() => { try { if (boardId) localStorage.setItem(LAST_BOARD, boardId); } catch { /* per-viewer convenience only */ } void loadTasks(); }, [boardId, loadTasks]);
  // Agents update cards while they work; keep the board fresh while it's on screen.
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void loadTasks(); }, 5000);
    return () => window.clearInterval(timer);
  }, [loadTasks]);

  const byId = useMemo(() => new Map(tasks.map((task) => [task.id, task])), [tasks]);
  const move = async (task: KanbanTask, status: KanbanStatus) => {
    if (task.status === status) return;
    setTasks((current) => current.map((item) => item.id === task.id ? { ...item, status } : item));
    try { await backend.updateKanbanTask(boardId, task.id, { status }); setError(''); }
    catch (exc) {
      const text = exc instanceof Error ? exc.message : String(exc);
      setError(/dependencies must be done/.test(text) ? `「${task.title}」依赖的任务还没完成，不能开始。` : text);
    }
    await loadTasks();
  };
  const createBoard = async (event: FormEvent) => {
    event.preventDefault();
    if (!newBoard?.trim()) return;
    try { const board = await backend.createKanbanBoard(newBoard.trim()); setNewBoard(null); await loadBoards(); setBoardId(board.id); }
    catch (exc) { say(exc); }
  };
  const drop = (status: KanbanStatus) => (event: DragEvent) => {
    event.preventDefault();
    const task = byId.get(event.dataTransfer.getData('text/plain'));
    setDragging(null);
    if (task) void move(task, status);
  };

  if (boards === null) return <p className="py-10 text-center text-[13px] text-fg-3">正在读取看板…</p>;
  if (!boards.length) return <div className="mx-auto mt-10 max-w-[440px] rounded-2xl card-surface p-6 text-center">
    <h2 className="m-0 font-serif text-[18px] font-semibold text-heading">还没有团队看板</h2>
    <p className="mt-2 mb-4 text-[13px] leading-[1.7] text-fg-3">大一点的活可以让 Atlas 拆成几张卡片放到看板上，再派子 Agent 认领、做完交给验收。你也可以先建一个看板自己排任务。</p>
    <form onSubmit={(event) => void createBoard(event)} className="flex gap-2">
      <input value={newBoard ?? ''} onChange={(event) => setNewBoard(event.target.value)} placeholder="看板名称，比如「重构登录」" aria-label="看板名称" className={cn(field, 'h-9 flex-1')} />
      <button disabled={!newBoard?.trim()} className="primary-fill h-9 shrink-0 rounded-[9px] px-3 text-[13px] disabled:opacity-50">新建</button>
    </form>
    {error && <p role="alert" className="mt-3 mb-0 text-[12.5px] text-danger">{error}</p>}
  </div>;

  const done = tasks.filter((task) => task.status === 'done').length;
  return <div className="flex min-h-0 flex-col gap-3">
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex min-w-0 flex-wrap gap-1" role="tablist" aria-label="看板">
        {boards.slice(0, 6).map((board) => <button key={board.id} role="tab" aria-selected={board.id === boardId} onClick={() => setBoardId(board.id)}
          className={cn('h-8 max-w-[200px] truncate rounded-full px-3 text-[13px]', board.id === boardId ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover')}>{board.name}</button>)}
        {boards.length > 6 && <Menu>
          <MenuTrigger asChild><button className="h-8 rounded-full px-2.5 text-[13px] text-fg-2 hover:bg-hover">更多 {boards.length - 6} 个</button></MenuTrigger>
          <MenuContent>{boards.slice(6).map((board) => <MenuItem key={board.id} checked={board.id === boardId} onSelect={() => setBoardId(board.id)}>{board.name}</MenuItem>)}</MenuContent>
        </Menu>}
      </div>
      {newBoard === null
        ? <button onClick={() => setNewBoard('')} className="inline-flex h-8 items-center gap-1 rounded-full px-2.5 text-[13px] text-fg-3 hover:bg-hover hover:text-fg"><Plus size={14} />新看板</button>
        : <form onSubmit={(event) => void createBoard(event)} className="flex items-center gap-1.5">
          <input autoFocus value={newBoard} onChange={(event) => setNewBoard(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setNewBoard(null); }} placeholder="看板名称" aria-label="新看板名称" className={cn(field, 'h-8 w-44')} />
          <button disabled={!newBoard.trim()} className="h-8 rounded-[9px] px-2.5 text-[13px] text-fg-2 hover:bg-hover disabled:opacity-40">建</button>
        </form>}
      <span className="flex-1" />
      {tasks.length > 0 && <span className="text-[12.5px] tabular-nums text-fg-3">完成 {done}/{tasks.length}</span>}
      <button aria-label="刷新看板" onClick={() => void loadTasks()} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><RefreshCw size={14} /></button>
    </div>
    {error && <p role="alert" className="m-0 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}<button onClick={() => setError('')} className="ml-auto text-fg-3 hover:text-fg">知道了</button></p>}
    <div className="flex min-h-[420px] gap-3 overflow-x-auto pb-3">
      {COLUMNS.map((column) => {
        const items = tasks.filter((task) => task.status === column.id);
        // Empty columns fold to a narrow strip on their own; any column can be folded by hand.
        const folded = collapsed.includes(column.id) || (!items.length && column.id !== 'todo' && !dragging);
        const toggle = () => setCollapsed((current) => current.includes(column.id) ? current.filter((id) => id !== column.id) : [...current, column.id]);
        if (folded) return <button key={column.id} onClick={toggle} onDragOver={(event) => event.preventDefault()} onDrop={drop(column.id)}
          aria-label={`展开「${column.title}」，${items.length} 张`} title={`展开「${column.title}」`}
          className="flex w-10 shrink-0 flex-col items-center gap-2 rounded-2xl bg-sunken py-3 text-fg-3 hover:text-fg">
          {column.icon}<span className="text-[12.5px] [writing-mode:vertical-rl]">{column.title}</span>
          <span className="rounded-full bg-hover px-1.5 text-[11px] tabular-nums">{items.length}</span>
        </button>;
        return <section key={column.id} aria-label={column.title} onDragOver={(event) => event.preventDefault()} onDrop={drop(column.id)}
          className={cn('flex min-w-[230px] flex-1 flex-col rounded-2xl bg-sunken p-2.5 transition-shadow', dragging && 'shadow-[inset_0_0_0_1.5px_var(--brand-soft)]')}>
          <header className="mb-2 flex items-center gap-2 px-1">
            {column.icon}<b className="text-[13px] font-semibold text-fg">{column.title}</b>
            <span className="rounded-full bg-hover px-1.5 text-[11.5px] tabular-nums text-fg-3">{items.length}</span>
            <button onClick={toggle} aria-label={`收起「${column.title}」`} className="ml-auto grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ChevronLeft size={14} /></button>
          </header>
          <div className="grid content-start gap-2">
            {items.map((task) => <TaskCard key={task.id} task={task} byId={byId} onMove={(status) => void move(task, status)}
              onDragStart={() => setDragging(task.id)} onDragEnd={() => setDragging(null)}
              onOpenRun={task.run_id && canOpenRun(task.run_id) ? () => onOpenRun(task.run_id) : undefined} />)}
            {column.id === 'todo' && (adding
              ? <NewTask boardId={boardId} tasks={tasks} types={types} onDone={() => { setAdding(false); void loadTasks(); }} onError={say} />
              : <button onClick={() => setAdding(true)} className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[12.5px] text-fg-3 hover:bg-hover hover:text-fg"><Plus size={13} />添加任务</button>)}
            {!items.length && column.id !== 'todo' && <p className="m-0 px-1 text-[12px] text-fg-3">拖到这里</p>}
          </div>
        </section>;
      })}
    </div>
  </div>;
}

function TaskCard({ task, byId, onMove, onDragStart, onDragEnd, onOpenRun }: {
  task: KanbanTask; byId: Map<string, KanbanTask>; onMove: (status: KanbanStatus) => void;
  onDragStart: () => void; onDragEnd: () => void; onOpenRun?: () => void;
}) {
  const [showOutput, setShowOutput] = useState(false);
  const deps = task.dependencies.map((id) => byId.get(id)).filter(Boolean) as KanbanTask[];
  const waiting = deps.filter((dep) => dep.status !== 'done');
  return <article draggable onDragStart={(event) => { event.dataTransfer.setData('text/plain', task.id); event.dataTransfer.effectAllowed = 'move'; onDragStart(); }} onDragEnd={onDragEnd}
    className="group cursor-grab rounded-xl card-surface px-3 py-2.5 active:cursor-grabbing">
    <div className="flex items-start gap-1.5">
      <b className="min-w-0 flex-1 text-[13px] font-medium leading-[1.5] text-fg">{task.title}</b>
      <Menu>
        <MenuTrigger asChild><button aria-label={`「${task.title}」的操作`} className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 opacity-0 hover:bg-hover hover:text-fg group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100"><MoreHorizontal size={14} /></button></MenuTrigger>
        <MenuContent align="end">
          <MenuLabel>移到</MenuLabel>
          {COLUMNS.map((column) => <MenuItem key={column.id} checked={task.status === column.id} onSelect={() => onMove(column.id)}>{column.icon}{column.title}</MenuItem>)}
        </MenuContent>
      </Menu>
    </div>
    {task.description && <p className="m-0 mt-0.5 line-clamp-2 text-[12px] leading-[1.6] text-fg-3" title={task.description}>{task.description}</p>}
    <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px]">
      {task.assignee && <span className="rounded-full bg-brand-soft px-1.5 py-px text-fg">{agentLabel(task.assignee)}</span>}
      {deps.length > 0 && <span className={cn('inline-flex items-center gap-0.5', waiting.length ? 'text-fg-2' : 'text-fg-3')}
        title={deps.map((dep) => `${dep.status === 'done' ? '✓' : '·'} ${dep.title}`).join('\n')}>
        <Link2 size={11} />{waiting.length ? `等 ${waiting.length} 项` : '依赖已完成'}</span>}
      {task.updated_at && <span className="inline-flex items-center gap-0.5 text-fg-3"><Clock3 size={11} />{task.updated_at.slice(5, 16).replace('T', ' ')}</span>}
      <span className="flex-1" />
      {task.output && <button onClick={() => setShowOutput((value) => !value)} aria-expanded={showOutput} className="inline-flex items-center gap-0.5 text-fg-3 hover:text-fg">
        产出<ChevronRight size={11} className={cn('transition-transform', showOutput && 'rotate-90')} /></button>}
      {onOpenRun && <button onClick={onOpenRun} className="inline-flex items-center gap-0.5 text-fg-3 hover:text-fg"><ExternalLink size={11} />看运行</button>}
    </div>
    {showOutput && <p className="anim-fade m-0 mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-sunken px-2.5 py-1.5 text-[12px] leading-[1.6] text-fg-2">{task.output}</p>}
  </article>;
}

function NewTask({ boardId, tasks, types, onDone, onError }: {
  boardId: string; tasks: KanbanTask[]; types: AgentTypeInfo[]; onDone: () => void; onError: (exc: unknown) => void;
}) {
  const [form, setForm] = useState({ title: '', description: '', assignee: '', dependencies: [] as string[] });
  const [showDeps, setShowDeps] = useState(false);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try { await backend.createKanbanTask(boardId, { ...form, title: form.title.trim() }); onDone(); }
    catch (exc) { onError(exc); setBusy(false); }
  };
  return <form onSubmit={(event) => void submit(event)} className="grid gap-1.5 rounded-xl card-surface p-2.5">
    <input autoFocus required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="要做什么" aria-label="任务标题" className={cn(field, 'h-8')} />
    <textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={2} placeholder="说明、完成标准（可选）" aria-label="任务说明" className={cn(field, 'py-1.5 text-[12.5px]')} />
    <select value={form.assignee} onChange={(event) => setForm({ ...form, assignee: event.target.value })} aria-label="负责的 Agent" className={cn(field, 'h-8 text-[12.5px]')}>
      <option value="">还没指派</option>
      {types.map((type) => <option key={type.name} value={type.name}>{agentLabel(type.name)}{AGENT_LABEL[type.name] ? '' : ` · ${type.description.slice(0, 20)}`}</option>)}
    </select>
    {tasks.length > 0 && <div>
      <button type="button" onClick={() => setShowDeps((value) => !value)} aria-expanded={showDeps} className="inline-flex items-center gap-1 text-[12px] text-fg-3 hover:text-fg">
        <ChevronRight size={12} className={cn('transition-transform', showDeps && 'rotate-90')} />依赖{form.dependencies.length ? `（${form.dependencies.length}）` : ''}</button>
      {showDeps && <div className="mt-1 grid max-h-32 gap-0.5 overflow-auto">
        {tasks.map((task) => <label key={task.id} className="flex items-center gap-1.5 text-[12px] text-fg-2">
          <input type="checkbox" checked={form.dependencies.includes(task.id)} onChange={(event) => setForm({ ...form, dependencies: event.target.checked ? [...form.dependencies, task.id] : form.dependencies.filter((id) => id !== task.id) })} />
          <span className="truncate">{task.title}</span>
        </label>)}
      </div>}
    </div>}
    <div className="flex justify-end gap-1.5">
      <button type="button" onClick={onDone} className="h-7 rounded-lg px-2 text-[12.5px] text-fg-3 hover:text-fg">取消</button>
      <button disabled={busy || !form.title.trim()} className="primary-fill h-7 rounded-lg px-2.5 text-[12.5px] disabled:opacity-50">添加</button>
    </div>
  </form>;
}
