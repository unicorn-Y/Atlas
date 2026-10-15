// 子会话回报在主会话历史里的样子：一行折叠提示，点开看全文（而不是一个用户气泡）。
import { useState } from 'react';
import { ChevronRight, SplitSquareHorizontal } from 'lucide-react';
import { cn } from '../../ui/cn';

export default function SideSessionNote({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const blocks = [...content.matchAll(/<side-session-event>([\s\S]*?)<\/side-session-event>/g)].map((match) => match[1].trim());
  const titles = blocks.map((block) => /「([^」]+)」/.exec(block)?.[1]).filter(Boolean);
  return <div className="my-3 text-[12.5px] text-fg-2" role="note">
    <button className="flex items-center gap-2 hover:text-fg" aria-expanded={open} onClick={() => setOpen(!open)}>
      <SplitSquareHorizontal size={13} className="shrink-0 text-brand" />
      <span>独立会话回报{titles.length ? `：${titles.join('、')}` : ''}</span>
      <ChevronRight size={12} className={cn('transition-transform', open && 'rotate-90')} />
    </button>
    {open && <div className="mt-1.5 whitespace-pre-wrap rounded-lg bg-sunken px-3 py-2 text-fg-2">{blocks.join('\n\n') || content}</div>}
  </div>;
}
