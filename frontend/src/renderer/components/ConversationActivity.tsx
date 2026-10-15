import { memo, useMemo, useState } from 'react';
import { BookMarked, Check, ClipboardCopy, FileCheck2, FileWarning, SearchCheck, ChevronRight, CircleDashed, LoaderCircle, FileText, FlaskConical, ListChecks, MessageCircleQuestion, Repeat2, Send, ShieldAlert, Square, Users, X } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import ToolExecutionCard, { CATEGORY, Detail } from './tool-cards/ToolExecutionCard';
import ConversationMessage from './ConversationMessage';
import ReasoningBlock from './ReasoningBlock';
import Mark from './Mark';
import SessionEventCard from './sessions/SessionEventCard';
import ReviewFindingsCard from './ReviewFindingsCard';
import ForegroundConfirmCard from './x2/ForegroundConfirmCard';
import BrowserHandoffCard from './x2/BrowserHandoffCard';
import { DiagnosticsList } from './diagnostics';
import { buildTimeline, cacheShare, describeTool, duration, tokenCount, type Step, type TimelineItem } from './timeline';
import type { InspectorTab } from '../shell/Inspector';
import { TokenUsageCard, TokenUsageToggle } from './TokenUsage';
import { usageSummary } from './runInsights';

interface ConversationActivityProps {
  events: AgentEvent[];
  store: ReturnType<typeof useAtlasStore.getState>;
  username: string;
  setTab: (tab: InspectorTab) => void;
  /** X2 交接卡「在浏览器面板打开」时由宿主打开浏览器面板并带上网址。 */
  onOpenBrowser?: (url: string) => void;
}

/** 一条时间线渲染所需的上下文；由 ConversationActivity / MessageThread（虚拟列表）提供。 */
export interface TimelineRowContext {
  events: AgentEvent[];
  store: ReturnType<typeof useAtlasStore.getState>;
  username: string;
  setTab: (tab: InspectorTab) => void;
  busy: boolean;
  onOpenBrowser?: (url: string) => void;
}

/** 渲染单条时间线（用户消息、步骤、回复、审批卡片…）；虚拟列表按条复用，输出与整段渲染完全一致。 */
export const TimelineRow = memo(function TimelineRow({ item, context, firstInTurn, last }: { item: TimelineItem; context: TimelineRowContext; firstInTurn: boolean; last: boolean }) {
  const { events, store, username, setTab, busy, onOpenBrowser } = context;
  switch (item.kind) {
    case 'user': return <ConversationMessage key={item.id} role="user" content={item.content} username={username} note={item.steered ? '插话' : undefined} />;
    case 'reply': return <ConversationMessage key={item.id} role="assistant" content={item.content} username={username} continued={!firstInTurn} streaming={item.streaming}
      status={item.status ?? (item.streaming ? '正在回复' : undefined)} working={item.streaming && busy} />;
    case 'reasoning': return <div key={item.id}>
      {firstInTurn && <TurnHeader working={last && busy} />}
      <ReasoningBlock text={item.text} streaming={last && busy && item.source === 'run.status'} startedAt={item.startedAt} endedAt={item.endedAt} truncated={item.truncated} />
    </div>;
    case 'steps': return <div key={item.id}>
      {firstInTurn && <TurnHeader working={last && busy} />}
      <StepTrack steps={item.steps} live={last && busy} runId={events[0]?.runId ?? ''} store={store} onCancelSubtask={(subtaskId) => { const runId = events[0]?.runId; if (runId) store.cancelSubtask(runId, subtaskId); }} />
    </div>;
    case 'artifact': return <div key={item.id} className="my-3 flex items-center gap-3 rounded-xl card-surface px-3.5 py-2.5 text-[13px]">
      <FileText size={16} className="shrink-0 text-brand" />
      <div className="min-w-0 flex-1"><b className="font-medium text-fg">{item.name}</b>{item.summary && <p className="m-0 truncate text-fg-3">{item.summary}</p>}</div>
      <Button size="sm" variant="ghost" onClick={() => setTab('artifacts')}>查看</Button>
    </div>;
    case 'approval': return <Approval key={item.id} event={item.event} store={store} />;
    case 'question': return <Question key={item.id} event={item.event} store={store} />;
    case 'plan': return <Plan key={item.id} event={item.event} store={store} />;
    case 'trust': return <Trust key={item.id} event={item.event} store={store} />;
    case 'foreground': {
      const data = item.event.data;
      return <div key={item.id} className="my-4">
        <ForegroundConfirmCard apiBaseUrl={store.apiBaseUrl} runId={item.event.runId}
          reason={typeof data.reason === 'string' && data.reason ? data.reason : 'Atlas 想在你正在使用的窗口里操作'}
          target={typeof data.target === 'string' ? data.target : undefined} />
      </div>;
    }
    case 'handoff': {
      const data = item.event.data;
      const url = typeof data.url === 'string' ? data.url : undefined;
      return <div key={item.id} className="my-4">
        <BrowserHandoffCard apiBaseUrl={store.apiBaseUrl} runId={item.event.runId}
          reason={typeof data.reason === 'string' && data.reason ? data.reason : '浏览器这一步需要你搭把手'}
          url={url}
          onOpenPanel={() => { if (url && onOpenBrowser) onOpenBrowser(url); else setTab('browser'); }} />
      </div>;
    }
    case 'group': return <WorkerGroup key={item.id} item={item} />;
    case 'checks': return <Checks key={item.id} item={item} />;
    case 'notice': return <div key={item.id} className="my-3 flex items-center gap-2 text-[12.5px] text-fg-2">
      {item.tone === 'switch' ? <Repeat2 size={13} className="shrink-0 text-brand" /> : item.tone === 'todo' ? <ListChecks size={13} className="shrink-0 text-brand" /> : <FlaskConical size={13} className="shrink-0 text-brand" />}
      <span>{item.text}</span>
    </div>;
    case 'lsp': return <LspNotice key={item.id} item={item} />;
    case 'review': return <ReviewFindingsCard key={item.id} item={item} store={store} />;
    case 'session': return <SessionEventCard key={item.id} event={item.event} />;
    case 'cancelled': return <div key={item.id} className="my-4 flex items-center gap-2 text-[12.5px] text-fg-3">
      <Square size={12} />{item.reason ? `会话已结束：${item.reason}` : '你停止了这次任务'}
    </div>;
    case 'done': return <DoneLine key={item.id} item={item} events={events} store={store} setTab={setTab} />;
    case 'failed': return <div key={item.id} role="alert" className="my-4 rounded-xl bg-danger-soft px-4 py-3 text-[13px] text-danger">
      没能完成：{item.detail}
    </div>;
    default: return null;
  }
});

