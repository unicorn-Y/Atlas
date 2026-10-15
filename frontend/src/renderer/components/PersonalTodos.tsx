import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { Check, ChevronDown, ChevronRight, GripHorizontal, ListTodo, Minus, Pencil, Plus, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { cn } from '../ui/cn';

/** The user's own to-do list (not the agent's run todos): a floating, draggable, collapsible card
 * that opens with Atlas so unfinished plans are the first thing in view. Stored by the backend in
 * data/personal-todos.json; position and collapsed state are per-machine localStorage conveniences. */

interface PersonalTodo { id: string; text: string; done: boolean; created_at: string; done_at: string | null }

const POS_KEY = 'atlas.personalTodos.pos';
const OPEN_KEY = 'atlas.personalTodos.open';
const SHOW_DONE_KEY = 'atlas.personalTodos.showDone';
const CARD_WIDTH = 300;

function readPref<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw === null ? fallback : JSON.parse(raw) as T; } catch { return fallback; }
}
function writePref(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
function newId() {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}
/** Anchored to the window's top-right corner so it stays put when the window resizes. */
interface Pos { right: number; top: number }
function clampPos(pos: Pos, width: number): Pos {
  if (!window.innerWidth) return pos;
  return {
    right: Math.min(Math.max(8, pos.right), Math.max(8, window.innerWidth - width - 8)),
    top: Math.min(Math.max(8, pos.top), Math.max(8, window.innerHeight - 48)),
  };
}

export default function PersonalTodos({ apiBaseUrl, connected }: { apiBaseUrl: string; connected: boolean }) {
  const [items, setItems] = useState<PersonalTodo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(() => readPref(OPEN_KEY, true));
  const [showDone, setShowDone] = useState(() => readPref(SHOW_DONE_KEY, false));
  const [pos, setPos] = useState<Pos>(() => { const saved = readPref<Partial<Pos>>(POS_KEY, {}); return { right: saved.right ?? 20, top: saved.top ?? 56 }; });
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const dirty = useRef(false);
  const drag = useRef<{ x: number; y: number; start: Pos; moved: boolean } | null>(null);
  const cardRef = useRef<HTMLDivElement>(null);

  // Load independently of the rest of the app's connection state; `connected` only re-triggers a retry.
  useEffect(() => {
    if (loaded) return;
    let cancelled = false;
    let retry: number | undefined;
    api<{ items: PersonalTodo[] }>(apiBaseUrl, '/api/personal-todos')
      .then((result) => { if (cancelled) return; if (!dirty.current) setItems(result.items); setLoaded(true); setError(null); })
      .catch(() => { if (!cancelled) retry = window.setTimeout(() => setAttempt((value) => value + 1), 3000); });
    return () => { cancelled = true; window.clearTimeout(retry); };
  }, [apiBaseUrl, connected, attempt, loaded]);

  // Debounced whole-list save after every local change.
  useEffect(() => {
    if (!dirty.current) return;
    const timer = window.setTimeout(() => {
      api<{ items: PersonalTodo[] }>(apiBaseUrl, '/api/personal-todos', { method: 'PUT', json: { items } })
        .then(() => setError(null))
        .catch((err) => setError(`保存失败：${err instanceof Error ? err.message : String(err)}`));
    }, 400);
    return () => window.clearTimeout(timer);
  }, [items, apiBaseUrl]);

  useEffect(() => {
    const onResize = () => setPos((current) => clampPos(current, cardRef.current?.offsetWidth ?? CARD_WIDTH));
    window.addEventListener('resize', onResize);
    onResize();
    return () => window.removeEventListener('resize', onResize);
  }, [open]);

  const update = (next: (current: PersonalTodo[]) => PersonalTodo[]) => { dirty.current = true; setItems(next); };
  const toggleOpen = () => setOpen((value) => { writePref(OPEN_KEY, !value); return !value; });

  const add = () => {
    const text = draft.trim();
    if (!text) return;
    update((current) => [...current, { id: newId(), text, done: false, created_at: new Date().toISOString(), done_at: null }]);
    setDraft('');
  };
  const toggleDone = (id: string) => update((current) => current.map((item) => item.id === id
    ? { ...item, done: !item.done, done_at: item.done ? null : new Date().toISOString() } : item));
  const remove = (id: string) => update((current) => current.filter((item) => item.id !== id));
  const commitEdit = () => {
    if (!editing) return;
    const text = editing.text.trim();
    if (text) update((current) => current.map((item) => item.id === editing.id ? { ...item, text } : item));
    else remove(editing.id);
    setEditing(null);
  };
  const clearDone = () => update((current) => current.filter((item) => !item.done));

  const onPointerDown = (event: ReactPointerEvent) => {
    if (event.button !== 0 || (event.target as HTMLElement).closest('[data-no-drag]')) return;
    drag.current = { x: event.clientX, y: event.clientY, start: pos, moved: false };
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent) => {
    if (!drag.current) return;
    const { x, y, start } = drag.current;
    if (Math.abs(event.clientX - x) + Math.abs(event.clientY - y) < 3) return;
    drag.current.moved = true;
    setPos(clampPos({ right: start.right - (event.clientX - x), top: start.top + (event.clientY - y) }, cardRef.current?.offsetWidth ?? CARD_WIDTH));
  };
  const onPointerUp = () => {
    const wasDrag = drag.current?.moved;
    drag.current = null;
    if (wasDrag) writePref(POS_KEY, pos);
    return wasDrag;
  };

  const pending = items.filter((item) => !item.done);
  const done = items.filter((item) => item.done).sort((a, b) => (b.done_at ?? '').localeCompare(a.done_at ?? ''));

  if (!open) return (
    <div ref={cardRef} style={{ right: pos.right, top: pos.top }}
      className="fixed z-40 flex select-none items-center gap-1.5 rounded-full border border-line bg-overlay px-3 py-1.5 text-[12.5px] text-fg-2 shadow-raised hover:text-fg cursor-grab active:cursor-grabbing"
      onPointerDown={onPointerDown} onPointerMove={onPointerMove}
      onPointerUp={() => { if (!onPointerUp()) toggleOpen(); }}
      role="button" title="展开待办（可拖动）">
      <ListTodo size={14} className="text-brand" />
      <span>待办</span>
      {pending.length > 0 && <span className="rounded-full bg-brand-soft px-1.5 text-[11px] font-medium text-brand">{pending.length}</span>}
    </div>
  );

  const row = (item: PersonalTodo) => (
    <li key={item.id} className="group flex items-start gap-2 rounded-md px-1.5 py-1 hover:bg-hover">
      <button data-no-drag type="button" onClick={() => toggleDone(item.id)} title={item.done ? '标记为未完成' : '标记为已完成'}
        className={cn('mt-[3px] grid size-[15px] shrink-0 place-items-center rounded-[4px] border',
          item.done ? 'border-brand bg-brand text-on-primary' : 'border-line-strong hover:border-brand')}>
        {item.done && <Check size={11} strokeWidth={3} />}
      </button>
      {editing?.id === item.id ? (
        <textarea data-no-drag autoFocus rows={1} value={editing.text}
          onChange={(event) => setEditing({ id: item.id, text: event.target.value })}
          onBlur={commitEdit}
          onFocus={(event) => event.currentTarget.select()}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); commitEdit(); }
            if (event.key === 'Escape') setEditing(null);
          }}
          className="min-w-0 flex-1 resize-none rounded border border-brand bg-bg px-1 text-[13px] leading-[1.5] text-fg outline-none [field-sizing:content]" />
      ) : (
        <span onDoubleClick={() => setEditing({ id: item.id, text: item.text })}
          className={cn('min-w-0 flex-1 whitespace-pre-wrap break-words text-[13px] leading-[1.5]', item.done ? 'text-fg-3 line-through' : 'text-fg')}>
          {item.text}
        </span>
      )}
      {editing?.id !== item.id && (
        <span data-no-drag className="flex shrink-0 items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100">
          <button type="button" title="修改" onClick={() => setEditing({ id: item.id, text: item.text })} className="rounded p-0.5 text-fg-3 hover:text-fg"><Pencil size={12} /></button>
          <button type="button" title="删除" onClick={() => remove(item.id)} className="rounded p-0.5 text-fg-3 hover:text-danger"><Trash2 size={12} /></button>
        </span>
      )}
    </li>
  );

  return (
    <div ref={cardRef} style={{ right: pos.right, top: pos.top, width: CARD_WIDTH }}
      className="fixed z-40 flex max-h-[min(560px,calc(100vh-80px))] flex-col rounded-xl border border-line bg-overlay shadow-pop">
      <div className="flex select-none items-center gap-2 border-b border-line px-3 py-2 cursor-grab active:cursor-grabbing"
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
        onDoubleClick={(event) => { if (!(event.target as HTMLElement).closest('[data-no-drag]')) toggleOpen(); }}>
        <ListTodo size={15} className="text-brand" />
        <span className="text-[13px] font-semibold text-heading">我的待办</span>
        <span className="text-[12px] text-fg-3">{pending.length ? `${pending.length} 项未完成` : loaded ? '全部完成' : ''}</span>
        <GripHorizontal size={14} className="ml-auto text-fg-3" />
        <button data-no-drag type="button" onClick={toggleOpen} title="折叠" className="rounded p-0.5 text-fg-3 hover:bg-hover hover:text-fg"><Minus size={14} /></button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1.5">
        {pending.length === 0 && loaded && <p className="px-2 py-3 text-center text-[12.5px] text-fg-3">没有待办，下面添加一条计划</p>}
        <ul className="m-0 list-none p-0">{pending.map(row)}</ul>
        {done.length > 0 && (
          <div className="mt-1 border-t border-line pt-1">
            <div className="flex items-center px-1">
              <button type="button" onClick={() => setShowDone((value) => { writePref(SHOW_DONE_KEY, !value); return !value; })}
                className="flex items-center gap-1 rounded px-1 py-0.5 text-[12px] text-fg-3 hover:text-fg">
                {showDone ? <ChevronDown size={12} /> : <ChevronRight size={12} />}已完成 {done.length}
              </button>
              {showDone && <button type="button" onClick={clearDone} className="ml-auto rounded px-1 py-0.5 text-[11.5px] text-fg-3 hover:text-danger">清空已完成</button>}
            </div>
            {showDone && <ul className="m-0 list-none p-0">{done.map(row)}</ul>}
          </div>
        )}
      </div>

      <form className="flex items-center gap-1.5 border-t border-line px-2 py-2" onSubmit={(event) => { event.preventDefault(); add(); }}>
        <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={loaded ? '添加待办，回车保存' : '正在读取待办…'}
          disabled={!loaded}
          onKeyDown={(event) => { if (event.key === 'Enter' && event.nativeEvent.isComposing) event.preventDefault(); }}
          className="min-w-0 flex-1 rounded-md border border-line bg-bg px-2 py-1 text-[13px] text-fg outline-none placeholder:text-fg-3 focus:border-brand" />
        <button type="submit" disabled={!draft.trim()} title="添加"
          className="grid size-7 place-items-center rounded-md bg-brand text-on-primary disabled:opacity-40"><Plus size={14} /></button>
      </form>
      {error && <p className="m-0 border-t border-line px-3 py-1.5 text-[11.5px] text-danger">{error}</p>}
    </div>
  );
}
