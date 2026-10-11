import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { ArrowDown, ArrowUp, Code2, ExternalLink, LayoutDashboard, Pencil, Pin, Plus, RefreshCw, Save, Trash2, X } from 'lucide-react';
import type { ConversationMessage } from '@atlas/backend-adapter';
import type { Step } from '../../components/timeline';
import { api } from '../../services/api';
import { cn } from '../../ui/cn';

type WidgetKind = 'text' | 'link' | 'code' | 'metric';
interface DashboardWidget { id: string; title: string; kind: WidgetKind; content: string; source_event_id?: string; position: number }
interface DashboardBoard { id: string; title: string; widgets: DashboardWidget[] }
interface DashboardResponse { conversation_id: string; boards: DashboardBoard[] }
interface WidgetDraft { title: string; kind: WidgetKind; content: string }
interface PinSource { key: string; label: string; title: string; kind: WidgetKind; content: string; source_event_id?: string }

const KINDS: Array<{ id: WidgetKind; label: string }> = [
  { id: 'text', label: '文本' }, { id: 'link', label: '链接' }, { id: 'code', label: '代码' }, { id: 'metric', label: '指标' },
];
const fieldClass = 'h-9 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-50';
const buttonClass = 'inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] text-fg-2 hover:bg-hover hover:text-fg disabled:cursor-not-allowed disabled:opacity-40';

