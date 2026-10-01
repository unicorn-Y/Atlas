import { useMemo, useState } from 'react';
import { Check, ChevronUp, Circle, CircleDot, ListTodo, X } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';
import { cn } from '../ui/cn';

type Todo = { id: string; text: string; status: string };

/** The newest todo list of the run (older revisions arriving late are ignored). */
export function latestTodos(events: AgentEvent[]): Todo[] {
  let best: { revision: number; todos: Todo[] } | null = null;
  for (const event of events) {
    if (event.type !== 'run.todos') continue;
    const revision = Number(event.data.revision ?? 0);
    if (best && revision < best.revision) continue;
    const raw = Array.isArray(event.data.todos) ? event.data.todos as Array<Record<string, unknown>> : [];
    best = { revision, todos: raw.map((item, index) => ({
      id: String(item.id ?? index), text: String(item.text ?? item.content ?? ''), status: String(item.status ?? 'pending'),
    })).filter((item) => item.text) };
  }
  return best?.todos ?? [];
}

const DONE = new Set(['completed', 'done']);
const ACTIVE = new Set(['in_progress', 'running', 'active']);

/** Atlas's own checklist for the current task, folded to one line above the composer. */
export default function TodoStrip({ events }: { events: AgentEvent[] }) {
  const todos = useMemo(() => latestTodos(events), [events]);
  const [open, setOpen] = useState(false);
  if (!todos.length) return null;
  const done = todos.filter((todo) => DONE.has(todo.status)).length;
  const current = todos.find((todo) => ACTIVE.has(todo.status)) ?? todos.find((todo) => !DONE.has(todo.status) && todo.status !== 'cancelled');
  return <div className="mb-2 overflow-hidden rounded-xl card-surface text-[12.5px]">
    <button onClick={() => setOpen((value) => !value)} aria-expanded={open} className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-hover">
      <ListTodo size={14} className="shrink-0 text-brand" />
      <span className="shrink-0 font-medium text-fg">待办 {done}/{todos.length}</span>
      <span className="h-1 w-14 shrink-0 overflow-hidden rounded-full bg-sunken"><span className="block h-full rounded-full bg-ok transition-all" style={{ width: `${(done / todos.length) * 100}%` }} /></span>
      {current && !open && <span className="min-w-0 flex-1 truncate text-fg-3">正在做：{current.text}</span>}
      <ChevronUp size={14} className={cn('ml-auto shrink-0 text-fg-3 transition-transform', !open && 'rotate-180')} />
    </button>
    {open && <ol className="anim-fade m-0 grid max-h-52 list-none gap-0.5 overflow-auto px-3 pt-0.5 pb-2">
      {todos.map((todo) => <li key={todo.id} className="flex items-start gap-2 py-0.5">
        {DONE.has(todo.status) ? <Check size={13} className="mt-[3px] shrink-0 text-ok" />
          : todo.status === 'cancelled' ? <X size={13} className="mt-[3px] shrink-0 text-fg-3" />
          : ACTIVE.has(todo.status) ? <CircleDot size={13} className="mt-[3px] shrink-0 text-brand" />
          : <Circle size={13} className="mt-[3px] shrink-0 text-fg-3" />}
        <span className={cn('min-w-0', DONE.has(todo.status) || todo.status === 'cancelled' ? 'text-fg-3 line-through decoration-line-strong' : 'text-fg-2')}>{todo.text}</span>
      </li>)}
    </ol>}
  </div>;
}
