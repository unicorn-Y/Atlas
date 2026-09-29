import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { MessageSquare, Search } from 'lucide-react';

export interface PaletteItem {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon?: ReactNode;
  run: () => void;
}

export default function Palette({ items, onClose }: { items: PaletteItem[]; onClose: () => void }) {
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    const matched = q ? items.filter((item) => `${item.label} ${item.hint ?? ''}`.toLowerCase().includes(q)) : items;
    return matched.slice(0, 40);
  }, [items, query]);
  useEffect(() => setCursor(0), [query]);
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }, [cursor]);

  const choose = (item?: PaletteItem) => { if (!item) return; onClose(); item.run(); };
  let lastGroup = '';

  return <div className="scrim" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="palette glass" role="dialog" aria-modal="true" aria-label="搜索与命令">
      <label className="field"><Search size={18} />
        <input autoFocus value={query} placeholder="搜索对话、页面或命令" aria-label="搜索对话、页面或命令"
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'ArrowDown') { event.preventDefault(); setCursor((value) => Math.min(results.length - 1, value + 1)); }
            else if (event.key === 'ArrowUp') { event.preventDefault(); setCursor((value) => Math.max(0, value - 1)); }
            else if (event.key === 'Enter') { event.preventDefault(); choose(results[cursor]); }
            else if (event.key === 'Escape') { event.preventDefault(); onClose(); }
          }} />
      </label>
      <div className="res" role="listbox" ref={listRef}>
        {results.map((item, index) => {
          const header = item.group !== lastGroup ? <h5>{item.group}</h5> : null;
          lastGroup = item.group;
          return <div key={item.id}>{header}
            <button className="it" role="option" aria-selected={index === cursor} onMouseMove={() => setCursor(index)} onClick={() => choose(item)}>
              {item.icon ?? <MessageSquare size={16} />}<span>{item.label}</span>{item.hint && <small>{item.hint}</small>}
            </button>
          </div>;
        })}
        {!results.length && <div className="empty"><b>没有匹配的结果</b>换个关键词试试，或按 Esc 关闭。</div>}
      </div>
      <div className="foot"><span><kbd>↑</kbd><kbd>↓</kbd>选择</span><span><kbd>Enter</kbd>打开</span><span><kbd>Esc</kbd>关闭</span></div>
    </div>
  </div>;
}