function newId() { return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`; }
function isKind(value: unknown): value is WidgetKind { return value === 'text' || value === 'link' || value === 'code' || value === 'metric'; }
function normalizeDashboard(value: unknown): DashboardResponse {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const boards = Array.isArray(raw.boards) ? raw.boards.map((entry, boardIndex): DashboardBoard => {
    const board = entry && typeof entry === 'object' ? entry as Record<string, unknown> : {};
    const widgets = Array.isArray(board.widgets) ? board.widgets.map((item, index): DashboardWidget => {
      const widget = item && typeof item === 'object' ? item as Record<string, unknown> : {};
      return {
        id: typeof widget.id === 'string' && widget.id ? widget.id : newId(),
        title: typeof widget.title === 'string' ? widget.title : '未命名组件',
        kind: isKind(widget.kind) ? widget.kind : 'text',
        content: typeof widget.content === 'string' ? widget.content : '',
        ...(typeof widget.source_event_id === 'string' ? { source_event_id: widget.source_event_id } : {}),
        position: Number.isFinite(Number(widget.position)) ? Number(widget.position) : index,
      };
    }).sort((a, b) => a.position - b.position).map((widget, position) => ({ ...widget, position })) : [];
    return { id: typeof board.id === 'string' && board.id ? board.id : newId(), title: typeof board.title === 'string' ? board.title : `看板 ${boardIndex + 1}`, widgets };
  }) : [];
  return { conversation_id: typeof raw.conversation_id === 'string' ? raw.conversation_id : '', boards };
}
function toolPinText(step: Step) {
  const details = step.summary || step.failureReason || step.result || step.output;
  return [step.verb, step.target, details].filter(Boolean).join('\n');
}
function safeLink(value: string) {
  try {
    const url = new URL(value);
    return ['http:', 'https:', 'mailto:'].includes(url.protocol) ? url.href : null;
  } catch { return null; }
}

export default function SessionDashboardPanel({ apiBaseUrl, conversationId, messages, steps }: {
  apiBaseUrl: string; conversationId: string; messages: ConversationMessage[]; steps: Step[];
}) {
  const [boards, setBoards] = useState<DashboardBoard[]>([]);
  const [activeBoardId, setActiveBoardId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [loadFailed, setLoadFailed] = useState(false);
  const [fingerprint, setFingerprint] = useState('[]');
  const [reload, setReload] = useState(0);
  const [addingBoard, setAddingBoard] = useState(false);
  const [boardTitle, setBoardTitle] = useState('');
  const [editingWidget, setEditingWidget] = useState('');
  const [widgetDraft, setWidgetDraft] = useState<WidgetDraft>({ title: '', kind: 'text', content: '' });
  const [pinChoice, setPinChoice] = useState('');

  const path = `/api/conversations/${encodeURIComponent(conversationId)}/dashboard`;
  useEffect(() => {
    if (!conversationId) { setBoards([]); setActiveBoardId(''); setLoading(false); setError(''); setLoadFailed(false); setFingerprint('[]'); return; }
    let stale = false;
    setLoading(true); setError(''); setLoadFailed(false); setBoards([]); setActiveBoardId(''); setFingerprint('[]');
    void api<unknown>(apiBaseUrl, path).then((data) => {
      if (stale) return;
      const result = normalizeDashboard(data);
      setBoards(result.boards); setActiveBoardId(result.boards[0]?.id ?? ''); setFingerprint(JSON.stringify(result.boards));
    }).catch((cause: unknown) => { if (!stale) { setError(cause instanceof Error ? cause.message : String(cause)); setLoadFailed(true); } })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [apiBaseUrl, conversationId, path, reload]);

  const activeBoard = boards.find((board) => board.id === activeBoardId);
  const dirty = JSON.stringify(boards) !== fingerprint;
  const sourceOptions = useMemo<PinSource[]>(() => [
    ...messages.filter((message) => message.role === 'user' || message.role === 'assistant').map((message) => ({
      key: `message:${message.id}`, label: `${message.role === 'user' ? '你' : 'Atlas'} · ${message.content.replace(/\s+/g, ' ').slice(0, 70) || '空消息'}`,
      title: `${message.role === 'user' ? '用户消息' : 'Atlas 回复'} · ${message.content.replace(/\s+/g, ' ').slice(0, 36) || '消息'}`,
      kind: 'text' as const, content: message.content,
    })),
    ...steps.map((step) => ({ key: `tool:${step.id}`, label: `工具 · ${step.verb}${step.target ? ` · ${step.target}` : ''}`,
      title: `工具 · ${step.verb}`, kind: 'text' as const, content: toolPinText(step), source_event_id: step.id })),
  ], [messages, steps]);

  const updateBoard = (update: (board: DashboardBoard) => DashboardBoard) => {
    setBoards((current) => current.map((board) => board.id === activeBoardId ? update(board) : board));
  };
  const createBoard = (event: FormEvent) => {
    event.preventDefault();
    const title = boardTitle.trim();
    if (!title) return;
    const board = { id: newId(), title, widgets: [] };
    setBoards((current) => [...current, board]); setActiveBoardId(board.id); setBoardTitle(''); setAddingBoard(false);
  };
  const deleteBoard = () => {
    if (!activeBoard) return;
    const next = boards.filter((board) => board.id !== activeBoard.id);
    setBoards(next); setActiveBoardId(next[0]?.id ?? ''); setEditingWidget('');
  };
  const beginWidget = (widget?: DashboardWidget) => {
    setEditingWidget(widget?.id ?? 'new');
    setWidgetDraft(widget ? { title: widget.title, kind: widget.kind, content: widget.content } : { title: '', kind: 'text', content: '' });
  };
  const saveWidgetDraft = (event: FormEvent) => {
    event.preventDefault();
    if (!activeBoard || !widgetDraft.title.trim()) return;
    updateBoard((board) => {
      const existing = board.widgets.find((widget) => widget.id === editingWidget);
      const widget: DashboardWidget = {
        id: existing?.id ?? newId(), title: widgetDraft.title.trim(), kind: widgetDraft.kind, content: widgetDraft.content,
        ...(existing?.source_event_id ? { source_event_id: existing.source_event_id } : {}),
        position: existing?.position ?? board.widgets.length,
      };
      const widgets = existing ? board.widgets.map((item) => item.id === existing.id ? widget : item) : [...board.widgets, widget];
      return { ...board, widgets: widgets.map((item, position) => ({ ...item, position })) };
    });
    setEditingWidget('');
  };
  const pinSource = (key: string) => {
    if (!activeBoard) return;
    const source = sourceOptions.find((item) => item.key === key);
    if (!source) return;
    const widget: DashboardWidget = { id: newId(), title: source.title, kind: source.kind, content: source.content,
      ...(source.source_event_id ? { source_event_id: source.source_event_id } : {}), position: activeBoard.widgets.length };
    updateBoard((board) => ({ ...board, widgets: [...board.widgets, widget] }));
    setPinChoice('');
  };
  const moveWidget = (widgetId: string, direction: -1 | 1) => updateBoard((board) => {
    const index = board.widgets.findIndex((widget) => widget.id === widgetId);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= board.widgets.length) return board;
    const widgets = [...board.widgets]; [widgets[index], widgets[target]] = [widgets[target], widgets[index]];
    return { ...board, widgets: widgets.map((widget, position) => ({ ...widget, position })) };
  });
  const save = async () => {
    if (!conversationId || saving) return;
    setSaving(true); setError('');
    const snapshot = boards.map((board) => ({ ...board, widgets: board.widgets.map((widget, position) => ({ ...widget, position })) }));
    try {
      const result = normalizeDashboard(await api<unknown>(apiBaseUrl, path, { method: 'PUT', json: { boards: snapshot } }));
      setBoards(result.boards); setFingerprint(JSON.stringify(result.boards));
      setActiveBoardId((current) => result.boards.some((board) => board.id === current) ? current : result.boards[0]?.id ?? '');
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setSaving(false); }
  };

  if (!conversationId) return <div className="grid justify-items-center gap-2 py-10 text-center text-[13px] text-fg-3"><LayoutDashboard size={21} /><p className="m-0">先打开一个对话</p></div>;
  if (loading) return <p className="m-0 py-10 text-center text-[13px] text-fg-3">正在读取对话看板…</p>;
  if (loadFailed) return <div className="grid gap-3">{error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">读取看板失败：{error}</p>}
    <button type="button" onClick={() => setReload((value) => value + 1)} className={buttonClass}><RefreshCw size={13} />重试</button></div>;

  return <div className="grid content-start gap-3">
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{error}</p>}
    <div className="flex min-w-0 items-center gap-1 overflow-x-auto" role="tablist" aria-label="对话看板">
      {boards.map((board) => <button key={board.id} role="tab" aria-selected={board.id === activeBoardId} onClick={() => { setActiveBoardId(board.id); setEditingWidget(''); }}
        className={cn('shrink-0 rounded-lg px-2.5 py-1.5 text-[12.5px]', board.id === activeBoardId ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}>{board.title}</button>)}
      {addingBoard ? <form onSubmit={createBoard} className="flex shrink-0 gap-1"><input autoFocus value={boardTitle} disabled={saving} onChange={(event) => setBoardTitle(event.target.value)} aria-label="新看板名称" placeholder="看板名称" className={cn(fieldClass, 'h-8 w-32')} />
        <button type="submit" aria-label="创建看板" disabled={saving || !boardTitle.trim()} className={buttonClass}><Plus size={14} /></button><button type="button" aria-label="取消" disabled={saving} onClick={() => setAddingBoard(false)} className={buttonClass}><X size={14} /></button></form>
        : <button type="button" aria-label="添加看板" disabled={saving} onClick={() => setAddingBoard(true)} className={buttonClass}><Plus size={14} /></button>}
      <span className="flex-1" />
      <button type="button" aria-label="刷新看板" title="重新读取" onClick={() => setReload((value) => value + 1)} disabled={saving} className={buttonClass}><RefreshCw size={13} /></button>
      <button type="button" onClick={() => void save()} disabled={!dirty || saving} className={cn(buttonClass, dirty && 'text-brand')}><Save size={13} />{saving ? '保存中…' : dirty ? '保存' : '已保存'}</button>
    </div>

    {!activeBoard ? <div className="grid justify-items-center gap-2 rounded-xl card-surface px-4 py-8 text-center">
      <LayoutDashboard size={22} className="text-fg-3" /><p className="m-0 text-[13px] font-medium text-fg">还没有对话看板</p>
      <p className="m-0 max-w-64 text-[12px] leading-relaxed text-fg-3">创建看板后，可以整理消息、工具摘要、链接、代码和指标。</p>
      {!addingBoard && <button type="button" onClick={() => setAddingBoard(true)} className="primary-fill mt-1 inline-flex h-8 items-center gap-1.5 rounded-[9px] px-3 text-[12.5px] font-medium"><Plus size={14} />新建看板</button>}
    </div> : <>
      <div className="flex items-center gap-2">
        <input aria-label="看板名称" value={activeBoard.title} disabled={saving} onChange={(event) => updateBoard((board) => ({ ...board, title: event.target.value }))} className={cn(fieldClass, 'min-w-0 flex-1 font-medium')} />
        <button type="button" aria-label="删除看板" title="删除当前看板" disabled={saving} onClick={deleteBoard} className={buttonClass}><Trash2 size={14} /></button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <button type="button" disabled={saving} onClick={() => beginWidget()} className="primary-fill inline-flex h-8 items-center gap-1.5 rounded-[9px] px-2.5 text-[12px] font-medium"><Plus size={13} />添加组件</button>
        <label className="sr-only" htmlFor="dashboard-pin-source">固定当前对话内容</label>
        <select id="dashboard-pin-source" value={pinChoice} disabled={saving || !sourceOptions.length} onChange={(event) => pinSource(event.target.value)} className={cn(fieldClass, 'h-8 max-w-full py-0 text-[12px]')}>
          <option value="">固定消息 / 工具摘要…</option>
          {messages.some((message) => message.role === 'user' || message.role === 'assistant') && <optgroup label="对话消息">{sourceOptions.filter((item) => item.key.startsWith('message:')).map((source) => <option key={source.key} value={source.key}>{source.label}</option>)}</optgroup>}
          {steps.length > 0 && <optgroup label="工具摘要">{sourceOptions.filter((item) => item.key.startsWith('tool:')).map((source) => <option key={source.key} value={source.key}>{source.label}</option>)}</optgroup>}
        </select>
      </div>

      {editingWidget && <form onSubmit={saveWidgetDraft} className="grid gap-2 rounded-xl card-surface p-3">
        <div className="flex items-center"><b className="flex-1 text-[12.5px] text-fg">{editingWidget === 'new' ? '新组件' : '编辑组件'}</b><button type="button" aria-label="关闭编辑器" onClick={() => setEditingWidget('')} className={buttonClass}><X size={14} /></button></div>
        <div className="grid grid-cols-[minmax(0,1fr)_100px] gap-2">
          <input required aria-label="组件标题" placeholder="标题" value={widgetDraft.title} disabled={saving} onChange={(event) => setWidgetDraft({ ...widgetDraft, title: event.target.value })} className={fieldClass} />
          <select aria-label="组件类型" value={widgetDraft.kind} disabled={saving} onChange={(event) => setWidgetDraft({ ...widgetDraft, kind: event.target.value as WidgetKind })} className={fieldClass}>{KINDS.map((kind) => <option key={kind.id} value={kind.id}>{kind.label}</option>)}</select>
        </div>
        <textarea required aria-label="组件内容" rows={4} placeholder={widgetDraft.kind === 'link' ? 'https://…' : '内容'} value={widgetDraft.content} disabled={saving} onChange={(event) => setWidgetDraft({ ...widgetDraft, content: event.target.value })} className="rounded-[9px] bg-sunken px-3 py-2 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
        <div className="flex justify-end gap-1.5"><button type="button" onClick={() => setEditingWidget('')} className={buttonClass}>取消</button><button type="submit" disabled={saving || !widgetDraft.title.trim()} className="primary-fill inline-flex h-8 items-center gap-1.5 rounded-[9px] px-3 text-[12px] font-medium"><Save size={13} />应用</button></div>
      </form>}

      {!activeBoard.widgets.length ? <div className="rounded-xl card-surface px-4 py-7 text-center text-[12.5px] text-fg-3">这个看板还是空的。添加组件或固定一条对话消息。</div>
        : <div className="grid gap-2">{activeBoard.widgets.map((widget, index) => <article key={widget.id} className="min-w-0 rounded-xl card-surface p-3">
          <div className="mb-2 flex items-start gap-2">
            <div className="min-w-0 flex-1"><h3 className="m-0 break-words text-[13px] font-medium text-fg">{widget.title}</h3>{widget.source_event_id && <span className="mt-0.5 inline-flex items-center gap-1 text-[10.5px] text-fg-3"><Pin size={10} />已固定工具事件</span>}</div>
            <button type="button" aria-label="上移组件" title="上移" disabled={saving || index === 0} onClick={() => moveWidget(widget.id, -1)} className={buttonClass}><ArrowUp size={13} /></button>
            <button type="button" aria-label="下移组件" title="下移" disabled={saving || index === activeBoard.widgets.length - 1} onClick={() => moveWidget(widget.id, 1)} className={buttonClass}><ArrowDown size={13} /></button>
            <button type="button" aria-label="编辑组件" title="编辑" disabled={saving} onClick={() => beginWidget(widget)} className={buttonClass}><Pencil size={13} /></button>
            <button type="button" aria-label="删除组件" title="删除" disabled={saving} onClick={() => updateBoard((board) => ({ ...board, widgets: board.widgets.filter((item) => item.id !== widget.id).map((item, position) => ({ ...item, position })) }))} className={buttonClass}><Trash2 size={13} /></button>
          </div>
          {widget.kind === 'link' ? (safeLink(widget.content) ? <a href={safeLink(widget.content)!} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 break-all text-[12.5px] text-brand underline underline-offset-2"><ExternalLink size={12} className="shrink-0" />{widget.content}</a> : <p className="m-0 break-all text-[12.5px] text-fg-2">{widget.content}<span className="ml-2 text-[11px] text-danger">只支持 http、https 或 mailto 链接</span></p>)
            : widget.kind === 'code' ? <pre className="m-0 max-h-64 overflow-auto rounded-lg bg-sunken p-2.5 font-mono text-[11.5px] leading-relaxed text-fg-2"><code>{widget.content}</code></pre>
              : widget.kind === 'metric' ? <div className="flex items-start gap-2 text-[13px] font-medium text-brand"><Code2 size={14} className="mt-0.5 shrink-0" /><span className="whitespace-pre-wrap break-words">{widget.content}</span></div>
                : <p className="m-0 whitespace-pre-wrap break-words text-[12.5px] leading-relaxed text-fg-2">{widget.content}</p>}
        </article>)}</div>}
    </>}
  </div>;
}
