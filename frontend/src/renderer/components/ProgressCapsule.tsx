import * as Popover from '@radix-ui/react-popover';
import { useEffect, useMemo, useState } from 'react';
import { Check, ChevronDown, CircleDashed, Clock3, Coins, Gauge, LoaderCircle, Pause, Square, X } from 'lucide-react';
import type { AgentEvent, AgentRun } from '../../types/runtime';
import { cn } from '../ui/cn';
import { buildTimeline, duration } from './timeline';
import { clock, formatTokens, latestTodos, usageSummary } from './runInsights';

type StepState = 'pending' | 'running' | 'done' | 'failed' | 'cancelled';
interface ProgressStep { id: string; text: string; detail?: string; state: StepState; time?: string }

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

/** Prefer the Agent's own todo list, then an approved plan, then the tool steps it actually took. */
function progressSteps(events: AgentEvent[]): { steps: ProgressStep[]; source: 'todos' | 'plan' | 'tools' } {
  const todos = latestTodos(events);
  if (todos?.todos.length) return {
    source: 'todos',
    steps: todos.todos.map((item) => ({ id: item.id, text: item.text,
      state: item.status === 'completed' ? 'done' : item.status === 'in_progress' ? 'running' : item.status === 'cancelled' ? 'cancelled' : 'pending' })),
  };
  const plan = [...events].reverse().find((event) => event.type === 'run.plan.updated')?.data;
  const subtasks = plan && typeof plan.plan === 'object' && plan.plan ? (plan.plan as { subtasks?: unknown }).subtasks : plan?.subtasks;
  if (Array.isArray(subtasks) && subtasks.length) return {
    source: 'plan',
    steps: subtasks.map((raw, index) => {
      const step = (raw ?? {}) as { id?: string; title?: string; status?: string };
      return { id: String(step.id ?? index), text: String(step.title ?? step.id ?? `步骤 ${index + 1}`),
        state: step.status === 'completed' ? 'done' : step.status === 'running' || step.status === 'in_progress' ? 'running' : step.status === 'failed' ? 'failed' : 'pending' };
    }),
  };
  const steps = buildTimeline(events).flatMap((item) => item.kind === 'steps' ? item.steps : []);
  return {
    source: 'tools',
    steps: steps.map((step) => ({ id: step.id, text: step.verb, detail: step.target, state: step.state === 'running' ? 'running' : step.state,
      time: step.state === 'running' ? undefined : duration(step.startedAt, step.endedAt) })),
  };
}

function Ring({ value, running, state }: { value: number | null; running: boolean; state: string }) {
  if (state === 'completed') return <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-ok text-white"><Check size={11} strokeWidth={3} /></span>;
  if (state === 'failed') return <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-danger text-white"><X size={11} strokeWidth={3} /></span>;
  if (state === 'cancelled') return <span className="grid size-[18px] shrink-0 place-items-center rounded-full bg-fg-3 text-white"><Square size={8} fill="currentColor" /></span>;
  const radius = 7;
  const circumference = 2 * Math.PI * radius;
  const shown = value ?? 0.25;
  return <svg viewBox="0 0 18 18" className={cn('size-[18px] shrink-0 -rotate-90', value === null && running && 'animate-spin')} aria-hidden>
    <circle cx="9" cy="9" r={radius} fill="none" stroke="var(--line-strong)" strokeWidth="2" />
    <circle cx="9" cy="9" r={radius} fill="none" stroke="var(--brand)" strokeWidth="2" strokeLinecap="round"
      strokeDasharray={`${circumference * shown} ${circumference}`} className="transition-[stroke-dasharray] duration-500" />
  </svg>;
}

function StepIcon({ state, live }: { state: StepState; live: boolean }) {
  if (state === 'done') return <Check size={13} className="text-ok" strokeWidth={2.6} />;
  if (state === 'failed') return <X size={13} className="text-danger" strokeWidth={2.6} />;
  if (state === 'cancelled') return <X size={13} className="text-fg-3" />;
  if (state === 'running') return live ? <LoaderCircle size={13} className="animate-spin text-brand" /> : <i className="size-[7px] rounded-full bg-brand" />;
  return <CircleDashed size={13} className="text-fg-3" />;
}

const RUN_TEXT: Record<string, string> = { completed: '已完成', failed: '没有完成', cancelled: '已停止', paused: '已暂停', waiting: '等你确认', planning: '正在规划' };