export default function ConversationActivity({ events, store, username, setTab, onOpenBrowser }: ConversationActivityProps) {
  const items = useMemo(() => buildTimeline(events), [events]);
  const busy = store.busy && !store.paused;
  // Each Atlas turn shows its header once; later steps and replies in the same turn hang beneath it.
  let headed = false;
  return <>{items.map((item, index) => {
    const last = index === items.length - 1;
    if (item.kind === 'user') headed = false;
    const firstInTurn = item.kind !== 'user' && !headed;
    if (item.kind !== 'user') headed = true;
    return <TimelineRow key={item.id} item={item} context={{ events, store, username, setTab, busy, onOpenBrowser }} firstInTurn={firstInTurn} last={last} />;
  })}</>;
}


/** The finished-turn line: duration, token usage (unfolds into a breakdown card), changed files, follow-up actions. */
function DoneLine({ item, events, store, setTab }: { item: Extract<TimelineItem, { kind: 'done' }>; events: AgentEvent[]; store: Store; setTab: (tab: InspectorTab) => void }) {
  const [usageOpen, setUsageOpen] = useState(false);
  const summary = useMemo(() => usageSummary(events), [events]);
  const tokens = summary ? null : tokenCount(item.usage);
  const cached = summary ? null : cacheShare(item.usage);
  const changed = item.changes && item.changes.files > 0 ? item.changes : null;
  return <div className="my-4 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-fg-3">
    <Check size={14} className="text-ok" />完成{item.startedAt ? `，用时 ${duration(item.startedAt, item.endedAt)}` : ''}
    {summary && <TokenUsageToggle usage={summary} open={usageOpen} onToggle={() => setUsageOpen((value) => !value)} />}
    {tokens && <span className="tabular-nums">· {tokens} tokens{cached ? `（${cached}）` : ''}</span>}
    {changed && <button className="text-fg-2 hover:text-fg" onClick={() => setTab('changes')}>
      · 改了 {changed.files} 个文件 <span className="tabular-nums text-ok">+{changed.additions}</span> <span className="tabular-nums text-danger">−{changed.deletions}</span>
    </button>}
    <button className="ml-2 text-fg-2 underline decoration-line-strong underline-offset-[3px] hover:text-fg" onClick={() => setTab('activity')}>全部步骤</button>
    {changed && <button className="ml-2 inline-flex items-center gap-1 text-fg-2 hover:text-fg"
      onClick={() => void store.sendMessage('/review')}><SearchCheck size={13} />审查本次改动</button>}
    {events[0] && <SaveRecipe runId={events[0].runId} store={store} />}
    {summary && usageOpen && <TokenUsageCard usage={summary} />}
    <RunTraceDetails events={events} usage={summary} />
  </div>;
}

function reportedReasoningTokens(events: AgentEvent[]): number | null {
  const rows = new Map<string, Record<string, unknown>>();
  let anonymous = 0;
  for (const event of events) {
    if (event.type !== 'run.usage') continue;
    const id = typeof event.data.request_id === 'string' && event.data.request_id ? event.data.request_id : `anon-${anonymous++}`;
    rows.set(id, event.data);
  }
  let total = 0;
  let reported = false;
  for (const row of rows.values()) {
    const completion = row.completion_tokens_details && typeof row.completion_tokens_details === 'object'
      ? row.completion_tokens_details as Record<string, unknown> : undefined;
    const output = row.output_tokens_details && typeof row.output_tokens_details === 'object'
      ? row.output_tokens_details as Record<string, unknown> : undefined;
    const value = [row.reasoning_tokens, completion?.reasoning_tokens, output?.reasoning_tokens]
      .find((candidate) => typeof candidate === 'number' && Number.isFinite(candidate));
    if (typeof value === 'number') { total += value; reported = true; }
  }
  return reported ? total : null;
}

