import { useEffect, useState } from 'react';
import { GitBranch } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';

export const loadConversationBranches = (
  activeId: string,
  load: typeof backend.getConversationBranches = (id) => backend.getConversationBranches(id),
) => activeId ? load(activeId) : Promise.resolve([]);

/** The family of conversations forked from one another, with the open one marked; pick any to jump. */
export default function ForkTree({ conversations, activeId, onOpen, running = [], waiting = [] }: {
  conversations: ConversationSummary[]; activeId: string; onOpen: (conversation: ConversationSummary) => void; running?: string[]; waiting?: string[];
}) {
  const [tree, setTree] = useState<Array<{ id: string; parent_session_id?: string | null; title: string }> | null>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  useEffect(() => {
    let stale = false;
    setTree(null);
    void loadConversationBranches(activeId).then((value) => { if (!stale) setTree(value); })
      .catch(() => { if (!stale) setTree([]); });
    return () => { stale = true; };
  }, [activeId]);
  const byId = new Map(conversations.map((item) => [item.id, item]));
  const active = byId.get(activeId);
  if (!active || !tree?.length) return null;
  const treeById = new Map(tree.map((item) => [item.id, item]));
  const children = new Map<string, Array<{ id: string; parent_session_id?: string | null; title: string }>>();
  for (const node of tree) {
    const parent = node.parent_session_id;
    if (parent && treeById.has(parent)) children.set(parent, [...(children.get(parent) ?? []), node]);
  }
  const actualParent = treeById.get(activeId)?.parent_session_id;
  const parentNode = actualParent ? treeById.get(actualParent) : undefined;
  const parent = parentNode ? byId.get(parentNode.id) ?? { id: parentNode.id, title: parentNode.title } : undefined;
  if (!parent && !children.get(activeId)?.length) return null;
  let rootId = active.id;
  for (const seen = new Set<string>(); treeById.get(rootId)?.parent_session_id && treeById.has(String(treeById.get(rootId)?.parent_session_id)) && !seen.has(rootId);) {
    seen.add(rootId);
    rootId = String(treeById.get(rootId)?.parent_session_id);
  }
  const rows: Array<{ item: ConversationSummary; depth: number }> = [];
  const walk = (node: { id: string; parent_session_id?: string | null; title: string }, depth: number) => {
    if (rows.some((row) => row.item.id === node.id)) return;
    rows.push({ item: byId.get(node.id) ?? { id: node.id, title: node.title }, depth });
    for (const child of children.get(node.id) ?? []) walk(child, depth + 1);
  };
  walk(treeById.get(rootId) ?? { id: rootId, title: rootId }, 0);
  const forks = children.get(activeId)?.length ?? 0;
  const needle = query.trim().toLocaleLowerCase();
  const visibleRows = (() => {
    if (!needle) return rows;
    const keep = new Set<string>();
    for (const row of rows) {
      if (!`${row.item.title} ${row.item.id}`.toLocaleLowerCase().includes(needle)) continue;
      let id: string | null = row.item.id;
      while (id && !keep.has(id)) { keep.add(id); id = treeById.get(id)?.parent_session_id ?? null; }
    }
    return rows.filter((row) => keep.has(row.item.id));
  })();

  return <>
    <button type="button" title="搜索并浏览完整分叉树" onClick={() => { setOpen(true); setQuery(''); }} className="no-drag inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-fg-3 hover:bg-hover hover:text-fg">
      <GitBranch size={12} />{parent ? `分叉自 ${parent.title.slice(0, 16)}` : `${forks} 个分叉`}
    </button>
    {open && <div role="dialog" aria-modal="true" aria-label="完整会话分叉树" className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" onMouseDown={(event) => { if (event.target === event.currentTarget) setOpen(false); }}>
      <section className="card-surface flex max-h-[82vh] w-full max-w-2xl flex-col gap-3 rounded-2xl p-5 shadow-xl">
        <header className="flex items-center gap-2"><GitBranch size={16} className="text-brand" /><h2 className="m-0 flex-1 text-[16px] font-semibold text-heading">完整会话分叉树</h2><button type="button" aria-label="关闭分叉树" className="btn ghost" onClick={() => setOpen(false)}>关闭</button></header>
        <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索会话标题或 ID" aria-label="搜索分支" className="input h-9" />
        <div className="min-h-0 flex-1 overflow-auto rounded-lg bg-sunken p-2" role="tree" aria-label="会话分支列表">
          {visibleRows.map(({ item, depth }) => {
            const state = waiting.includes(item.id) ? '等待输入或审批' : running.includes(item.id) ? '运行中' : item.archived ? '已归档' : '空闲';
            return <button type="button" role="treeitem" aria-current={item.id === activeId ? 'page' : undefined} key={item.id} onClick={() => { if (item.id !== activeId) onOpen(item); setOpen(false); }} className={`flex w-full items-center gap-2 rounded-md px-2 py-2 text-left hover:bg-hover ${item.id === activeId ? 'bg-brand-soft' : ''}`} style={{ paddingLeft: 10 + depth * 20 }}>
              <i title={state} className={`size-2 shrink-0 rounded-full ${state === '运行中' ? 'animate-pulse bg-brand' : state === '等待输入或审批' ? 'bg-warning' : state === '已归档' ? 'bg-fg-3' : 'bg-fg-3/50'}`} />
              {depth > 0 && <span className="shrink-0 text-fg-3">└</span>}
              <span className="min-w-0 flex-1 truncate text-[13px] text-fg">{item.title || '未命名对话'}</span>
              <span className="shrink-0 text-[11px] text-fg-3">{state}</span>
              <code className="shrink-0 text-[10px] text-fg-3">{item.id.slice(0, 8)}</code>
            </button>;
          })}
          {!visibleRows.length && <p role="status" className="m-0 p-4 text-center text-[12px] text-fg-3">没有匹配的分支。</p>}
        </div>
      </section>
    </div>}
  </>;
}
