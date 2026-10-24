import { useEffect, useMemo, useState } from 'react';
import { AlertCircle, ArrowDown, ArrowUp, Clock3, GripVertical, ListTodo, RefreshCw } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { api } from '../services/api';
import { Dialog } from '../ui/Dialog';

type Column = 'todo' | 'doing' | 'done';
type Item = { conversation_id: string; title: string; updated_at?: string; status: string; waiting_for?: string | null; priority: number; position: number; column: Column; attention: boolean; category: 'waiting' | 'failed' | 'pending' | null };
const columns: Array<{ id: Column; label: string }> = [{ id: 'todo', label: '待办' }, { id: 'doing', label: '进行中' }, { id: 'done', label: '完成' }];
const statusLabel: Record<string, string> = { waiting: '等待输入', failed: '运行失败', running: '运行中', planning: '规划中', idle: '空闲', completed: '已完成', cancelled: '已取消' };

export default function TriageBoardDialog({ apiBaseUrl, open, onOpenChange, conversations, onOpenConversation }: {
  apiBaseUrl: string; open: boolean; onOpenChange: (open: boolean) => void; conversations: ConversationSummary[];
  onOpenConversation: (conversation: ConversationSummary) => void;
}) {
  const [items, setItems] = useState<Item[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [dragged, setDragged] = useState<string | null>(null);
  const [inboxFilter, setInboxFilter] = useState<'all' | 'waiting' | 'failed' | 'pending'>('all');
  const [sortMode, setSortMode] = useState<'priority' | 'manual'>('priority');
  const [revision, setRevision] = useState(0);
  const refresh = () => {
    setLoading(true); setError('');
    void api<{ items: Item[] }>(apiBaseUrl, '/api/triage').then((result) => setItems(result.items ?? []))
      .catch((cause) => setError(cause instanceof Error ? cause.message : '收件箱读取失败'))
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    if (!open) return;
    refresh(); const timer = window.setInterval(refresh, 10000);
    return () => window.clearInterval(timer);
  }, [open, apiBaseUrl]);
  useEffect(() => {
    if (!open || revision === 0) return;
    const timer = window.setTimeout(() => {
      void api(apiBaseUrl, '/api/triage', { method: 'PUT', json: { items: items.map((item, position) => ({ conversation_id: item.conversation_id, column: item.column, priority: item.priority, position })) } })
        .catch((cause) => setError(cause instanceof Error ? `工作板保存失败：${cause.message}` : '工作板保存失败'));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [items, revision, open, apiBaseUrl]);
  const update = (next: Item[]) => { setItems(next); setRevision((value) => value + 1); };
  const sorted = useMemo(() => [...items].sort((a, b) => sortMode === 'priority'
    ? a.priority - b.priority || a.position - b.position || (b.updated_at ?? '').localeCompare(a.updated_at ?? '')
    : a.position - b.position || a.priority - b.priority), [items, sortMode]);
  const inboxItems = sorted.filter((item) => inboxFilter === 'all' ? item.category : item.category === inboxFilter);
  const moveTo = (id: string, column: Column) => update(items.map((item) => item.conversation_id === id ? { ...item, column, position: items.filter((other) => other.column === column).length, category: item.status === 'waiting' ? 'waiting' : item.status === 'failed' ? 'failed' : column === 'todo' ? 'pending' : null } : item));
  const dropOn = (targetId: string | null, column: Column) => {
    if (!dragged) return;
    const ordered = [...sorted]; const from = ordered.findIndex((item) => item.conversation_id === dragged);
    if (from < 0) return;
    const [item] = ordered.splice(from, 1); item.column = column;
    item.category = item.status === 'waiting' ? 'waiting' : item.status === 'failed' ? 'failed' : column === 'todo' ? 'pending' : null;
    const target = targetId ? ordered.findIndex((entry) => entry.conversation_id === targetId) : -1;
    const insert = target >= 0 ? target : ordered.filter((entry) => entry.column === column).length;
    ordered.splice(insert, 0, item);
    update(ordered.map((entry, position) => ({ ...entry, position }))); setSortMode('manual'); setDragged(null);
  };
  const priority = (id: string, value: number) => update(items.map((item) => item.conversation_id === id ? { ...item, priority: value } : item));
  const openItem = (item: Item) => {
    const conversation = conversations.find((entry) => entry.id === item.conversation_id);
    if (conversation) { onOpenConversation(conversation); onOpenChange(false); }
  };
  const card = (item: Item) => <article key={item.conversation_id} draggable onDragStart={() => setDragged(item.conversation_id)} onDragEnd={() => setDragged(null)}
    onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); dropOn(item.conversation_id, item.column); }}
    className="rounded-lg border border-line bg-surface p-2.5 shadow-sm">
    <div className="flex items-start gap-1.5"><GripVertical size={14} className="mt-0.5 shrink-0 cursor-grab text-fg-3" /><button type="button" onClick={() => openItem(item)} className="min-w-0 flex-1 text-left text-[12px] font-medium leading-snug text-fg hover:text-brand">{item.title || '新对话'}</button>
      {item.attention && <AlertCircle size={14} className="shrink-0 text-amber-500" aria-label={item.status === 'waiting' ? '等待输入' : '运行失败'} />}</div>
    <div className="mt-2 flex items-center gap-1.5 pl-5 text-[10.5px] text-fg-3"><span className={item.status === 'failed' ? 'text-danger' : item.status === 'waiting' ? 'text-amber-600' : ''}>{statusLabel[item.status] ?? item.status}</span>{item.waiting_for && <span className="truncate">· {item.waiting_for}</span>}</div>
    <div className="mt-2 flex items-center justify-between pl-5"><label className="flex items-center gap-1 text-[10.5px] text-fg-3">优先级<select aria-label={`${item.title}优先级`} value={item.priority} onChange={(event) => priority(item.conversation_id, Number(event.target.value))} className="rounded border border-line bg-surface px-1 py-0.5 text-fg">{[1,2,3,4,5].map((value) => <option key={value} value={value}>{value}{value === 1 ? ' · 最高' : value === 5 ? ' · 最低' : ''}</option>)}</select></label>
      <div className="flex gap-1">{item.column !== 'todo' && <button aria-label="移到待办" onClick={() => moveTo(item.conversation_id, 'todo')} className="rounded p-1 text-fg-3 hover:bg-hover"><ArrowUp size={13} /></button>}{item.column !== 'done' && <button aria-label={item.column === 'todo' ? '移到进行中' : '移到完成'} onClick={() => moveTo(item.conversation_id, item.column === 'todo' ? 'doing' : 'done')} className="rounded p-1 text-fg-3 hover:bg-hover"><ArrowDown size={13} /></button>}</div></div>
  </article>;
  return <Dialog open={open} onOpenChange={onOpenChange} label="跨会话分诊与工作板" className="w-[min(1080px,calc(100vw-32px))] max-h-[min(88vh,900px)] overflow-hidden border border-line bg-overlay p-4 shadow-2xl" align="center">
    <div className="flex items-center gap-2"><ListTodo size={18} className="text-brand"/><h2 className="m-0 flex-1 text-[16px] font-semibold text-heading">跨会话收件箱与工作板</h2><button type="button" onClick={refresh} disabled={loading} aria-label="刷新收件箱" className="rounded-md p-1.5 text-fg-3 hover:bg-hover"><RefreshCw size={15} className={loading ? 'animate-spin' : ''}/></button><button type="button" onClick={() => onOpenChange(false)} className="rounded-md px-2 py-1 text-[12px] text-fg-3 hover:bg-hover">关闭</button></div>
    <p className="mb-3 mt-1 text-[11.5px] text-fg-3">等待输入和失败任务会进入分诊队列；拖动卡片调整顺序或移到待办、进行中、完成。点标题恢复原会话。</p>
    <section className="mb-3 rounded-lg border border-line bg-sunken p-2.5"><div className="mb-1.5 flex items-center gap-1.5 text-[11.5px] font-medium text-fg"><Clock3 size={13}/>{`分诊队列 · ${inboxItems.length}`}</div><div className="mb-2 flex flex-wrap gap-1" role="group" aria-label="分诊类别">
      {([{ id: 'all', label: `全部 ${sorted.filter((item) => item.category).length}` }, { id: 'waiting', label: `等待输入 ${sorted.filter((item) => item.category === 'waiting').length}` }, { id: 'failed', label: `失败 ${sorted.filter((item) => item.category === 'failed').length}` }, { id: 'pending', label: `待处理 ${sorted.filter((item) => item.category === 'pending').length}` }] as const).map((filter) => <button key={filter.id} aria-pressed={inboxFilter === filter.id} onClick={() => setInboxFilter(filter.id)} className={`rounded-md px-2 py-1 text-[10.5px] ${inboxFilter === filter.id ? 'bg-brand-soft text-brand' : 'text-fg-3 hover:bg-hover'}`}>{filter.label}</button>)}
    </div><div className="mb-2 flex items-center gap-1" role="group" aria-label="队列排序"><span className="mr-1 text-[10px] text-fg-3">排序</span><button aria-pressed={sortMode === 'priority'} onClick={() => setSortMode('priority')} className={`rounded px-2 py-1 text-[10.5px] ${sortMode === 'priority' ? 'bg-brand-soft text-brand' : 'text-fg-3 hover:bg-hover'}`}>优先级</button><button aria-pressed={sortMode === 'manual'} onClick={() => setSortMode('manual')} className={`rounded px-2 py-1 text-[10.5px] ${sortMode === 'manual' ? 'bg-brand-soft text-brand' : 'text-fg-3 hover:bg-hover'}`}>手动顺序</button></div><div className="flex max-h-32 flex-wrap gap-2 overflow-auto">{inboxItems.map((item) => <button key={item.conversation_id} onClick={() => openItem(item)} className="max-w-full truncate rounded-md border border-line bg-surface px-2 py-1 text-left text-[11px] hover:border-brand/40"><span className={item.category === 'failed' ? 'text-danger' : item.category === 'waiting' ? 'text-amber-600' : 'text-fg-3'}>{item.category === 'failed' ? '运行失败' : item.category === 'waiting' ? '等待输入' : '待处理'}</span> · {item.title}</button>)}</div></section>
    {error && <p role="alert" className="text-[12px] text-danger">{error}</p>}
    <div className="grid max-h-[64vh] min-h-64 grid-cols-3 gap-2 overflow-hidden">{columns.map((column) => {
      const rows = sorted.filter((item) => item.column === column.id);
      return <section key={column.id} onDragOver={(event) => event.preventDefault()} onDrop={(event) => { event.preventDefault(); dropOn(null, column.id); }} className="flex min-h-0 flex-col rounded-lg bg-sunken p-2">
        <h3 className="mb-2 mt-0 flex items-center justify-between px-1 text-[12px] font-medium text-fg">{column.label}<span className="text-[10px] text-fg-3">{rows.length}</span></h3><div className="grid min-h-0 flex-1 content-start gap-1.5 overflow-auto">{rows.map(card)}{!rows.length && <div className="rounded-md border border-dashed border-line px-2 py-5 text-center text-[10.5px] text-fg-3">拖动会话到这里</div>}</div>
      </section>;
    })}</div>
  </Dialog>;
}
