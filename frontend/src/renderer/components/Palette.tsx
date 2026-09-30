import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { MessageSquare, Search } from 'lucide-react';
import { Dialog } from '../ui/Dialog';
import { Kbd } from '../ui/Kbd';
import { cn } from '../ui/cn';

export interface PaletteItem {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  run: () => void;
}

export default function Palette({ items, open, onClose, search }: {
  items: PaletteItem[]; open: boolean; onClose: () => void;
  /** Extra results fetched for the query, e.g. full-text hits inside conversations. */
  search?: (query: string) => Promise<PaletteItem[]>;
}) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const [found, setFound] = useState<PaletteItem[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = q ? items.filter((item) => `${item.label} ${item.hint ?? ''}`.toLowerCase().includes(q)) : items;
    return [...matched.slice(0, 40), ...found];
  }, [items, query, found]);
  useEffect(() => {
    const q = query.trim();
    setFound([]);
    if (!search || q.length < 2) return;
    let stale = false;
    const timer = window.setTimeout(() => { void search(q).then((hits) => { if (!stale) setFound(hits); }).catch(() => undefined); }, 250);
    return () => { stale = true; window.clearTimeout(timer); };
  }, [query, search]);
  useEffect(() => setCursor(0), [query]);
  useEffect(() => { if (!open) setQuery(''); }, [open]);
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  const choose = (item?: PaletteItem) => { if (!item) return; onClose(); item.run(); };
  let lastGroup = '';

  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} label="搜索与命令" align="top" className="w-[min(620px,calc(100vw-32px))]">
    <label className="flex h-14 items-center gap-3 px-5 text-fg-3 shadow-[inset_0_-1px_0_var(--line)]">
      <Search size={18} />
      <input autoFocus value={query} placeholder="搜索对话、页面或命令" aria-label="搜索对话、页面或命令"
        className="min-w-0 flex-1 border-0 bg-transparent text-[15px] text-fg outline-none placeholder:text-fg-3"
        onChange={(event) => setQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown') { event.preventDefault(); setCursor((value) => Math.min(results.length - 1, value + 1)); }
          else if (event.key === 'ArrowUp') { event.preventDefault(); setCursor((value) => Math.max(0, value - 1)); }
          else if (event.key === 'Enter') { event.preventDefault(); choose(results[cursor]); }
        }} />
    </label>
    <div className="max-h-[52vh] overflow-auto p-1.5" role="listbox" ref={listRef}>
      {results.map((item, index) => {
        const header = item.group !== lastGroup ? <div className="px-3 pt-2.5 pb-1 text-[12px] text-fg-3">{item.group}</div> : null;
        lastGroup = item.group;
        return <div key={item.id}>{header}
          <button role="option" aria-selected={index === cursor} onMouseMove={() => setCursor(index)} onClick={() => choose(item)}
            className={cn('flex w-full items-center gap-3 rounded-[10px] px-3 py-2 text-left text-[13.5px] text-fg [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-fg-3',
              index === cursor && 'bg-selected')}>
            {item.icon ?? <MessageSquare />}<span className="min-w-0 truncate">{item.label}</span>{item.hint && <span className="ml-auto shrink-0 text-[12px] text-fg-3">{item.hint}</span>}
          </button>
        </div>;
      })}
      {!results.length && <div className="px-5 py-8 text-center text-[13.5px] text-fg-3"><b className="mb-1 block font-medium text-fg">没有匹配的结果</b>换个关键词试试。</div>}
    </div>
    <div className="flex gap-4 px-5 py-2.5 text-[12px] text-fg-3 shadow-[inset_0_1px_0_var(--line)]">
      <span className="flex items-center gap-1"><Kbd>↑</Kbd><Kbd>↓</Kbd>选择</span>
      <span className="flex items-center gap-1"><Kbd>Enter</Kbd>打开</span>
      <span className="flex items-center gap-1"><Kbd>Esc</Kbd>关闭</span>
    </div>
  </Dialog>;
}
