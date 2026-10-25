import { Check, Circle, LoaderCircle, Table2 } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';

type ComponentStore = { sendMessage: (content: string) => Promise<unknown> };
export type StructuredComponentItem = { id: string; title: string; kind: 'progress' | 'table' | 'metrics' | 'buttons'; data: Record<string, unknown> };
function record(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
export function structuredComponent(event: AgentEvent): StructuredComponentItem | null {
  const data = event.data; const kind = data.kind;
  if (typeof data.title !== 'string' || !['progress', 'table', 'metrics', 'buttons'].includes(String(kind))) return null;
  const payload = record(data.data);
  if (JSON.stringify(payload).length > 24000) return null;
  if (kind === 'progress' && (!Array.isArray(payload.steps) || payload.steps.length > 40 || payload.steps.some((step) => !record(step).label || !['pending', 'active', 'done', 'error'].includes(String(record(step).status))))) return null;
  if (kind === 'table' && (!Array.isArray(payload.columns) || payload.columns.length < 1 || payload.columns.length > 20 || payload.columns.some((column) => typeof column !== 'string') || !Array.isArray(payload.rows) || payload.rows.length > 200)) return null;
  if (kind === 'metrics' && (!Array.isArray(payload.metrics) || payload.metrics.length > 20 || payload.metrics.some((metric) => typeof record(metric).label !== 'string'))) return null;
  if (kind === 'buttons' && (!Array.isArray(payload.buttons) || payload.buttons.length < 1 || payload.buttons.length > 8 || payload.buttons.some((button) => typeof record(button).label !== 'string' || typeof record(button).value !== 'string'))) return null;
  return { id: String(data.component_id ?? event.id), title: data.title.slice(0, 120), kind: kind as StructuredComponentItem['kind'], data: payload };
}

/** Renderer for the deliberately small, text-only agent component contract. */
export default function StructuredComponentCard({ item, store }: { item: StructuredComponentItem; store: ComponentStore }) {
  const data = item.data;
  return <section aria-label={item.title} className="my-3 overflow-hidden rounded-xl border border-line bg-panel">
    <header className="flex items-center gap-2 border-b border-line px-3.5 py-2.5"><Table2 size={14} className="text-brand" /><h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg">{item.title}</h3><span className="text-[10px] text-fg-3">{item.kind}</span></header>
    {item.kind === 'progress' && <ol className="m-0 grid list-none gap-2 p-3.5">{(Array.isArray(data.steps) ? data.steps : []).map((raw, index) => { const step = record(raw); const status = String(step.status); return <li key={`${index}:${String(step.label)}`} className="flex items-center gap-2 text-[12px] text-fg-2">{status === 'done' ? <Check size={14} className="text-ok" /> : status === 'active' ? <LoaderCircle size={14} className="animate-spin text-brand" /> : <Circle size={14} className={status === 'error' ? 'text-danger' : 'text-fg-3'} />}<span>{String(step.label ?? '')}</span></li>; })}</ol>}
    {item.kind === 'table' && <div className="max-h-72 overflow-auto"><table className="w-full border-collapse text-left text-[11.5px]"><thead><tr>{(Array.isArray(data.columns) ? data.columns : []).map((column, index) => <th key={index} className="sticky top-0 border-b border-line bg-sunken px-2.5 py-2 font-medium text-fg">{String(column)}</th>)}</tr></thead><tbody>{(Array.isArray(data.rows) ? data.rows : []).map((raw, rowIndex) => { const values = Array.isArray(raw) ? raw : record(raw); return <tr key={rowIndex}>{(data.columns as unknown[]).map((column, columnIndex) => <td key={columnIndex} className="border-b border-line px-2.5 py-1.5 text-fg-2">{String(Array.isArray(values) ? values[columnIndex] ?? '' : values[String(column)] ?? '')}</td>)}</tr>; })}</tbody></table></div>}
    {item.kind === 'metrics' && <dl className="m-0 grid grid-cols-2 gap-2 p-3.5 sm:grid-cols-3">{(Array.isArray(data.metrics) ? data.metrics : []).map((raw, index) => { const metric = record(raw); return <div key={index} className="rounded-lg bg-sunken px-3 py-2"><dt className="text-[10.5px] text-fg-3">{String(metric.label ?? '')}</dt><dd className="m-0 mt-1 break-words text-[16px] font-semibold tabular-nums text-fg">{String(metric.value ?? '')}</dd>{typeof metric.note === 'string' && <small className="text-fg-3">{metric.note}</small>}</div>; })}</dl>}
    {item.kind === 'buttons' && <div className="flex flex-wrap gap-2 p-3.5">{(Array.isArray(data.buttons) ? data.buttons : []).map((raw, index) => { const button = record(raw); const label = String(button.label ?? '').slice(0, 80); const value = String(button.value ?? '').slice(0, 1000); return <button key={index} type="button" className="rounded-lg border border-line bg-surface px-3 py-1.5 text-[12px] text-fg hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand" onClick={() => void store.sendMessage(`结构化卡片「${item.title}」选择：${label}\n${value}`)}>{label}</button>; })}</div>}
  </section>;
}
