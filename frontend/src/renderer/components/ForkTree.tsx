import { useEffect, useState } from 'react';
import { GitBranch } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from '../ui/Menu';

export const loadConversationBranches = (
  activeId: string,
  load: typeof backend.getConversationBranches = (id) => backend.getConversationBranches(id),
) => activeId ? load(activeId) : Promise.resolve([]);

/** The family of conversations forked from one another, with the open one marked; pick any to jump. */
export default function ForkTree({ conversations, activeId, onOpen }: {
  conversations: ConversationSummary[]; activeId: string; onOpen: (conversation: ConversationSummary) => void;
}) {
  const [tree, setTree] = useState<Array<{ id: string; parent_session_id?: string | null; title: string }> | null>(null);
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
  const children = new Map<string, ConversationSummary[]>();
  for (const node of tree) {
    const item = byId.get(node.id);
    const parent = node.parent_session_id;
    if (item && parent && byId.has(parent)) children.set(parent, [...(children.get(parent) ?? []), item]);
  }
  const actualParent = treeById.get(activeId)?.parent_session_id;
  const parent = actualParent ? byId.get(actualParent) : undefined;
  if (!parent && !children.get(activeId)?.length) return null;
  let root = active;
  for (const seen = new Set<string>(); treeById.get(root.id)?.parent_session_id && byId.has(String(treeById.get(root.id)?.parent_session_id)) && !seen.has(root.id);) {
    seen.add(root.id);
    root = byId.get(String(treeById.get(root.id)?.parent_session_id))!;
  }
  const rows: Array<{ item: ConversationSummary; depth: number }> = [];
  const walk = (item: ConversationSummary, depth: number) => {
    if (rows.length > 60 || rows.some((row) => row.item.id === item.id)) return;
    rows.push({ item, depth });
    for (const child of children.get(item.id) ?? []) walk(child, depth + 1);
  };
  walk(root, 0);
  const forks = children.get(activeId)?.length ?? 0;

  return <Menu>
    <MenuTrigger asChild>
      <button title="查看分叉关系" className="no-drag inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[12px] text-fg-3 hover:bg-hover hover:text-fg">
        <GitBranch size={12} />{parent ? `分叉自 ${parent.title.slice(0, 16)}` : `${forks} 个分叉`}
      </button>
    </MenuTrigger>
    <MenuContent className="min-w-[280px] max-w-[420px]">
      <MenuLabel>分叉关系</MenuLabel>
      {rows.map(({ item, depth }) => <MenuItem key={item.id} checked={item.id === activeId} onSelect={() => { if (item.id !== activeId) onOpen(item); }}>
        <span className="flex min-w-0 items-center gap-1.5" style={{ paddingLeft: depth * 14 }}>
          {depth > 0 && <span className="shrink-0 text-fg-3">└</span>}
          <span className="truncate">{item.title || '未命名对话'}</span>
        </span>
      </MenuItem>)}
    </MenuContent>
  </Menu>;
}
