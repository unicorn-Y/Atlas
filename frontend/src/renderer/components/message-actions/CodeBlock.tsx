import { Children, isValidElement, useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import { MoreHorizontal } from 'lucide-react';
import ClipboardAction from './ClipboardAction';
import ImagePreview from './ImagePreview';

export type ContextAction = { id: string; label: string; onSelect: () => void | Promise<void>; restoreFocus?: boolean };
type ContextMenuCloseReason = 'escape' | 'select' | 'outside' | 'tab';

export function AccessibleContextMenu({ label, items, x, y, onClose, restoreFocus }: {
  label: string;
  items: ContextAction[];
  x: number;
  y: number;
  onClose: (reason: ContextMenuCloseReason) => void;
  restoreFocus: () => void;
}) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState('');
  const estimatedHeight = Math.min(items.length * 36 + 16, window.innerHeight - 16);
  const left = Math.max(8, Math.min(x, window.innerWidth - 248));
  const top = Math.max(8, Math.min(y, window.innerHeight - estimatedHeight - 8));

  useEffect(() => {
    const first = menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)');
    first?.focus();
    const dismissOutside = (event: Event) => {
      if (!menuRef.current?.contains(event.target as Node)) onClose('outside');
    };
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('contextmenu', dismissOutside);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('contextmenu', dismissOutside);
    };
  }, [onClose]);

  const close = (reason: ContextMenuCloseReason, shouldRestoreFocus = reason !== 'outside') => {
    onClose(reason);
    if (shouldRestoreFocus) requestAnimationFrame(restoreFocus);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const buttons = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)') ?? []);
    if (!buttons.length) return;
    const active = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      close('escape');
    } else if (event.key === 'Tab') {
      event.preventDefault();
      close('tab');
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp' || event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      const next = event.key === 'Home' ? 0
        : event.key === 'End' ? buttons.length - 1
          : (active + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
    }
  };

  const select = async (item: ContextAction) => {
    try {
      await item.onSelect();
      close('select', item.restoreFocus !== false);
    } catch {
      setError('操作失败，请重试。');
    }
  };

  return createPortal(<div ref={menuRef} role="menu" aria-label={label} onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); }} onKeyDown={onKeyDown}
    style={{ position: 'fixed', left, top, zIndex: 120 }}
    className="min-w-56 rounded-xl border border-line bg-overlay p-1.5 text-[12.5px] text-fg shadow-xl">
    {items.map((item) => <button key={item.id} type="button" role="menuitem" onClick={() => void select(item)}
      className="flex min-h-8 w-full items-center rounded-lg px-2.5 text-left hover:bg-hover focus-visible:bg-hover focus-visible:outline-none">
      {item.label}
    </button>)}
    {error && <span role="alert" className="block px-2.5 py-1.5 text-danger">{error}</span>}
  </div>, document.body);
}

function markdownCellText(node: ReactNode): string {
  let output = '';
  const visit = (value: ReactNode) => {
    Children.forEach(value, (child) => {
      if (typeof child === 'string' || typeof child === 'number') output += child;
      else if (isValidElement<{ children?: ReactNode }>(child)) {
        if (child.type === 'br') output += '\n';
        else visit(child.props.children);
      }
    });
  };
  visit(node);
  return output;
}

function markdownTableRows(node: ReactNode): string[][] {
  const rows: string[][] = [];
  const visit = (value: ReactNode) => {
    Children.forEach(value, (child) => {
      if (!isValidElement<{ children?: ReactNode }>(child)) return;
      if (child.type === 'tr') {
        const cells: string[] = [];
        Children.forEach(child.props.children, (cell) => {
          if (isValidElement<{ children?: ReactNode }>(cell) && (cell.type === 'th' || cell.type === 'td')) {
            cells.push(markdownCellText(cell.props.children));
          }
        });
        if (cells.length) rows.push(cells);
        return;
      }
      visit(child.props.children);
    });
  };
  visit(node);
  return rows;
}