/** Model text is shown only when a run.status event explicitly carries status=reasoning and text. */
function RunTraceDetails({ events, usage }: { events: AgentEvent[]; usage: ReturnType<typeof usageSummary> }) {
  const steps = useMemo(() => buildTimeline(events).flatMap((item) => item.kind === 'steps' ? item.steps : []), [events]);
  const switches = events.filter((event) => event.type === 'run.model_switched');
  const reasoningTokens = useMemo(() => reportedReasoningTokens(events), [events]);
  const sources = useMemo(() => [
    events.some((event) => event.type === 'run.usage') && 'run.usage',
    switches.length > 0 && 'run.model_switched',
    events.some((event) => event.type === 'tool.started' || event.type === 'tool.output' || event.type === 'tool.completed') && 'tool.started/tool.output/tool.completed',
    events.some((event) => event.type.startsWith('subtask.')) && 'subtask.*',
  ].filter(Boolean).join(' · '), [events, switches.length]);
  const traceText = useMemo(() => {
    const lines = ['Atlas 本次运行轨迹'];
    if (usage) {
      lines.push(`模型调用：${usage.requests} 次`);
      for (const model of usage.byModel) lines.push(`- ${model.model}：${model.requests} 次，输入 ${model.input} tokens，输出 ${model.output} tokens，缓存 ${model.cached} tokens`);
      lines.push(`推理 token：${reasoningTokens === null ? '提供方未返回' : reasoningTokens.toLocaleString()}`);
      if (usage.cost !== null) lines.push(`费用：$${usage.cost.toFixed(4)}`);
    } else lines.push('模型用量：运行事件未提供');
    if (switches.length) lines.push(`模型切换：${switches.map((event) => `${String(event.data.from ?? '未知模型')} → ${String(event.data.to ?? '未知模型')}`).join('；')}`);
    if (sources) lines.push(`事件来源：${sources}`);
    lines.push(`工具步骤：${steps.length} 项`);
    for (const step of steps) {
      lines.push(`- ${step.verb}${step.target ? ` ${step.target}` : ''}：${step.state === 'failed' ? '失败' : step.state === 'cancelled' ? '已取消' : step.state === 'running' ? '进行中' : '完成'}`);
      if (step.summary || step.failureReason) lines.push(`  ${step.failureReason ?? step.summary}`);
    }
    return lines.join('\n');
  }, [reasoningTokens, sources, steps, switches, usage]);
  const [copyStatus, setCopyStatus] = useState('');
  const requests = usage?.requests ?? 0;
  const label = requests ? `模型与工具轨迹 · ${requests} 次模型调用 · ${steps.length} 个工具步骤` : `运行轨迹 · ${steps.length} 个工具步骤`;
  if (!usage && !steps.length && !switches.length) return null;
  return <details className="basis-full rounded-lg border border-line/70 bg-surface/40 px-2.5 py-2">
    <summary className="cursor-pointer text-[12px] text-fg-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">{label}</summary>
    <div className="mt-2 grid gap-2 text-left">
      <p className="m-0 text-[11.5px] text-fg-3">模型和用量来自 <code>run.usage</code>，工具步骤来自运行时工具事件。推理文本只有在 <code>run.status</code> 明确提供时才会单独显示。</p>
      {usage && <div className="grid gap-1 text-[12px] text-fg-2">
        {usage.byModel.map((model) => <p key={model.model} className="m-0">{model.model} · {model.requests} 次 · 输入 {model.input.toLocaleString()} / 输出 {model.output.toLocaleString()} tokens</p>)}
        <p className="m-0">推理 tokens：{reasoningTokens === null ? '提供方未返回' : reasoningTokens.toLocaleString()}{usage.cost !== null ? ` · 费用 $${usage.cost.toFixed(4)}` : ''}</p>
      </div>}
      {switches.map((event) => <p key={event.id} className="m-0 text-[12px] text-fg-2">模型切换：{String(event.data.from ?? '未知模型')} → {String(event.data.to ?? '未知模型')}{typeof event.data.reason === 'string' && event.data.reason ? `（${event.data.reason}）` : ''}</p>)}
      {steps.length > 0 && <ol className="m-0 grid max-h-48 gap-1 overflow-auto pl-5 text-[12px] text-fg-2">
        {steps.map((step) => <li key={step.id}>{step.verb}{step.target ? ` · ${step.target}` : ''} · {step.state === 'failed' ? `失败：${step.failureReason ?? '未提供原因'}` : step.state === 'cancelled' ? '已取消' : step.state === 'running' ? '进行中' : step.summary ?? '完成'}</li>)}
      </ol>}
      <button type="button" onClick={() => {
        if (!navigator.clipboard) { setCopyStatus('复制失败，浏览器未提供剪贴板权限'); return; }
        void navigator.clipboard.writeText(traceText).then(() => setCopyStatus('已复制轨迹摘要')).catch(() => setCopyStatus('复制失败，浏览器未提供剪贴板权限'));
      }}
        className="inline-flex w-fit items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-fg-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
        <ClipboardCopy size={13} aria-hidden="true" />复制轨迹摘要
      </button>
      <span role="status" aria-live="polite" className="sr-only">{copyStatus}</span>
    </div>
  </details>;
}

function TurnHeader({ working }: { working: boolean }) {
  // No avatar or name column any more; only a working line while Atlas is busy.
  if (!working) return <div className="mt-5" />;
  return <div className="mt-5 flex items-center gap-2 text-[12px] text-fg-3">
    <Mark className="size-4" working />
    <span className="text-shimmer">正在处理</span>
  </div>;
}

/** Claude Code / Codex style work log: one quiet line per step; a finished batch folds into a single summary line. */
function StepTrack({ steps, live, runId, store, onCancelSubtask }: { steps: Step[]; live: boolean; runId: string; store: Store; onCancelSubtask: (subtaskId: string) => void }) {
  const [open, setOpen] = useState<boolean | null>(null);
  const running = live && steps.some((step) => step.state === 'running');
  const failed = steps.filter((step) => step.state === 'failed').length;
  const foldable = steps.length > 2;
  const expanded = !foldable || (open ?? running);
  const startedAt = steps[0]?.startedAt;
  const endedAt = steps.reduce<string | undefined>((latest, step) => (step.endedAt && (!latest || step.endedAt > latest) ? step.endedAt : latest), undefined);
  return <div className="my-2">
    {foldable && <button type="button" onClick={() => setOpen(!expanded)} aria-expanded={expanded}
      className="inline-flex max-w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-[13px] text-fg-3 hover:text-fg">
      <ChevronRight size={13} className={cn('shrink-0 transition-transform', expanded && 'rotate-90')} />
      {running && <LoaderCircle size={13} className="spin shrink-0 text-brand" />}
      <span className="min-w-0 truncate">{summarizeSteps(steps, running)}</span>
      {failed > 0 && <span className="shrink-0 text-danger">· {failed} 步失败</span>}
      {!running && startedAt && endedAt && <span className="shrink-0 tabular-nums">· {duration(startedAt, endedAt)}</span>}
    </button>}
    {expanded && <ol className={cn('m-0 list-none p-0', foldable && 'ml-[6px] border-l border-line pl-3')} aria-label="Atlas 的步骤">
      {steps.map((step) => step.subtaskId
        ? <SubtaskRow key={step.id} step={step} live={live} runId={runId} store={store} onCancelSubtask={onCancelSubtask} />
        : <StepLine key={step.id} step={step} live={live} />)}
    </ol>}
  </div>;
}

