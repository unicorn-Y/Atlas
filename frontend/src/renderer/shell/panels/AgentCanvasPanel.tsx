import { useMemo, useState } from 'react';
import type { AgentEvent } from '../../../types/runtime';
import MermaidBlock from '../../components/MermaidBlock';
import { Empty } from './Empty';

type CanvasWidget = { id: string; title: string; format: 'mermaid' | 'html' | 'table'; content: string };

function widgetsFrom(events: AgentEvent[]): CanvasWidget[] {
  const widgets = new Map<string, CanvasWidget>();
  for (const event of events) {
    if (event.type !== 'canvas.update') continue;
    const data = event.data as Record<string, unknown>;
    const id = String(data.widget_id || 'default');
    const format = data.format;
    if (format !== 'mermaid' && format !== 'html' && format !== 'table') continue;
    const content = String(data.content || '').slice(0, 100000);
    const prior = widgets.get(id);
    widgets.set(id, {
      id, title: String(data.title || '共享画布').slice(0, 120), format,
      content: data.mode === 'append' && prior?.format === format ? `${prior.content}${content}`.slice(-100000) : content,
    });
  }
  return [...widgets.values()];
}

function TableView({ content }: { content: string }) {
  const table = useMemo(() => {
    try {
      const value = JSON.parse(content) as { columns?: unknown[]; rows?: unknown[] };
      if (!Array.isArray(value.columns) || !Array.isArray(value.rows)) return null;
      return { columns: value.columns.slice(0, 40).map(String), rows: value.rows.slice(0, 500) };
    } catch { return null; }
  }, [content]);
  if (!table) return <p role="alert" className="text-danger">表格数据格式错误；需要包含 columns 和 rows 数组的 JSON。</p>;
  return <div className="overflow-auto"><table className="w-full border-collapse text-left text-[12px]"><thead><tr>{table.columns.map((column, index) => <th key={`${index}:${column}`} className="border-b border-line bg-sunken px-2 py-1.5 font-medium text-fg">{column}</th>)}</tr></thead><tbody>{table.rows.map((row, rowIndex) => {
    const values = Array.isArray(row) ? row : table.columns.map((column) => row && typeof row === 'object' ? (row as Record<string, unknown>)[column] : '');
    return <tr key={rowIndex}>{table.columns.map((_column, columnIndex) => <td key={columnIndex} className="border-b border-line px-2 py-1.5 text-fg-2">{String(values[columnIndex] ?? '')}</td>)}</tr>;
  })}</tbody></table></div>;
}

export default function AgentCanvasPanel({ events }: { events: AgentEvent[] }) {
  const widgets = useMemo(() => widgetsFrom(events), [events]);
  const [activeId, setActiveId] = useState('');
  const current = widgets.find((widget) => widget.id === activeId) ?? widgets.at(-1);
  if (!current) return <Empty title="等待 Agent 推送画布" body="Agent 可以在任务执行时创建 Mermaid 图表、HTML 视图和数据表，并持续更新内容。" />;
  return <section className="flex h-full min-h-0 flex-col gap-3" aria-label="Agent 共享画布">
    <header className="flex min-w-0 items-center gap-2"><div className="flex min-w-0 flex-1 gap-1 overflow-x-auto" role="tablist" aria-label="共享画布列表">
      {widgets.map((widget) => <button key={widget.id} role="tab" aria-selected={widget.id === current.id} onClick={() => setActiveId(widget.id)} className={`shrink-0 rounded-md px-2.5 py-1.5 text-[12px] ${widget.id === current.id ? 'bg-brand-soft text-brand' : 'text-fg-3 hover:bg-hover'}`}>{widget.title}</button>)}
    </div><span className="shrink-0 text-[10.5px] text-fg-3">{current.format === 'mermaid' ? '图表' : current.format === 'html' ? 'HTML' : '表格'}</span></header>
    <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-line bg-surface p-3" aria-live="polite" key={`${current.id}:${current.format}`}>
      {current.format === 'mermaid' ? <MermaidBlock source={current.content} />
        : current.format === 'table' ? <TableView content={current.content} />
          : <iframe title={`共享画布：${current.title}`} sandbox="" srcDoc={current.content} className="h-full min-h-80 w-full border-0 bg-white" />}
    </div>
    <details className="shrink-0 text-[11px] text-fg-3"><summary className="cursor-pointer">查看画布源内容</summary><pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-sunken p-2 font-mono">{current.content}</pre></details>
  </section>;
}