/** Floating pill at the top-right of the conversation: where the task is now; click for every step. */
export default function ProgressCapsule({ run, events, onShowAll }: { run: AgentRun; events: AgentEvent[]; onShowAll: () => void }) {
  const live = !TERMINAL.has(run.status);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [live]);

  const { steps, source } = useMemo(() => progressSteps(events), [events]);
  const usage = useMemo(() => usageSummary(events), [events]);
  const endedAt = useMemo(() => [...events].reverse().find((event) => event.type === 'run.completed' || event.type === 'run.failed' || event.type === 'run.cancelled')?.timestamp, [events]);
  const startedAt = events.find((event) => event.type === 'run.started')?.timestamp ?? run.startedAt;
  const elapsed = clock(startedAt, live ? now : endedAt ?? run.updatedAt);

  const planned = source !== 'tools';
  const countable = steps.filter((step) => step.state !== 'cancelled');
  const done = countable.filter((step) => step.state === 'done').length;
  const current = steps.find((step) => step.state === 'running') ?? (planned ? steps.find((step) => step.state === 'pending') : undefined);
  const ratio = planned && countable.length ? done / countable.length : null;
  const headline = live && run.status === 'running'
    ? current ? `${current.text}${current.detail ? ` ${current.detail}` : ''}` : '正在思考'
    : RUN_TEXT[run.status] ?? '正在处理';
  const shownSteps = planned ? steps : steps.slice(-30);

  return <Popover.Root>
    <Popover.Trigger asChild>
      <button type="button" aria-label="任务进展"
        className="group raised no-drag anim-pop flex h-8 max-w-[360px] items-center gap-2 rounded-full py-0 pr-2.5 pl-1.5 text-[12.5px] text-fg-2 transition-shadow hover:text-fg data-[state=open]:text-fg">
        <Ring value={ratio} running={live} state={run.status} />
        {run.status === 'paused' && <Pause size={12} className="shrink-0 text-fg-3" />}
        <span className={cn('min-w-0 truncate', live && run.status === 'running' && 'text-fg')}>{headline}</span>
        {planned && countable.length > 0 && <span className="shrink-0 tabular-nums text-fg-3">{done}/{countable.length}</span>}
        <span className="h-3 w-px shrink-0 bg-line-strong" />
        <span className="shrink-0 tabular-nums text-fg-3">{elapsed}</span>
        <ChevronDown size={12} className="shrink-0 text-fg-3 transition-transform group-data-[state=open]:rotate-180" />
      </button>
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Content side="bottom" align="end" sideOffset={8} collisionPadding={12}
        className="pop anim-pop z-[60] w-[360px] overflow-hidden rounded-2xl outline-none">
        <div className="px-4 pt-3.5 pb-3">
          <div className="flex items-center gap-2">
            <Ring value={ratio} running={live} state={run.status} />
            <b className="text-[14px] font-semibold text-heading">任务进展</b>
            <span className="text-[12px] text-fg-3">{live ? (RUN_TEXT[run.status] ?? '进行中') : RUN_TEXT[run.status]}</span>
            <span className="flex-1" />
            {planned && countable.length > 0 && <span className="text-[12px] tabular-nums text-fg-2">{done} / {countable.length}</span>}
          </div>
          {ratio !== null && <span className="mt-2.5 block h-1 overflow-hidden rounded-full bg-sunken">
            <i className={cn('block h-full rounded-full transition-[width] duration-500', run.status === 'completed' ? 'bg-ok' : 'bg-brand')} style={{ width: `${ratio * 100}%` }} />
          </span>}
          <div className="mt-2.5 flex flex-wrap gap-x-3.5 gap-y-1 text-[11.5px] text-fg-3">
            <span className="inline-flex items-center gap-1"><Clock3 size={11} />用时 <b className="font-medium tabular-nums text-fg-2">{elapsed}</b></span>
            {usage && <span className="inline-flex items-center gap-1"><Coins size={11} /><b className="font-medium tabular-nums text-fg-2">{formatTokens(usage.input + usage.output)}</b> tokens · {usage.requests} 次调用</span>}
            {usage?.context && <span className={cn('inline-flex items-center gap-1', usage.context.percent >= 80 && 'text-danger')}><Gauge size={11} />上下文 <b className="font-medium tabular-nums">{usage.context.percent}%</b></span>}
          </div>
        </div>
        <div className="border-t border-line">
          {shownSteps.length === 0
            ? <p className="m-0 px-4 py-4 text-[12.5px] text-fg-3">{live ? 'Atlas 还在想，第一步马上开始…' : '这次没有用到工具。'}</p>
            : <ol className="relative m-0 max-h-[46vh] list-none overflow-y-auto px-2 py-2">
              {!planned && steps.length > shownSteps.length && <li className="px-2 pb-1 text-[11.5px] text-fg-3">前面还有 {steps.length - shownSteps.length} 步</li>}
              {shownSteps.map((step, index) => <li key={step.id}
                className={cn('relative flex items-start gap-2.5 rounded-lg px-2 py-[5px]', step.state === 'running' && 'bg-brand-soft')}>
                {index < shownSteps.length - 1 && <span className="absolute top-[22px] bottom-[-6px] left-[14.5px] w-px bg-line" aria-hidden />}
                <span className="relative z-[1] mt-[3px] grid size-[13px] shrink-0 place-items-center bg-[var(--overlay)]"><StepIcon state={step.state} live={live} /></span>
                <span className="min-w-0 flex-1 text-[12.5px] leading-[1.55]">
                  <span className={cn(step.state === 'done' || step.state === 'cancelled' ? 'text-fg-2' : step.state === 'failed' ? 'text-danger' : step.state === 'running' ? 'font-medium text-fg' : 'text-fg-3',
                    step.state === 'cancelled' && 'line-through')}>{step.text}</span>
                  {step.detail && <code className="ml-1.5 rounded-[4px] bg-code px-1 font-mono text-[11px] break-all text-fg-3">{step.detail}</code>}
                </span>
                {step.time && <span className="mt-[2px] shrink-0 text-[11px] tabular-nums text-fg-3">{step.time}</span>}
              </li>)}
            </ol>}
        </div>
        <div className="flex items-center border-t border-line px-4 py-2 text-[12px]">
          <span className="text-fg-3">{source === 'todos' ? '按 Atlas 的待办清单' : source === 'plan' ? '按批准的计划' : '按实际执行的步骤'}</span>
          <span className="flex-1" />
          <Popover.Close asChild><button type="button" onClick={onShowAll} className="text-fg-2 hover:text-fg">在任务面板查看 →</button></Popover.Close>
        </div>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