const STEP_GROUPS: Array<{ match: (step: Step) => boolean; done: (n: number) => string; doing: (n: number) => string }> = [
  { match: (s) => s.category === 'file-read', done: (n) => `读取了 ${n} 个文件`, doing: (n) => `读取 ${n} 个文件` },
  { match: (s) => s.category === 'file-write' || s.category === 'file-edit' || s.category === 'file-patch', done: (n) => `改动了 ${n} 个文件`, doing: (n) => `改动 ${n} 个文件` },
  { match: (s) => s.category === 'shell' || s.category === 'exec' || s.category === 'process', done: (n) => `运行了 ${n} 条命令`, doing: (n) => `运行 ${n} 条命令` },
  { match: (s) => s.category === 'search', done: (n) => `搜索了 ${n} 次`, doing: (n) => `搜索 ${n} 次` },
  { match: (s) => s.category === 'web' || s.category === 'browser', done: (n) => `访问了 ${n} 次网页`, doing: (n) => `访问 ${n} 次网页` },
];

function summarizeSteps(steps: Step[], running: boolean): string {
  const parts: string[] = [];
  let rest = steps.length;
  for (const group of STEP_GROUPS) {
    const count = steps.filter(group.match).length;
    if (!count) continue;
    parts.push(running ? group.doing(count) : group.done(count));
    rest -= count;
  }
  if (rest > 0) parts.push(`其他 ${rest} 步`);
  return (running ? '正在工作：' : '') + parts.join('、');
}

function StepLine({ step, live }: { step: Step; live: boolean }) {
  const [open, setOpen] = useState(false);
  const active = step.state === 'running' && live;
  const { icon: Icon } = CATEGORY[step.category] ?? CATEGORY.other;
  const hasDetails = Boolean(step.input || step.result || step.output || step.fullOutputPath || step.summary);
  return <li className="min-w-0">
    <button type="button" onClick={() => { if (hasDetails) setOpen((value) => !value); }} aria-expanded={hasDetails ? open : undefined}
      className={cn('group flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-[3px] text-left text-[13px]', hasDetails && 'hover:bg-hover')}>
      {active ? <LoaderCircle size={13} className="spin shrink-0 text-brand" />
        : <Icon size={13} className={cn('shrink-0', step.state === 'failed' ? 'text-danger' : 'text-fg-3')} />}
      <span className={cn('shrink-0', step.state === 'failed' ? 'text-danger' : 'text-fg-2')}>{step.verb}</span>
      {step.target && <span className="min-w-0 truncate font-mono text-[12px] text-fg-3" title={step.target}>{step.target}</span>}
      <span className="flex-1" />
      {step.state === 'failed' ? <X size={12} className="shrink-0 text-danger" />
        : step.state === 'cancelled' ? <span className="shrink-0 text-[11px] text-fg-3">已取消</span>
          : step.endedAt ? <span className="shrink-0 text-[11px] tabular-nums text-fg-3 opacity-0 group-hover:opacity-100">{duration(step.startedAt, step.endedAt)}</span> : null}
    </button>
    {step.failureReason && !open && <p className="m-0 ml-[29px] truncate text-[12px] text-danger" title={step.failureReason}>{step.failureReason}</p>}
    {open && <div className="anim-fade mb-1.5 ml-[29px] mt-1 grid gap-2 text-[12.5px]">
      {step.summary && <p className="m-0 break-words text-fg-2">{step.summary.replace(/\s+/g, ' ').trim()}</p>}
      {step.failureReason && <p role="alert" className="m-0 break-words text-danger">失败原因：{step.failureReason}</p>}
      {step.input && <Detail label="输入参数" value={step.input} copyLabel="复制输入" />}
      {step.result && <Detail label="工具结果" value={step.result} copyLabel="复制结果" />}
      {step.output && <Detail label="运行输出" value={step.output} copyLabel="复制输出" />}
      {step.fullOutputPath && <p className="m-0 text-[11.5px] text-fg-3">完整输出：{window.atlasDesktop?.openPath
        ? <button type="button" onClick={() => void window.atlasDesktop!.openPath(step.fullOutputPath!)} className="break-all font-mono text-fg-2 underline decoration-line-strong underline-offset-2 hover:text-fg">{step.fullOutputPath}</button>
        : <code className="break-all">{step.fullOutputPath}</code>}</p>}
    </div>}
  </li>;
}

