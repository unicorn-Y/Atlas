import { GitBranch } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { Menu, MenuContent, MenuItem, MenuLabel, MenuTrigger } from '../ui/Menu';

/** The family of conversations forked from one another, with the open one marked; pick any to jump. */
export default function ForkTree({ conversations, activeId, onOpen }: {
  conversations: ConversationSummary[]; activeId: string; onOpen: (conversation: ConversationSummary) => void;
}) {
  const byId = new Map(conversations.map((item) => [item.id, item]));
  const active = byId.get(activeId);
  if (!active) return null;
  const children = new Map<string, ConversationSummary[]>();
  for (const item of conversations) {
    const parent = item.parent_conversation_id;
    if (parent && byId.has(parent)) children.set(parent, [...(children.get(parent) ?? []), item]);
  }
  const parent = active.parent_conversation_id ? byId.get(active.parent_conversation_id) : undefined;
  if (!parent && !children.get(activeId)?.length) return null;
  let root = active;
  for (const seen = new Set<string>(); root.parent_conversation_id && byId.has(root.parent_conversation_id) && !seen.has(root.id);) {
    seen.add(root.id);
    root = byId.get(root.parent_conversation_id)!;
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
