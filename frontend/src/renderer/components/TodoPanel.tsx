import { useEffect, useRef, useState, type KeyboardEvent } from 'react';
import { Check, ChevronDown, GripVertical, ListChecks, LoaderCircle, Plus, RotateCcw, Send, Trash2, X } from 'lucide-react';
import { cn } from '../ui/cn';
import { Tip } from '../ui/Tooltip';
import type { TodoItem, TodoStatus } from './runInsights';

const COLLAPSE_KEY = 'atlas.todoPanel.collapsed';
const readCollapsed = () => { try { return localStorage.getItem(COLLAPSE_KEY) === '1'; } catch { return false; } };
const writeCollapsed = (value: boolean) => { try { localStorage.setItem(COLLAPSE_KEY, value ? '1' : '0'); } catch { /* storage unavailable */ } };

/** Click cycles a todo through 待做 → 进行中 → 完成 → 待做. */
const NEXT_STATUS: Record<TodoStatus, TodoStatus> = { pending: 'in_progress', in_progress: 'completed', completed: 'pending', cancelled: 'pending' };
const STATUS_LABEL: Record<TodoStatus, string> = { pending: '待做', in_progress: '进行中', completed: '已完成', cancelled: '已取消' };

function StatusDot({ status, live }: { status: TodoStatus; live: boolean }) {
  if (status === 'completed') return <span className="grid size-[17px] place-items-center rounded-full bg-ok text-white"><Check size={11} strokeWidth={3} /></span>;
  if (status === 'in_progress') return <span className="relative grid size-[17px] place-items-center rounded-full shadow-[inset_0_0_0_1.5px_var(--brand)]">
    <i className={cn('size-[7px] rounded-full bg-brand', live && 'animate-pulse')} />
  </span>;
  if (status === 'cancelled') return <span className="grid size-[17px] place-items-center rounded-full text-fg-3 shadow-[inset_0_0_0_1.5px_var(--line-strong)]"><X size={10} strokeWidth={2.5} /></span>;
  return <span className="block size-[17px] rounded-full shadow-[inset_0_0_0_1.5px_var(--line-strong)] transition-shadow group-hover/dot:shadow-[inset_0_0_0_1.5px_var(--brand)]" />;
}

interface TodoPanelProps {
  todos: TodoItem[];
  /** Changes whenever the Agent writes a new list; a clean draft follows it. */
  revisionKey: string;
  running: boolean;
  onSubmit: (todos: TodoItem[]) => boolean;
}

