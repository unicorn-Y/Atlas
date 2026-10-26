import { Children, isValidElement, useCallback, useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import { Maximize2, MoreHorizontal, X } from 'lucide-react';
import ClipboardAction from './ClipboardAction';
import ImagePreview from './ImagePreview';
import { useAtlasStore } from '../../store/useAtlasStore';

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
    // React 18 flushes this effect while the opening right-click is still bubbling;
    // listening right away would treat that same event as an outside click.
    const timer = window.setTimeout(() => {
      document.addEventListener('pointerdown', dismissOutside);
      document.addEventListener('contextmenu', dismissOutside);
    }, 0);
    return () => {
      window.clearTimeout(timer);
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
  const tableRoot = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [selectedRows, setSelectedRows] = useState<number[]>([]);
  const [comment, setComment] = useState('');
  const [copyTableStatus, setCopyTableStatus] = useState('');
  const active = useAtlasStore((state) => state.activeConversationId);
  const toggleRow = (event: MouseEvent<HTMLTableElement>) => {
    const row = (event.target as HTMLElement).closest('tbody tr');
    if (!row) return;
    const index = [...(row.parentElement?.children ?? [])].indexOf(row);
    row.classList.toggle('bg-brand-soft');
    setSelectedRows((current) => current.includes(index) ? current.filter((value) => value !== index) : [...current, index]);
  };
  const currentRows = () => {
    const domRows = [...(tableRoot.current?.querySelectorAll('table tr') ?? [])].map((row) => [...row.querySelectorAll('th,td')].map((cell) => cell.textContent?.trim() ?? ''));
    return domRows.length ? domRows : rows;
  };
  const exportCurrentCsv = () => downloadCsv(currentRows());
  const sendComment = async () => {
    const tableRows = currentRows();
    const selection = selectedRows.map((index) => tableRows[index + 1]).filter(Boolean);
    const excerpt = selection.length ? selection.map((row) => row.map((cell, index) => `${tableRows[0]?.[index] ?? `列${index + 1}`}: ${cell}`).join(' | ')).join('\n') : '未选择具体行';
    const instruction = `请基于这张 Markdown 表格${active ? '' : '（当前没有活动对话）'}进行修改。\n选中区域：\n${excerpt}\n\n修改意见：${comment.trim() || '请检查并提出改进建议。'}`;
    if (active) await useAtlasStore.getState().sendMessage(instruction);
    else window.dispatchEvent(new CustomEvent('atlas:add-selection-to-draft', { detail: { text: instruction } }));
    setExpanded(false); setComment(''); setSelectedRows([]);
  };
  const table = <table onClick={toggleRow} className="w-full">{children}</table>;
  return <div ref={tableRoot} className="my-3 overflow-x-auto">
    <div className="mb-1 flex justify-end">
      <button type="button" onClick={() => { setExpanded(true); setSelectedRows([]); }} aria-label="放大并批注表格" title="放大并批注表格"
        className="inline-flex min-h-7 items-center gap-1 rounded-md px-2 text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"><Maximize2 size={12} />放大与批注</button>
      <button type="button" onClick={() => { void navigator.clipboard.writeText(currentRows().map((row) => row.join('\t')).join('\n')).then(() => setCopyTableStatus('已复制完整表格（TSV）')).catch(() => setCopyTableStatus('复制表格失败')); }} aria-label="复制完整表格" title="复制完整表格"
        className="inline-flex min-h-7 items-center rounded-md px-2 text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">复制整表</button>
      {copyTableStatus && <span role="status" className="self-center text-[11px] text-fg-3">{copyTableStatus}</span>}
      <button type="button" onClick={exportCurrentCsv} aria-label="导出表格为 CSV" title="导出表格为 CSV"
        className="inline-flex min-h-7 items-center rounded-md px-2 text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand">
        导出 CSV
      </button>
    </div>
    {table}
    {expanded && createPortal(<div className="fixed inset-0 z-[100] grid place-items-center bg-black/55 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setExpanded(false); }}>
      <section role="dialog" aria-modal="true" aria-labelledby="table-dialog-title" className="flex max-h-[92vh] w-[min(1100px,96vw)] flex-col overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl">
        <header className="flex items-center gap-2 border-b border-line px-4 py-3"><Maximize2 size={15} className="text-brand"/><h2 id="table-dialog-title" className="m-0 flex-1 text-[14px] font-semibold text-heading">表格放大查看与区域批注</h2><button type="button" aria-label="关闭表格" onClick={() => setExpanded(false)} className="grid size-8 place-items-center rounded-md text-fg-3 hover:bg-hover"><X size={16}/></button></header>
        <div className="min-h-0 flex-1 overflow-auto p-4"><p className="mt-0 text-[12px] text-fg-3">点击表格行选择要讨论的区域；可多选。选择行数：{selectedRows.length}</p><div className="overflow-auto rounded-lg border border-line [&_table]:border-collapse [&_table]:text-[12px] [&_th]:sticky [&_th]:top-0 [&_th]:bg-sunken [&_th]:p-2 [&_td]:p-2 [&_td]:align-top [&_tr]:border-b [&_tr]:border-line">{table}</div>
          <label className="mt-4 grid gap-1 text-[12px] text-fg-2">区域批注<textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder="例如：把这一行的状态更新为已完成，并说明依据。" className="rounded-lg border border-line bg-surface p-2.5 text-[13px] text-fg" /></label>
        </div><footer className="flex justify-end gap-2 border-t border-line px-4 py-3"><button type="button" onClick={() => setExpanded(false)} className="rounded-lg px-3 py-1.5 text-[12px] text-fg-2 hover:bg-hover">关闭</button><button type="button" onClick={() => void sendComment()} className="rounded-lg bg-brand px-3 py-1.5 text-[12px] font-medium text-white hover:brightness-110">把区域批注发送给 Atlas</button></footer>
      </section>
    </div>, document.body)}
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
      <div className="flex shrink-0 items-center gap-0.5" role="group" aria-label="代码块显示选项">
        {(markdown || svg || diff) && <button type="button" onClick={() => setView('source')} aria-pressed={view === 'source'} title="显示源码"
          className={`inline-flex h-7 items-center rounded-md px-2 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${view === 'source' ? 'bg-hover text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg'}`}>源码</button>}
        {(markdown || svg) && <button type="button" onClick={() => setView('preview')} aria-pressed={view === 'preview'} title={svg ? '渲染 SVG 预览' : '渲染 Markdown 预览'}
          className={`inline-flex h-7 items-center rounded-md px-2 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${view === 'preview' ? 'bg-hover text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg'}`}>预览</button>}
        {diff && <button type="button" onClick={() => setView('diff')} aria-pressed={view === 'diff'} title="着色显示差异行"
          className={`inline-flex h-7 items-center rounded-md px-2 text-[11.5px] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand ${view === 'diff' ? 'bg-hover text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg'}`}>Diff</button>}
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
