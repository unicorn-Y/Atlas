import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { cn } from '../ui/cn';

/** Open conversations as tabs in the title bar; the running ones carry a dot. */
export default function TabStrip({ tabs, conversations, activeId, running, onSelect, onClose }: {
  tabs: string[]; conversations: ConversationSummary[]; activeId: string; running: string[];
  onSelect: (conversation: ConversationSummary) => void; onClose: (id: string) => void;
}) {
  const byId = new Map(conversations.map((item) => [item.id, item]));
  const open = tabs.map((id) => byId.get(id)).filter((item): item is ConversationSummary => Boolean(item));
  const listRef = useRef<HTMLDivElement>(null);
  // Tabs shrink first; when there are too many, keep the active one scrolled into view.
  useEffect(() => { listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' }); }, [activeId, tabs.length]);
  return <div ref={listRef} role="tablist" aria-label="打开的对话" className="no-drag flex min-w-0 items-center gap-0.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
    {open.map((conversation) => {
      const active = conversation.id === activeId;
      return <div key={conversation.id} role="tab" aria-selected={active} tabIndex={active ? 0 : -1}
        onClick={() => { if (!active) onSelect(conversation); }}
        onAuxClick={(event) => { if (event.button === 1) { event.preventDefault(); onClose(conversation.id); } }}
        onKeyDown={(event) => { if (event.key === 'Enter' && !active) onSelect(conversation); }}
        title={conversation.title}
        className={cn('group flex h-7 min-w-[72px] shrink grow-0 basis-[200px] cursor-default items-center gap-1.5 rounded-lg pr-1 pl-2.5 text-[12.5px]',
          active ? 'bg-selected text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg-2')}>
        {running.includes(conversation.id) && <span aria-label="运行中" className="size-1.5 shrink-0 rounded-full bg-brand" />}
        <span className="min-w-0 flex-1 truncate">{conversation.title || '新任务'}</span>
        <button aria-label={`关闭「${conversation.title}」`} onClick={(event) => { event.stopPropagation(); onClose(conversation.id); }}
          className={cn('grid size-5 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg', active ? 'opacity-100' : 'opacity-0 group-hover:opacity-100')}><X size={12} /></button>
      </div>;
    })}
  </div>;
}