/** The Agent's todo list, docked above the composer: foldable, and every item can be ticked, renamed, reordered or removed. */
export default function TodoPanel({ todos, revisionKey, running, onSubmit }: TodoPanelProps) {
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [draft, setDraft] = useState<TodoItem[]>(todos);
  const [dirty, setDirty] = useState(false);
  const [sent, setSent] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [adding, setAdding] = useState('');
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const addRef = useRef<HTMLInputElement>(null);

  // A new list from the Agent replaces the draft unless the user is in the middle of editing it.
  useEffect(() => {
    if (dirty) return;
    setDraft(todos);
    setSent(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [revisionKey]);

  const list = dirty ? draft : todos;
  const done = list.filter((item) => item.status === 'completed').length;
  const countable = list.filter((item) => item.status !== 'cancelled').length;
  const current = list.find((item) => item.status === 'in_progress') ?? list.find((item) => item.status === 'pending');
  const percent = countable ? done / countable * 100 : 0;

  const change = (next: TodoItem[]) => { setDraft(next); setDirty(true); setSent(false); };
  const toggleCollapsed = () => setCollapsed((value) => { writeCollapsed(!value); return !value; });
  const patch = (id: string, fields: Partial<TodoItem>) => change(list.map((item) => item.id === id ? { ...item, ...fields } : item));
  const remove = (id: string) => change(list.filter((item) => item.id !== id && item.parent !== id));
  const commitEdit = () => {
    if (editing) {
      const text = editText.trim();
      if (text && text !== list.find((item) => item.id === editing)?.text) patch(editing, { text });
    }
    setEditing(null);
  };
  const add = () => {
    const text = adding.trim();
    if (!text) return;
    const used = new Set(list.map((item) => item.id));
    let n = list.length + 1;
    while (used.has(String(n))) n += 1;
    change([...list, { id: String(n), text, status: 'pending' }]);
    setAdding('');
    addRef.current?.focus();
  };
  const move = (from: string, to: string) => {
    if (from === to) return;
    const next = [...list];
    const source = next.findIndex((item) => item.id === from);
    const [moved] = next.splice(source, 1);
    next.splice(next.findIndex((item) => item.id === to), 0, moved);
    change(next);
  };
  const submit = () => {
    if (onSubmit(list)) { setDirty(false); setSent(true); setDraft(list); }
  };
  const reset = () => { setDraft(todos); setDirty(false); setEditing(null); };
  const editKeys = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'Enter') { event.preventDefault(); commitEdit(); }
    if (event.key === 'Escape') { event.preventDefault(); setEditing(null); }
  };

  return <section aria-label="待办清单" className="mb-2 overflow-hidden rounded-2xl card-surface shadow-[inset_0_0_0_1px_var(--line)]">
    <button type="button" onClick={toggleCollapsed} aria-expanded={!collapsed}
      className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left hover:bg-hover">
      <ListChecks size={15} className="shrink-0 text-brand" />
      <span className="shrink-0 text-[13px] font-medium text-heading">待办</span>
      <span className="shrink-0 text-[12px] tabular-nums text-fg-3">{done}/{countable}</span>
      <span className="h-[3px] w-16 shrink-0 overflow-hidden rounded-full bg-line">
        <i className="block h-full rounded-full bg-ok transition-[width] duration-500" style={{ width: `${percent}%` }} />
      </span>
      {collapsed && current && <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2">
        {current.status === 'in_progress' ? (running ? '正在：' : '进行到：') : '下一项：'}{current.text}
      </span>}
      {collapsed && !current && countable > 0 && <span className="min-w-0 flex-1 truncate text-[12.5px] text-ok">全部完成</span>}
      {!collapsed && <span className="flex-1" />}
      {dirty && <span className="shrink-0 rounded-full bg-brand-soft px-2 py-[1px] text-[11px] text-brand">未提交</span>}
      {sent && !dirty && <span className="shrink-0 text-[11px] text-fg-3">已交给 Atlas</span>}
      <ChevronDown size={14} className={cn('shrink-0 text-fg-3 transition-transform', collapsed && '-rotate-90')} />
    </button>

    {!collapsed && <div className="anim-fade border-t border-line">
      <ol className="m-0 max-h-[38vh] list-none overflow-y-auto px-1.5 py-1.5">
        {list.map((item) => {
          const child = Boolean(item.parent);
          const finished = item.status === 'completed' || item.status === 'cancelled';
          return <li key={item.id}
            draggable={editing !== item.id}
            onDragStart={(event) => { setDragId(item.id); event.dataTransfer.effectAllowed = 'move'; }}
            onDragOver={(event) => { if (dragId) { event.preventDefault(); setOverId(item.id); } }}
            onDragLeave={() => setOverId((value) => value === item.id ? null : value)}
            onDrop={(event) => { event.preventDefault(); if (dragId) move(dragId, item.id); setDragId(null); setOverId(null); }}
            onDragEnd={() => { setDragId(null); setOverId(null); }}
            className={cn('group relative flex items-center gap-2 rounded-lg py-[5px] pr-1.5 pl-1 transition-colors hover:bg-hover',
              child && 'ml-6', dragId === item.id && 'opacity-40',
              overId === item.id && dragId !== item.id && 'shadow-[inset_0_2px_0_var(--brand)]',
              item.status === 'in_progress' && 'bg-brand-soft/60')}>
            <GripVertical size={13} className="shrink-0 cursor-grab text-fg-3 opacity-0 transition-opacity group-hover:opacity-60" aria-hidden />
            <Tip label={`${STATUS_LABEL[item.status]}，点一下改为${STATUS_LABEL[NEXT_STATUS[item.status]]}`}>
              <button type="button" aria-label={`切换状态：${item.text}`} onClick={() => patch(item.id, { status: NEXT_STATUS[item.status] })}
                className="group/dot shrink-0 rounded-full"><StatusDot status={item.status} live={running} /></button>
            </Tip>
            {editing === item.id
              ? <input autoFocus value={editText} onChange={(event) => setEditText(event.target.value)} onBlur={commitEdit} onKeyDown={editKeys} aria-label="修改待办内容"
                className="min-w-0 flex-1 rounded-md bg-overlay px-2 py-0.5 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--brand)]" />
              : <span onDoubleClick={() => { setEditing(item.id); setEditText(item.text); }} title="双击修改"
                className={cn('min-w-0 flex-1 cursor-text text-[13px] leading-[1.5] break-words',
                  finished ? 'text-fg-3 line-through decoration-line-strong' : item.status === 'in_progress' ? 'font-medium text-fg' : 'text-fg-2')}>
                {item.text}
                {item.status === 'in_progress' && running && <LoaderCircle size={12} className="ml-1.5 inline animate-spin align-[-1px] text-brand" />}
              </span>}
            {editing !== item.id && <span className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
              {item.status !== 'cancelled' && !finished && <Tip label="不做这一项"><button type="button" aria-label={`取消：${item.text}`} onClick={() => patch(item.id, { status: 'cancelled' })}
                className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-selected hover:text-fg"><X size={13} /></button></Tip>}
              <Tip label="删除"><button type="button" aria-label={`删除：${item.text}`} onClick={() => remove(item.id)}
                className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-selected hover:text-danger"><Trash2 size={13} /></button></Tip>
            </span>}
          </li>;
        })}
      </ol>
      <form className="flex items-center gap-2 px-3.5 pb-2.5" onSubmit={(event) => { event.preventDefault(); add(); }}>
        <Plus size={14} className="shrink-0 text-fg-3" />
        <input ref={addRef} value={adding} onChange={(event) => setAdding(event.target.value)} placeholder="添加一项，回车确认" aria-label="添加待办"
          className="min-w-0 flex-1 bg-transparent py-1 text-[13px] text-fg outline-none placeholder:text-fg-3" />
      </form>
      {dirty && <div className="anim-fade flex items-center gap-2 border-t border-line bg-sunken/70 px-3.5 py-2 text-[12px] text-fg-2">
        <span className="min-w-0 flex-1">{running ? '改好后交给 Atlas，它会在这一步做完后按新清单继续' : '改好后交给 Atlas，按新清单把剩下的做完'}</span>
        <button type="button" onClick={reset} className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-fg-3 hover:bg-hover hover:text-fg"><RotateCcw size={12} />撤销修改</button>
        <button type="button" onClick={submit} className="primary-fill inline-flex h-7 items-center gap-1.5 rounded-lg px-3 font-medium"><Send size={12} />{running ? '交给 Atlas' : '按清单继续'}</button>
      </div>}
    </div>}
  </section>;
}