function csvField(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

function downloadCsv(rows: string[][]): void {
  const csv = `\uFEFF${rows.map((row) => row.map(csvField).join(',')).join('\r\n')}`;
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `markdown-table-${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
  anchor.rel = 'noopener';
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function CsvMarkdownTable({ children }: { children?: ReactNode }) {
  const rows = markdownTableRows(children);
  return <div className="my-3 overflow-x-auto">
    {rows.length > 0 && <div className="mb-1 flex justify-end">
      <button type="button" onClick={() => downloadCsv(rows)} aria-label="导出表格为 CSV" title="导出表格为 CSV"
        className="inline-flex min-h-7 items-center rounded-md px-2 text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">
        导出 CSV
      </button>
    </div>}
    <table>{children}</table>
  </div>;
}

function DiffPreview({ source, wrap }: { source: string; wrap: boolean }) {
  return <pre className="m-0 overflow-x-auto rounded-none border-0 bg-transparent px-4 py-3 font-mono text-fg-2 shadow-none"
    style={{ whiteSpace: wrap ? 'pre-wrap' : 'pre', overflowWrap: wrap ? 'anywhere' : 'normal' }} aria-label="差异源码">
    {source.split(/(?<=\n)/).map((line, index) => {
      const prefix = line.startsWith('+') && !line.startsWith('+++')
        ? 'bg-ok-soft text-ok'
        : line.startsWith('-') && !line.startsWith('---')
          ? 'bg-danger-soft text-danger'
          : line.startsWith('@@')
            ? 'text-brand'
            : '';
      return <span key={index} className={`block ${prefix}`}>{line}</span>;
    })}
  </pre>;
}

/** Code block controls for copying the source and choosing readable soft wrapping. */
export default function CodeBlock({ source, language, children }: {
  source: string;
  language?: string;
  children?: ReactNode;
}) {
  const [wrap, setWrap] = useState(false);
  const [fontScale, setFontScale] = useState(1);
  const [view, setView] = useState<'source' | 'preview' | 'diff'>('source');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const contextTriggerRef = useRef<HTMLButtonElement>(null);
  const markdown = /^(?:markdown|md)$/i.test(language ?? '');
  const svg = /^(?:svg|image\/svg\+xml)$/i.test(language ?? '');
  const diff = /^(?:diff|patch)$/i.test(language ?? '');
  const contextActions: ContextAction[] = [
    ...(source ? [
      { id: 'copy', label: '复制代码', onSelect: () => navigator.clipboard.writeText(source) },
      ...(view !== 'source' ? [{ id: 'source', label: '查看源码', onSelect: () => setView('source') }] : []),
      ...(markdown && view !== 'preview' ? [{ id: 'preview', label: '查看 Markdown 预览', onSelect: () => setView('preview') }] : []),
      ...(svg && view !== 'preview' ? [{ id: 'preview', label: '查看 SVG 预览', onSelect: () => setView('preview') }] : []),
      ...(diff && view !== 'diff' ? [{ id: 'diff', label: '查看 Diff', onSelect: () => setView('diff') }] : []),
      ...((view === 'source' || view === 'diff') ? [{ id: 'wrap', label: wrap ? '关闭自动换行' : '自动换行', onSelect: () => setWrap((current) => !current) }] : []),
      ...(fontScale > 0 ? [{ id: 'font-smaller', label: '缩小代码字体', onSelect: () => setFontScale((value) => Math.max(0, value - 1)) }] : []),
      ...(fontScale < 4 ? [{ id: 'font-larger', label: '放大代码字体', onSelect: () => setFontScale((value) => Math.min(4, value + 1)) }] : []),
    ] : []),
  ];
  const closeContextMenu = useCallback(() => setContextMenu(null), []);
  const openContextMenu = (event: MouseEvent<HTMLElement>) => {
    if (!contextActions.length || (event.target instanceof Element && event.target.closest('a, button, input, textarea, [role="menu"]'))) return;
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({ x: event.clientX, y: event.clientY });
  };
  const openContextMenuFromButton = () => {
    const rect = contextTriggerRef.current?.getBoundingClientRect();
    if (rect && contextActions.length) setContextMenu({ x: rect.left, y: rect.bottom + 4 });
  };

  return <div className="mb-4 overflow-hidden rounded-[10px] bg-[var(--code-bg)] shadow-[inset_0_0_0_1px_var(--line)]" onContextMenu={openContextMenu}>
    <div className="flex min-h-9 items-center justify-between gap-3 border-b border-line px-2.5 pl-4">
      <span className="min-w-0 truncate font-sans text-[11px] text-fg-3">{language || '代码'}</span>
      <div className="flex shrink-0 items-center gap-1" role="group" aria-label="代码块显示选项">
        <button type="button" onClick={() => setView('source')} aria-pressed={view === 'source'} title="显示源码"
          className={`inline-flex h-7 items-center rounded-md px-2 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${view === 'source' ? 'bg-hover text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg'}`}>源码</button>
        {(markdown || svg) && <button type="button" onClick={() => setView('preview')} aria-pressed={view === 'preview'} title={svg ? '渲染 SVG 预览' : '渲染 Markdown 预览'}
          className={`inline-flex h-7 items-center rounded-md px-2 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${view === 'preview' ? 'bg-hover text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg'}`}>预览</button>}
        {diff && <button type="button" onClick={() => setView('diff')} aria-pressed={view === 'diff'} title="着色显示差异行"
          className={`inline-flex h-7 items-center rounded-md px-2 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${view === 'diff' ? 'bg-hover text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg'}`}>Diff</button>}
        {(view === 'source' || view === 'diff') && <button type="button" onClick={() => setWrap((current) => !current)} aria-pressed={wrap}
          title={wrap ? '关闭自动换行' : '自动换行'}
          className="inline-flex h-7 items-center rounded-md px-2 text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">
          {wrap ? '关闭换行' : '自动换行'}
        </button>}
        <button type="button" aria-label="缩小代码字体" title="缩小代码字体" disabled={fontScale <= 0}
          onClick={() => setFontScale((value) => Math.max(0, value - 1))}
          className="inline-flex h-7 items-center rounded-md px-1.5 text-[11px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand disabled:opacity-40">A−</button>
        <button type="button" aria-label="放大代码字体" title="放大代码字体" disabled={fontScale >= 4}
          onClick={() => setFontScale((value) => Math.min(4, value + 1))}
          className="inline-flex h-7 items-center rounded-md px-1.5 text-[13px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand disabled:opacity-40">A+</button>
        <ClipboardAction text={source} label="复制代码" />
        {contextActions.length > 0 && <button ref={contextTriggerRef} type="button" aria-label="更多代码操作" title="更多代码操作"
          aria-haspopup="menu" aria-expanded={Boolean(contextMenu)} onClick={openContextMenuFromButton}
          className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">
          <MoreHorizontal size={14} />
        </button>}
      </div>
    </div>
    {view === 'preview' && svg
      ? <div className="grid max-h-[28rem] min-h-40 place-items-center overflow-auto bg-white p-4">
        <iframe title="SVG 源码预览" sandbox="" srcDoc={`<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><style>html,body{margin:0;min-width:100%;min-height:100%;display:grid;place-items:center}svg{max-width:100%;max-height:26rem}</style></head><body>${source}</body></html>`}
          className="h-[26rem] w-full border-0" />
      </div>
      : view === 'preview' && markdown
      ? <div className="prose-atlas max-h-[28rem] overflow-auto px-4 py-3" style={{ fontSize: `${12 + fontScale}px` }}>
        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={{
          img: ({ src, alt, title }) => <ImagePreview src={src} alt={alt} title={title} />,
          table: CsvMarkdownTable,
        }}>{source}</ReactMarkdown>
      </div>
      : view === 'diff' && diff
        ? <div style={{ fontSize: `${12 + fontScale}px` }}><DiffPreview source={source} wrap={wrap} /></div>
        : <pre className="m-0 overflow-x-auto rounded-none border-0 bg-transparent px-4 py-3 shadow-none"
          style={{ whiteSpace: wrap ? 'pre-wrap' : 'pre', overflowWrap: wrap ? 'anywhere' : 'normal', fontSize: `${12 + fontScale}px` }}>
          {children}
        </pre>}
    {contextMenu && <AccessibleContextMenu label="代码操作" items={contextActions} x={contextMenu.x} y={contextMenu.y}
      onClose={closeContextMenu} restoreFocus={() => contextTriggerRef.current?.focus()} />}
  </div>;
}