/** Sub-agents keep the full card: they can be stopped and steered while running. */
function SubtaskRow({ step, live, runId, store, onCancelSubtask }: { step: Step; live: boolean; runId: string; store: Store; onCancelSubtask: (subtaskId: string) => void }) {
  const [steerText, setSteerText] = useState('');
  const [steerState, setSteerState] = useState<{ sequence: number; text: string } | null>(null);
  const running = step.state === 'running' && live;
  const steerFeedback = steerState && store.getRun(runId)?.events.find((event) => event.sequence > steerState.sequence
    && event.data.subtask_id === step.subtaskId
    && (event.type === 'subtask.steered' || event.type === 'subtask.steer_rejected'));
  return <li className="my-1.5">
    <ToolExecutionCard step={step} live={live}>
      {running && step.subtaskId && <div className="flex items-center justify-between gap-2">
        <span className="text-[11.5px] text-fg-3">子 Agent 正在运行</span>
        <button type="button" onClick={() => onCancelSubtask(step.subtaskId!)} className="rounded-md px-1.5 py-0.5 text-[11.5px] text-fg-3 hover:bg-hover hover:text-danger">停止这个子任务</button>
      </div>}
    {running && step.subtaskId && <form className="mt-2 flex items-center gap-2" onSubmit={(event) => {
      event.preventDefault();
      const text = steerText.trim();
      if (!text || !runId) return;
      const current = store.getRun(runId);
      const eventId = crypto.randomUUID();
      if (store.steerSubtask(runId, step.subtaskId!, eventId, text)) {
        setSteerState({ sequence: current?.lastEventSequence ?? 0, text });
        setSteerText('');
      }
    }}>
      <input aria-label="补充子任务要求" value={steerText} onChange={(event) => setSteerText(event.target.value)} placeholder="补充要求给这个子 Agent…"
        className="min-w-0 flex-1 rounded-lg border border-line bg-sheet px-2.5 py-1.5 text-[12px] text-fg outline-none placeholder:text-fg-3 focus:border-brand" />
      <Button type="submit" size="sm" variant="ghost" disabled={!steerText.trim()}><Send size={13} />发送</Button>
    </form>}
    {steerState && <p role="status" className={cn('m-0 mt-1 text-[11px]', steerFeedback?.type === 'subtask.steer_rejected' ? 'text-danger' : 'text-fg-3')}>
      {steerFeedback?.type === 'subtask.steer_rejected' ? `子任务拒绝补充：${String(steerFeedback.data.reason ?? '子任务已不在运行')}` : steerFeedback?.type === 'subtask.steered' ? '补充要求已送达' : `已发送补充要求：${steerState.text}`}
    </p>}
    </ToolExecutionCard>
  </li>;
}

function Approval({ event, store }: { event: AgentEvent; store: ReturnType<typeof useAtlasStore.getState> }) {
  const [details, setDetails] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const data = event.data;
  const response = store.getRun(event.runId)?.events.find((item) => item.type === 'approval.responded' && (item.data.event_id === event.id || item.data.approval_id === data.approval_id));
  const choice = response?.data.choice;
  const allowAlwaysAvailable = data.allow_always_available === true;
  const permissionScope = data.permission_scope && typeof data.permission_scope === 'object' ? data.permission_scope as Record<string, unknown> : null;
  const toolName = String(data.tool ?? data.name ?? '未知工具');
  const args = data.input ?? data.arguments;
  const { verb, target } = describeTool(toolName, args);
  return <div className="my-4 overflow-hidden rounded-xl card-surface" onKeyDown={(keyEvent) => {
    if (!keyEvent.altKey || keyEvent.ctrlKey || keyEvent.metaKey || keyEvent.shiftKey || keyEvent.nativeEvent.isComposing || (keyEvent.nativeEvent as KeyboardEvent).keyCode === 229) return;
    const target = keyEvent.target;
    if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return;
    if (keyEvent.key === '1') { keyEvent.preventDefault(); if (!choice) store.respondToApproval(event.id, 'allow_once'); }
    else if (keyEvent.key === '2' && allowAlwaysAvailable) { keyEvent.preventDefault(); if (!choice) store.respondToApproval(event.id, 'allow_always'); }
    else if (keyEvent.key === '3') { keyEvent.preventDefault(); if (!choice) setRejecting(true); }
  }}>
    <div className="flex gap-3.5 border-l-[3px] border-danger px-4 py-3.5">
      <ShieldAlert size={18} className="mt-0.5 shrink-0 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14px] font-semibold text-heading">需要你确认：{verb}{target ? <code className="ml-1.5 rounded-[5px] bg-code px-1.5 font-mono text-[12.5px] font-normal text-fg-2">{target}</code> : null}</p>
        {typeof data.description === 'string' && data.description && <p className="mt-1 mb-0 text-[13px] text-fg-2">{data.description}</p>}
        {permissionScope && <p className="mt-1 mb-0 text-[12px] text-fg-3">始终允许范围：{String(permissionScope.workspace ?? '')} · {String(permissionScope.tool ?? toolName)}{permissionScope.resource ? ` · ${String(permissionScope.resource)}` : ' · 精确调用'}</p>}
        {!permissionScope && Boolean(data.scope || data.resource) && <p className="mt-1 mb-0 text-[12px] text-fg-3">范围：{String(data.scope ?? '单次请求')}{data.resource ? ` · 资源：${String(data.resource)}` : ''}</p>}
        {choice
          ? <p className="mt-2.5 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2">{choice === 'deny' ? <><X size={14} className="text-danger" />已拒绝{typeof response?.data.reason === 'string' && response.data.reason ? `：${response.data.reason}` : ''}</> : <><Check size={14} className="text-ok" />{choice === 'allow_always' ? response?.data.source === 'persisted_grant' ? '按已保存的始终允许规则通过' : '始终允许' : '已允许一次'}</>}</p>
          : <>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="primary" title="快捷键 Alt+1" onClick={() => store.respondToApproval(event.id, 'allow_once')}>允许一次</Button>
              {allowAlwaysAvailable && <Button title="快捷键 Alt+2" onClick={() => store.respondToApproval(event.id, 'allow_always')}>始终允许</Button>}
              <Button title="快捷键 Alt+3" onClick={() => setRejecting((value) => !value)}>拒绝并说明</Button>
              {args !== undefined && <Button variant="ghost" onClick={() => setDetails((open) => !open)}>{details ? '收起详情' : '查看详情'}</Button>}
            </div>
            {rejecting && <form className="mt-3 grid gap-2" onSubmit={(submitEvent) => { submitEvent.preventDefault(); if (!reason.trim()) return; store.respondToApproval(event.id, 'deny', reason); }}>
              <label className="text-[12px] text-fg-2">拒绝理由</label>
              <textarea autoFocus rows={2} maxLength={1000} value={reason} onChange={(changeEvent) => setReason(changeEvent.target.value)} placeholder="说明为什么拒绝这次操作" className="rounded-lg bg-overlay px-2.5 py-1.5 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]"
                onKeyDown={(keyEvent) => { const composing = keyEvent.nativeEvent.isComposing || (keyEvent.nativeEvent as KeyboardEvent).keyCode === 229; if (keyEvent.key === 'Enter' && (keyEvent.ctrlKey || keyEvent.metaKey) && !composing) { keyEvent.preventDefault(); if (reason.trim()) store.respondToApproval(event.id, 'deny', reason); } if (keyEvent.key === 'Escape' && !composing) setRejecting(false); }} />
              <div className="flex items-center justify-between gap-2"><span className="text-[11px] text-fg-3">{reason.length}/1000</span><span className="flex gap-2"><Button type="button" variant="ghost" onClick={() => setRejecting(false)}>取消</Button><Button type="submit" disabled={!reason.trim()}>提交拒绝</Button></span></div>
            </form>}
          </>}
        {details && args !== undefined && <pre className="anim-fade mt-3 mb-0 max-h-60 overflow-auto rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] whitespace-pre-wrap text-fg-2">{typeof args === 'string' ? args : JSON.stringify(args, null, 2)}</pre>}
      </div>
    </div>
  </div>;
}

