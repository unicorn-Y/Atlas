import { useMemo, useState } from 'react';
import { Check, ChevronRight, FileText, ShieldAlert, X } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import ConversationMessage from './ConversationMessage';
import Mark from './Mark';
import { buildTimeline, describeTool, duration, type Step } from './timeline';

type InspectorTab = 'context' | 'artifacts' | 'activity';

interface ConversationActivityProps {
  events: AgentEvent[];
  store: ReturnType<typeof useAtlasStore.getState>;
  username: string;
  setTab: (tab: InspectorTab) => void;
}

export default function ConversationActivity({ events, store, username, setTab }: ConversationActivityProps) {
  const items = useMemo(() => buildTimeline(events), [events]);
  const busy = store.busy && !store.paused;
  // Each Atlas turn shows its header once; later steps and replies in the same turn hang beneath it.
  let headed = false;
  return <>{items.map((item, index) => {
    const last = index === items.length - 1;
    if (item.kind === 'user') headed = false;
    const firstInTurn = item.kind !== 'user' && !headed;
    if (item.kind !== 'user') headed = true;
    switch (item.kind) {
      case 'user': return <ConversationMessage key={item.id} role="user" content={item.content} username={username} />;
      case 'reply': return <ConversationMessage key={item.id} role="assistant" content={item.content} username={username} continued={!firstInTurn}
        status={item.streaming ? '正在回复' : undefined} working={item.streaming && busy} />;
      case 'steps': return <div key={item.id}>
        {firstInTurn && <TurnHeader working={last && busy} />}
        <StepTrack steps={item.steps} live={last && busy} />
      </div>;
      case 'artifact': return <div key={item.id} className="my-3 ml-10 flex items-center gap-3 rounded-xl card-surface px-3.5 py-2.5 text-[13px]">
        <FileText size={16} className="shrink-0 text-brand" />
        <div className="min-w-0 flex-1"><b className="font-medium text-fg">{item.name}</b>{item.summary && <p className="m-0 truncate text-fg-3">{item.summary}</p>}</div>
        <Button size="sm" variant="ghost" onClick={() => setTab('artifacts')}>查看</Button>
      </div>;
      case 'approval': return <Approval key={item.id} event={item.event} store={store} />;
      case 'done': return <div key={item.id} className="my-4 ml-10 flex items-center gap-2 text-[12.5px] text-fg-3">
        <Check size={14} className="text-ok" />完成{item.startedAt ? `，用时 ${duration(item.startedAt, item.endedAt)}` : ''}
        <button className="ml-2 text-fg-2 underline decoration-line-strong underline-offset-[3px] hover:text-fg" onClick={() => setTab('activity')}>全部步骤</button>
      </div>;
      case 'failed': return <div key={item.id} role="alert" className="my-4 ml-10 rounded-xl bg-danger-soft px-4 py-3 text-[13px] text-danger">
        没能完成：{item.detail}
      </div>;
      default: return null;
    }
  })}</>;
}

function TurnHeader({ working }: { working: boolean }) {
  return <div className="mt-5 grid grid-cols-[28px_minmax(0,1fr)] items-center gap-3">
    <Mark className="size-[26px]" working={working} />
    <div className="flex items-baseline gap-2.5">
      <b className="font-serif text-[14px] font-semibold tracking-[.04em] text-heading">Atlas</b>
      {working && <span className="text-[12px] text-fg-3">正在处理</span>}
    </div>
  </div>;
}

/** The "航迹": each step Atlas took, in plain words, strung along a brass meridian line. */
function StepTrack({ steps, live }: { steps: Step[]; live: boolean }) {
  return <ol className="relative my-3 ml-[13px] list-none border-l border-line-strong py-1 pl-[26px]" aria-label="Atlas 的步骤">
    {steps.map((step) => <StepRow key={step.id} step={step} live={live} />)}
  </ol>;
}

function StepRow({ step, live }: { step: Step; live: boolean }) {
  const [open, setOpen] = useState(false);
  const running = step.state === 'running' && live;
  const detail = [step.input && `输入\n${step.input}`, step.result && `结果\n${step.result}`, step.output && `输出\n${step.output}`].filter(Boolean).join('\n\n');
  return <li className="relative py-[5px]">
    <span className={cn('absolute -left-[31px] top-[11px] size-[9px] rounded-full ring-4 ring-[var(--sheet-solid)]',
      running ? 'bg-brand shadow-[0_0_0_4px_var(--brand-soft)]' : step.state === 'failed' ? 'bg-danger' : step.state === 'cancelled' ? 'bg-fg-3' : 'bg-ok')} />
    <button type="button" onClick={() => detail && setOpen((value) => !value)} aria-expanded={detail ? open : undefined}
      className={cn('group flex w-full items-baseline gap-2 rounded-lg px-2 py-0.5 -mx-2 text-left text-[13.5px]', detail && 'hover:bg-hover')}>
      <span className={cn('shrink-0', step.state === 'failed' ? 'text-danger' : 'text-fg')}>{running ? `正在${step.verb}` : step.verb}</span>
      {step.target && <code className="min-w-0 truncate rounded-[5px] bg-code px-1.5 font-mono text-[12px] text-fg-2">{step.target}</code>}
      <span className="flex-1" />
      <span className="shrink-0 text-[12px] tabular-nums text-fg-3">
        {step.state === 'failed' ? '失败' : step.state === 'cancelled' ? '已取消' : running ? '进行中' : duration(step.startedAt, step.endedAt)}
      </span>
      {detail && <ChevronRight size={13} className={cn('shrink-0 self-center text-fg-3 transition-transform', open && 'rotate-90')} />}
    </button>
    {open && <pre className="anim-fade mt-1.5 mb-1 max-h-72 overflow-auto rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] whitespace-pre-wrap text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">{detail}</pre>}
  </li>;
}

function Approval({ event, store }: { event: AgentEvent; store: ReturnType<typeof useAtlasStore.getState> }) {
  const [details, setDetails] = useState(false);
  const data = event.data;
  const response = store.getRun(event.runId)?.events.find((item) => item.type === 'approval.responded' && (item.data.event_id === event.id || item.data.approval_id === data.approval_id));
  const choice = response?.data.choice;
  const toolName = String(data.tool ?? data.name ?? '未知工具');
  const args = data.input ?? data.arguments;
  const { verb, target } = describeTool(toolName, args);
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface">
    <div className="flex gap-3.5 border-l-[3px] border-danger px-4 py-3.5">
      <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14px] font-semibold text-heading">需要你确认：{verb}{target ? <code className="ml-1.5 rounded-[5px] bg-code px-1.5 font-mono text-[12.5px] font-normal text-fg-2">{target}</code> : null}</p>
        {typeof data.description === 'string' && data.description && <p className="mt-1 mb-0 text-[13px] text-fg-2">{data.description}</p>}
        {choice
          ? <p className="mt-2.5 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2">{choice === 'allow' ? <><Check size={14} className="text-ok" />已允许</> : <><X size={14} className="text-danger" />已拒绝</>}</p>
          : <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => store.approve(event.id)}>允许</Button>
            <Button onClick={() => store.reject(event.id)}>拒绝</Button>
            {args !== undefined && <Button variant="ghost" onClick={() => setDetails((open) => !open)}>{details ? '收起详情' : '查看详情'}</Button>}
          </div>}
        {details && args !== undefined && <pre className="anim-fade mt-3 mb-0 max-h-60 overflow-auto rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] whitespace-pre-wrap text-fg-2">{typeof args === 'string' ? args : JSON.stringify(args, null, 2)}</pre>}
      </div>
    </div>
  </div>;
}
