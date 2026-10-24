import { useMemo } from 'react';
import { FileText, ListChecks, MessageSquareText, Search } from 'lucide-react';
import type { Artifact } from '../../../types/artifact';
import type { AgentEvent } from '../../../types/runtime';
import type { ConversationMessage } from '@atlas/backend-adapter';
import { Empty } from './Empty';

type Tab = 'artifacts' | 'activity' | 'files';
function latest(events: AgentEvent[], type: string) { return [...events].reverse().find((event) => event.type === type)?.data; }
function valueText(value: unknown): string { return typeof value === 'string' ? value : value && typeof value === 'object' ? JSON.stringify(value) : ''; }

export default function TaskOverviewPanel({ events, artifacts, messages, onTab }: {
  events: AgentEvent[]; artifacts: Artifact[]; messages: ConversationMessage[]; onTab: (tab: Tab) => void;
}) {
  const plan = useMemo(() => {
    const data = latest(events, 'run.plan.updated') ?? latest(events, 'run.plan.proposed');
    const plan = data?.plan && typeof data.plan === 'object' ? data.plan as Record<string, unknown> : undefined;
    const planValue = plan?.subtasks ?? plan?.steps ?? data?.subtasks ?? data?.steps;
    if (Array.isArray(planValue)) return planValue.map((item, index) => typeof item === 'string' ? { id: String(index), title: item, state: '' } : {
      id: String((item as Record<string, unknown>).id ?? index), title: String((item as Record<string, unknown>).title ?? (item as Record<string, unknown>).description ?? ''),
      state: String((item as Record<string, unknown>).status ?? ''),
    }).filter((item) => item.title);
    const todos = latest(events, 'run.todos')?.todos;
    return Array.isArray(todos) ? todos.map((item, index) => ({ id: String((item as Record<string, unknown>).id ?? index), title: String((item as Record<string, unknown>).text ?? ''), state: String((item as Record<string, unknown>).state ?? '') })) : [];
  }, [events]);
  const sources = useMemo(() => events.filter((event) => event.type === 'tool.started' || event.type === 'tool.completed')
    .filter((event) => /read|search|file|browser|web|reference|source/i.test(String(event.data.name ?? '')))
    .map((event) => {
      const args = (event.data.arguments ?? event.data.input ?? {}) as Record<string, unknown>;
      const execution = event.data.execution as Record<string, unknown> | undefined;
      const locator = args.path ?? args.file ?? args.url ?? args.query ?? args.pattern ?? execution?.command;
      return { id: event.id, name: String(event.data.name ?? '来源'), locator: valueText(locator) || valueText(event.data.result).slice(0, 180) };
    }).filter((item, index, all) => item.locator && all.findIndex((candidate) => candidate.name === item.name && candidate.locator === item.locator) === index), [events]);
  const summary = [...messages].reverse().find((message) => message.role === 'assistant' && message.content.trim())?.content ?? '';
  const generated = artifacts.length ? artifacts : events.filter((event) => event.type === 'artifact.updated').map((event) => ({
    id: event.id, runId: event.runId, type: 'file' as const, name: String(event.data.name ?? event.data.path ?? '生成文件'),
    path: typeof event.data.path === 'string' ? event.data.path : undefined, summary: String(event.data.summary ?? ''), createdAt: event.timestamp,
  }));
  return <div className="grid gap-4">
    <section className="rounded-xl bg-sunken p-3">
      <div className="mb-2 flex items-center gap-2"><ListChecks size={14} className="text-brand" /><h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg-2">当前计划</h3><button onClick={() => onTab('activity')} className="text-[11.5px] text-brand">查看活动 →</button></div>
      {plan.length ? <ol className="m-0 grid list-none gap-1.5 p-0">{plan.map((item) => <li key={item.id} className="flex gap-2 text-[12px] text-fg-2"><span className="text-brand">•</span><span className="min-w-0 flex-1">{item.title}</span><small className="text-fg-3">{item.state}</small></li>)}</ol> : <p className="m-0 text-[12px] text-fg-3">当前运行还没有发布计划或待办事件。</p>}
    </section>
    <section className="rounded-xl bg-sunken p-3">
      <div className="mb-2 flex items-center gap-2"><Search size={14} className="text-brand" /><h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg-2">来源与依据</h3><button onClick={() => onTab('activity')} className="text-[11.5px] text-brand">定位活动 →</button></div>
      {sources.length ? <ul className="m-0 grid list-none gap-1 p-0">{sources.slice(-30).map((source) => <li key={source.id} className="min-w-0 text-[11.5px] text-fg-2"><b>{source.name}</b><span className="ml-1 break-all text-fg-3">{source.locator}</span></li>)}</ul> : <p className="m-0 text-[12px] text-fg-3">工具读取、搜索或浏览活动会记录为来源依据。</p>}
    </section>
    <section className="rounded-xl bg-sunken p-3">
      <div className="mb-2 flex items-center gap-2"><FileText size={14} className="text-brand" /><h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg-2">生成文件 · {generated.length}</h3><button onClick={() => onTab('artifacts')} className="text-[11.5px] text-brand">查看产物 →</button><button onClick={() => onTab('files')} className="text-[11.5px] text-brand">浏览文件 →</button></div>
      {generated.length ? <ul className="m-0 grid list-none gap-1 p-0">{generated.map((artifact) => <li key={artifact.id} className="break-all text-[11.5px] text-fg-2">{artifact.name}{artifact.path && <span className="ml-1 text-fg-3">{artifact.path}</span>}{artifact.summary && <p className="m-0 text-fg-3">{artifact.summary}</p>}</li>)}</ul> : <p className="m-0 text-[12px] text-fg-3">本次运行还没有登记产物。</p>}
    </section>
    <section className="rounded-xl bg-sunken p-3">
      <div className="mb-2 flex items-center gap-2"><MessageSquareText size={14} className="text-brand" /><h3 className="m-0 flex-1 text-[12.5px] font-semibold text-fg-2">会话摘要</h3></div>
      {summary ? <p className="m-0 whitespace-pre-wrap text-[12px] leading-[1.65] text-fg-2">{summary.slice(-1800)}</p> : <Empty title="还没有回复摘要" body="运行产出的最新回复会显示在这里。" />}
    </section>
  </div>;
}