type Store = ReturnType<typeof useAtlasStore.getState>;

/** The Agent stopped to ask something; the run waits until this is answered or stopped. */
function Question({ event, store }: { event: AgentEvent; store: Store }) {
  const [text, setText] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const eventId = String(event.data.event_id ?? '');
  const question = String(event.data.question ?? '');
  const header = String(event.data.header ?? '');
  const multiple = event.data.multi_select === true || event.data.multiSelect === true;
  const options = Array.isArray(event.data.options) ? event.data.options.map((option) =>
    typeof option === 'string' ? { label: option, description: '' }
      : { label: String((option as { label?: unknown })?.label ?? ''),
          description: String((option as { description?: unknown })?.description ?? '') },
  ).filter((option) => option.label) : [];
  const answer = store.answers[eventId];
  const run = store.getRun(event.runId);
  const open = answer === undefined && (!run || !['completed', 'failed', 'cancelled'].includes(run.status));
  const send = (value: string) => { if (value.trim()) store.answerInput(event.runId, eventId, value.trim()); };
  return <div className="my-4 overflow-hidden rounded-xl card-surface">
    <div className="flex gap-3.5 border-l-[3px] border-brand px-4 py-3.5">
      <MessageCircleQuestion size={18} className="mt-0.5 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        {header && <p className="m-0 text-[11px] font-semibold uppercase tracking-wide text-brand">{header}</p>}
        <p className="m-0 text-[14px] font-semibold whitespace-pre-wrap text-heading">{question}</p>
        {answer !== undefined
          ? <p className="mt-2 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2"><Check size={14} className="text-ok" />你的回答：{(() => { try { const parsed = JSON.parse(answer); return Array.isArray(parsed) ? parsed.join('、') : answer; } catch { return answer; } })()}</p>
          : open ? <>
            {options.length > 0 && <div className="mt-3 grid gap-2">{options.map((option) => multiple
              ? <label key={option.label} className="flex cursor-pointer items-start gap-2 rounded-lg bg-sunken p-2.5 text-[13px] text-fg-2">
                <input type="checkbox" checked={selected.includes(option.label)} onChange={(changeEvent) => setSelected((current) => changeEvent.target.checked ? [...current, option.label] : current.filter((item) => item !== option.label))} />
                <span><span className="block font-medium text-heading">{option.label}</span>{option.description && <span className="mt-0.5 block text-fg-3">{option.description}</span>}</span>
              </label>
              : <Button key={option.label} onClick={() => send(option.label)}><span className="text-left"><span className="block">{option.label}</span>{option.description && <span className="block text-[11px] text-fg-3">{option.description}</span>}</span></Button>)}</div>}
            <form className="mt-3 flex gap-2" onSubmit={(formEvent) => { formEvent.preventDefault(); send(text); }}>
              <input value={text} onChange={(changeEvent) => setText(changeEvent.target.value)} placeholder={options.length ? '或者直接写你的回答' : '写下你的回答'} aria-label="回答 Atlas 的问题"
                className="min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
              <Button type="submit" variant="primary" disabled={!text.trim()}>回答</Button>
            </form>
            {multiple && <Button className="mt-2" variant="primary" disabled={!selected.length} onClick={() => send(JSON.stringify(selected))}>提交所选项</Button>}
          </> : <p className="mt-2 mb-0 text-[13px] text-fg-3">任务已经结束，这个问题不再需要回答。</p>}
      </div>
    </div>
  </div>;
}

interface PlanStep { id?: string; title?: string; verification?: string }

/** Plan mode stops after exploring; nothing changes until the plan is approved. */
function Plan({ event, store }: { event: AgentEvent; store: Store }) {
  const [adding, setAdding] = useState(false);
  const [edits, setEdits] = useState('');
  const eventId = String(event.data.event_id ?? '');
  const plan = (event.data.plan && typeof event.data.plan === 'object' ? event.data.plan : {}) as { goal?: string; subtasks?: PlanStep[]; steps?: string };
  const steps = Array.isArray(plan.subtasks) ? plan.subtasks : [];
  const decided = store.answers[eventId];
  const run = store.getRun(event.runId);
  const open = decided === undefined && (!run || !['completed', 'failed', 'cancelled'].includes(run.status));
  return <div className="my-4 overflow-hidden rounded-xl card-surface">
    <div className="border-l-[3px] border-brand px-4 py-3.5">
      <p className="m-0 flex items-center gap-2 text-[14px] font-semibold text-heading"><ListChecks size={17} className="text-brand" />计划：{plan.goal ?? '待确认'}</p>
      {steps.length > 0
        ? <ol className="mt-3 mb-0 grid list-none gap-2 p-0 text-[13.5px]">
          {steps.map((step, index) => <li key={step.id ?? index} className="flex gap-2.5">
            <CircleDashed size={15} className="mt-[3px] shrink-0 text-fg-3" />
            <span className="min-w-0"><span className="text-fg">{step.title ?? step.id}</span>{step.verification && <small className="block text-[12px] text-fg-3">怎么验证：{step.verification}</small>}</span>
          </li>)}
        </ol>
        : plan.steps && <div className="mt-2 text-[13.5px] whitespace-pre-wrap text-fg-2">{plan.steps}</div>}
      {decided !== undefined
        ? <p className="mt-3 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2"><Check size={14} className="text-ok" />{decided === 'approved' ? '已批准，按计划执行' : `已批准，并补充：${decided}`}</p>
        : open ? <>
          {adding && <textarea autoFocus value={edits} onChange={(changeEvent) => setEdits(changeEvent.target.value)} rows={2} placeholder="执行时还要注意什么" aria-label="补充说明"
            className="mt-3 block w-full resize-none rounded-[9px] bg-sunken p-2.5 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => store.approvePlan(event.runId, eventId, adding ? edits : '')}>{adding && edits.trim() ? '补充后执行' : '按计划执行'}</Button>
            {!adding && <Button onClick={() => setAdding(true)}>补充说明</Button>}
            <Button variant="ghost" onClick={() => store.stopTask()}>不执行</Button>
          </div>
        </> : <p className="mt-3 mb-0 text-[13px] text-fg-3">这个计划没有执行。</p>}
    </div>
  </div>;
}

/** Turn a run that worked into a recipe that can be re-run with new parameters. */
function SaveRecipe({ runId, store }: { runId: string; store: Store }) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState('');
  const [saved, setSaved] = useState(false);
  if (saved) return <span className="ml-2 inline-flex items-center gap-1 text-ok"><Check size={13} />已存为配方，/recipe 可以复跑</span>;
  if (!naming) return <button className="ml-2 inline-flex items-center gap-1 text-fg-2 hover:text-fg" onClick={() => setNaming(true)}><BookMarked size={13} />存为配方</button>;
  return <form className="ml-2 inline-flex items-center gap-1.5" onSubmit={(event) => { event.preventDefault(); if (name.trim()) void store.saveRecipe(runId, name).then((ok) => setSaved(ok)); }}>
    <input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="配方名称" aria-label="配方名称"
      className="h-6 w-36 rounded-md bg-sunken px-2 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
    <button type="submit" disabled={!name.trim()} className="text-fg-2 hover:text-fg disabled:opacity-40">保存</button>
    <button type="button" onClick={() => setNaming(false)} className="text-fg-3 hover:text-fg">取消</button>
  </form>;
}

/** Several workers ran side by side; one line each, then the coordinator's summary. */
function WorkerGroup({ item }: { item: Extract<TimelineItem, { kind: 'group' }> }) {
  const ok = item.results.filter((result) => result.accepted === true).length;
  const unverified = item.results.filter((result) => result.accepted === undefined).length;
  return <div className="my-4 overflow-hidden rounded-xl card-surface px-4 py-3.5 text-[13px]">
    <p className="m-0 flex items-center gap-2 font-semibold text-heading"><Users size={15} className="text-brand" />{item.results.length} 个 Worker 并行完成
      <span className="font-normal text-fg-3">{ok} 个验收通过{unverified ? `，${unverified} 个未验收` : ''}{item.results.length - ok - unverified ? `，${item.results.length - ok - unverified} 个未通过` : ''}</span></p>
    <ul className="m-0 mt-2 grid list-none gap-1 p-0">
      {item.results.map((result) => {
        const good = result.accepted === true;
        return <li key={result.index} className="flex items-start gap-2" title={result.summary}>
          {good ? <Check size={14} className="mt-0.5 shrink-0 text-ok" /> : <X size={14} className="mt-0.5 shrink-0 text-danger" />}
          <span className="min-w-0 flex-1 text-fg-2">{result.title || `Worker ${result.index + 1}`} <span className="text-fg-3">{good ? '验收通过' : result.accepted === false ? '验收未通过' : result.status === 'failed' ? '执行失败' : '未验收'}</span>{result.verifier_note && <span className="block text-fg-3">{result.verifier_note}</span>}</span>
          {result.changed_files.length > 0 && <span className="shrink-0 text-[12px] text-fg-3" title={result.changed_files.join('\n')}>改了 {result.changed_files.length} 个文件</span>}
          {(result.summary || result.changed_files.length > 0) && <details className="basis-full pl-5 text-[12px] text-fg-3">
            <summary className="cursor-pointer">查看 Worker 结果和改动</summary>
            {result.summary && <p className="my-1 whitespace-pre-wrap text-fg-2">{result.summary}</p>}
            {result.changed_files.length > 0 && <ul className="my-1 list-disc pl-4">{result.changed_files.map((path) => <li key={path} className="break-all">{path}</li>)}</ul>}
          </details>}
        </li>;
      })}
    </ul>
    {item.summary && <p className="m-0 mt-2.5 whitespace-pre-wrap border-t border-line pt-2.5 leading-[1.7] text-fg-2">{item.summary}</p>}
  </div>;
}

const CHECK_KIND: Record<string, string> = { lint: '代码检查', typecheck: '类型检查', test: '测试', all: '全部检查' };

/** Structured lint / type / test results: counts up top, the problems listed with their location. */
function Checks({ item }: { item: Extract<TimelineItem, { kind: 'checks' }> }) {
  const [open, setOpen] = useState(item.results.failed > 0);
  const { results } = item;
  const failed = results.failed > 0 || results.items.some((entry) => entry.severity === 'error');
  const shown = open ? results.items.slice(0, 50) : [];
  return <div className="my-4 overflow-hidden rounded-xl card-surface text-[13px]">
    <button onClick={() => setOpen((value) => !value)} disabled={!results.items.length} className="flex w-full items-center gap-2 px-4 py-3 text-left">
      {failed ? <X size={15} className="shrink-0 text-danger" /> : <Check size={15} className="shrink-0 text-ok" />}
      <b className="font-semibold text-heading">{CHECK_KIND[results.kind] ?? '检查'}</b>
      <span className="text-fg-3">{results.tool}</span>
      <span className="ml-auto flex items-center gap-2 tabular-nums text-[12.5px]">
        <span className="text-ok">通过 {results.passed}</span>
        {results.failed > 0 && <span className="text-danger">失败 {results.failed}</span>}
        {results.skipped > 0 && <span className="text-fg-3">跳过 {results.skipped}</span>}
        {results.items.length > 0 && <ChevronRight size={14} className={cn('text-fg-3 transition-transform', open && 'rotate-90')} />}
      </span>
    </button>
    {shown.length > 0 && <ul className="m-0 grid max-h-[320px] list-none gap-1 overflow-auto border-t border-line px-4 py-2.5 font-mono text-[12px]">
      {shown.map((entry, index) => <li key={index} className="flex gap-2">
        <span className={cn('shrink-0', entry.severity === 'error' ? 'text-danger' : entry.severity === 'warning' ? 'text-brand' : 'text-fg-3')}>{entry.severity === 'error' ? '错误' : entry.severity === 'warning' ? '警告' : '提示'}</span>
        {entry.file && <span className="shrink-0 text-fg-2">{entry.file}{entry.line ? `:${entry.line}` : ''}</span>}
        <span className="min-w-0 text-fg-3">{entry.test ? `${entry.test}：` : ''}{entry.message}</span>
      </li>)}
      {results.items.length > shown.length && <li className="text-fg-3">还有 {results.items.length - shown.length} 条…</li>}
    </ul>}
  </div>;
}

const relativeTo = (root: string, path: string) => {
  const base = root.replace(/[\\/]+$/, '');
  return base && path.toLowerCase().startsWith(base.toLowerCase()) ? path.slice(base.length).replace(/^[\\/]+/, '') || path : path;
};

/** LSP 编辑后的新增诊断：默认只占一行，点开看明细（后端最多带 20 条）。 */
function LspNotice({ item }: { item: Extract<TimelineItem, { kind: 'lsp' }> }) {
  const [open, setOpen] = useState(false);
  const name = item.path.split(/[\\/]/).pop() || item.path || '文件';
  const truncated = item.count > item.diagnostics.length;
  return <div className="my-2 text-[12.5px] text-fg-2">
    <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}
      className="-mx-2 flex items-center gap-2 rounded-lg px-2 py-0.5 text-left hover:bg-hover">
      <FileWarning size={13} className="shrink-0 text-brand" />
      <span>发现 {item.count} 个新问题 · {name}</span>
      <ChevronRight size={12} className={cn('shrink-0 text-fg-3 transition-transform', open && 'rotate-90')} />
    </button>
    {open && <div className="anim-fade mt-1.5 mb-1">
      <DiagnosticsList diagnostics={item.diagnostics} />
      {truncated && <p className="m-0 mt-1 text-[11.5px] text-fg-3">仅显示前 20 条</p>}
    </div>}
  </div>;
}

/** First run in a directory: its AGENTS.md / CLAUDE.md only reach the Agent once you trust the directory. */
function Trust({ event, store }: { event: AgentEvent; store: Store }) {
  const eventId = String(event.data.event_id ?? '');
  const files = Array.isArray(event.data.files) ? event.data.files as Array<{ path?: string; bytes?: number }> : [];
  const answer = store.answers[eventId];
  const open = answer === undefined && store.getRun(event.runId)?.status === 'waiting';
  return <div className="my-4 overflow-hidden rounded-xl card-surface">
    <div className="flex gap-3.5 border-l-[3px] border-brand px-4 py-3.5">
      <FileCheck2 size={18} className="mt-0.5 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14px] font-semibold text-heading">要不要信任这个目录的规则文件？</p>
        <p className="mt-1 mb-0 text-[13px] text-fg-2">信任后，下面这些文件会作为指令交给 Atlas。规则文件可以让 Atlas 做任何事，只信任你了解的项目。</p>
        <p className="mt-1.5 mb-0 truncate font-mono text-[12px] text-fg-3" title={String(event.data.root ?? '')}>{String(event.data.root ?? '')}</p>
        <ul className="mt-1 mb-0 list-none p-0 font-mono text-[12px] text-fg-2">{files.map((file) => <li key={file.path} title={file.path}>{relativeTo(String(event.data.root ?? ''), file.path ?? '')}{file.bytes ? `（${Math.max(1, Math.round(file.bytes / 1024))} KB）` : ''}</li>)}</ul>
        {answer !== undefined
          ? <p className="mt-2.5 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2">{answer === 'trusted' ? <><Check size={14} className="text-ok" />已信任，以后不再询问</> : <><X size={14} className="text-fg-3" />这次不加载规则文件</>}</p>
          : open ? <div className="mt-3 flex gap-2">
            <Button variant="primary" onClick={() => store.trustRules(event.runId, eventId, true)}>信任并加载</Button>
            <Button onClick={() => store.trustRules(event.runId, eventId, false)}>不加载，继续</Button>
          </div> : <p className="mt-2 mb-0 text-[13px] text-fg-3">任务已经结束。</p>}
      </div>
    </div>
  </div>;
}
