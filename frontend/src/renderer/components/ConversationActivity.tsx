import { memo, useEffect, useMemo, useState } from 'react';
import { BookMarked, Check, FileCheck2, FileWarning, SearchCheck, ChevronRight, CircleDashed, FileText, FlaskConical, ListChecks, MessageCircleQuestion, Repeat2, Send, ShieldAlert, Square, Users, X } from 'lucide-react';
import type { AgentEvent } from '../../types/runtime';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import ConversationMessage from './ConversationMessage';
import Mark from './Mark';
import ReviewFindingsCard from './ReviewFindingsCard';
import { DiagnosticsList } from './diagnostics';
import { buildTimeline, cacheShare, describeTool, duration, tokenCount, type Step, type TimelineItem } from './timeline';
import type { InspectorTab } from '../shell/Inspector';

interface ConversationActivityProps {
  events: AgentEvent[];
  store: ReturnType<typeof useAtlasStore.getState>;
  username: string;
  setTab: (tab: InspectorTab) => void;
}

/** 一条时间线渲染所需的上下文；由 ConversationActivity / MessageThread（虚拟列表）提供。 */
export interface TimelineRowContext {
  events: AgentEvent[];
  store: ReturnType<typeof useAtlasStore.getState>;
  username: string;
  setTab: (tab: InspectorTab) => void;
  busy: boolean;
}

/** 渲染单条时间线（用户消息、步骤、回复、审批卡片…）；虚拟列表按条复用，输出与整段渲染完全一致。 */
export const TimelineRow = memo(function TimelineRow({ item, context, firstInTurn, last }: { item: TimelineItem; context: TimelineRowContext; firstInTurn: boolean; last: boolean }) {
  const { events, store, username, setTab, busy } = context;
  switch (item.kind) {
    case 'user': return <ConversationMessage key={item.id} role="user" content={item.content} username={username} note={item.steered ? '插话' : undefined} />;
    case 'reply': return <ConversationMessage key={item.id} role="assistant" content={item.content} username={username} continued={!firstInTurn} streaming={item.streaming}
      status={item.status ?? (item.streaming ? '正在回复' : undefined)} working={item.streaming && busy} />;
    case 'steps': return <div key={item.id}>
      {firstInTurn && <TurnHeader working={last && busy} />}
      <StepTrack steps={item.steps} live={last && busy} runId={events[0]?.runId ?? ''} store={store} onCancelSubtask={(subtaskId) => { const runId = events[0]?.runId; if (runId) store.cancelSubtask(runId, subtaskId); }} />
    </div>;
    case 'artifact': return <div key={item.id} className="my-3 ml-10 flex items-center gap-3 rounded-xl card-surface px-3.5 py-2.5 text-[13px]">
      <FileText size={16} className="shrink-0 text-brand" />
      <div className="min-w-0 flex-1"><b className="font-medium text-fg">{item.name}</b>{item.summary && <p className="m-0 truncate text-fg-3">{item.summary}</p>}</div>
      <Button size="sm" variant="ghost" onClick={() => setTab('artifacts')}>查看</Button>
    </div>;
    case 'approval': return <Approval key={item.id} event={item.event} store={store} />;
    case 'question': return <Question key={item.id} event={item.event} store={store} />;
    case 'plan': return <Plan key={item.id} event={item.event} store={store} />;
    case 'trust': return <Trust key={item.id} event={item.event} store={store} />;
    case 'group': return <WorkerGroup key={item.id} item={item} />;
    case 'checks': return <Checks key={item.id} item={item} />;
    case 'notice': return <div key={item.id} className="my-3 ml-10 flex items-center gap-2 text-[12.5px] text-fg-2">
      {item.tone === 'switch' ? <Repeat2 size={13} className="shrink-0 text-brand" /> : <FlaskConical size={13} className="shrink-0 text-brand" />}
      <span>{item.text}</span>
    </div>;
    case 'lsp': return <LspNotice key={item.id} item={item} />;
    case 'review': return <ReviewFindingsCard key={item.id} item={item} store={store} />;
    case 'cancelled': return <div key={item.id} className="my-4 ml-10 flex items-center gap-2 text-[12.5px] text-fg-3">
      <Square size={12} />你停止了这次任务
    </div>;
    case 'done': {
      const tokens = tokenCount(item.usage);
      const cached = cacheShare(item.usage);
      const changed = item.changes && item.changes.files > 0 ? item.changes : null;
      return <div key={item.id} className="my-4 ml-10 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px] text-fg-3">
        <Check size={14} className="text-ok" />完成{item.startedAt ? `，用时 ${duration(item.startedAt, item.endedAt)}` : ''}
        {tokens && <span className="tabular-nums">· {tokens} tokens{cached ? `（${cached}）` : ''}</span>}
        {changed && <button className="text-fg-2 hover:text-fg" onClick={() => setTab('changes')}>
          · 改了 {changed.files} 个文件 <span className="tabular-nums text-ok">+{changed.additions}</span> <span className="tabular-nums text-danger">−{changed.deletions}</span>
        </button>}
        <button className="ml-2 text-fg-2 underline decoration-line-strong underline-offset-[3px] hover:text-fg" onClick={() => setTab('activity')}>全部步骤</button>
        {changed && <button className="ml-2 inline-flex items-center gap-1 text-fg-2 hover:text-fg"
          onClick={() => void store.sendMessage('/review')}><SearchCheck size={13} />审查本次改动</button>}
        {events[0] && <SaveRecipe runId={events[0].runId} store={store} />}
      </div>;
    }
    case 'failed': return <div key={item.id} role="alert" className="my-4 ml-10 rounded-xl bg-danger-soft px-4 py-3 text-[13px] text-danger">
      没能完成：{item.detail}
    </div>;
    default: return null;
  }
});

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
    return <TimelineRow key={item.id} item={item} context={{ events, store, username, setTab, busy }} firstInTurn={firstInTurn} last={last} />;
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
function StepTrack({ steps, live, runId, store, onCancelSubtask }: { steps: Step[]; live: boolean; runId: string; store: Store; onCancelSubtask: (subtaskId: string) => void }) {
  return <ol className="relative my-3 ml-[13px] list-none border-l border-line-strong py-1 pl-[26px]" aria-label="Atlas 的步骤">
    {steps.map((step) => <StepRow key={step.id} step={step} live={live} runId={runId} store={store} onCancelSubtask={onCancelSubtask} />)}
  </ol>;
}

function StepRow({ step, live, runId, store, onCancelSubtask }: { step: Step; live: boolean; runId: string; store: Store; onCancelSubtask: (subtaskId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [steerText, setSteerText] = useState('');
  const [steerState, setSteerState] = useState<{ sequence: number; text: string } | null>(null);
  const running = step.state === 'running' && live;
  const detail = [step.input && `输入\n${step.input}`, step.result && `结果\n${step.result}`, step.output && `输出\n${step.output}`].filter(Boolean).join('\n\n');
  const hasDetail = Boolean(detail);
  const steerFeedback = steerState && store.getRun(runId)?.events.find((event) => event.sequence > steerState.sequence
    && event.data.subtask_id === step.subtaskId
    && (event.type === 'subtask.steered' || event.type === 'subtask.steer_rejected'));
  // A failure you have to click to see is a failure hidden: show its evidence straight away.
  useEffect(() => { if (step.state === 'failed' && hasDetail) setOpen(true); }, [step.state, hasDetail]);
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
    {step.imagePreview && <img src={step.imagePreview} alt={step.target || '读取的图片'} className="mt-2 max-h-32 max-w-48 rounded-lg border border-line object-contain" />}
    {running && step.subtaskId && <button onClick={() => onCancelSubtask(step.subtaskId!)} className="ml-0 text-[12px] text-fg-3 hover:text-danger">停止这个子任务</button>}
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
    {open && <pre className="anim-fade mt-1.5 mb-1 max-h-72 overflow-auto rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] whitespace-pre-wrap text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">{detail}</pre>}
    {open && step.fullOutputPath && <p className="m-0 mb-1 text-[12px] text-fg-3">结果太长，只显示了开头和结尾。完整内容：
      {window.atlasDesktop?.openPath
        ? <button onClick={() => void window.atlasDesktop!.openPath(step.fullOutputPath!)} className="ml-1 font-mono text-fg-2 underline decoration-line-strong underline-offset-2 hover:text-fg">{step.fullOutputPath}</button>
        : <code className="ml-1">{step.fullOutputPath}</code>}</p>}
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

type Store = ReturnType<typeof useAtlasStore.getState>;

/** The Agent stopped to ask something; the run waits until this is answered or stopped. */
function Question({ event, store }: { event: AgentEvent; store: Store }) {
  const [text, setText] = useState('');
  const eventId = String(event.data.event_id ?? '');
  const question = String(event.data.question ?? '');
  const options = Array.isArray(event.data.options) ? event.data.options.map(String) : [];
  const answer = store.answers[eventId];
  const open = answer === undefined && store.getRun(event.runId)?.status === 'waiting';
  const send = (value: string) => { if (value.trim()) store.answerInput(event.runId, eventId, value.trim()); };
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface">
    <div className="flex gap-3.5 border-l-[3px] border-brand px-4 py-3.5">
      <MessageCircleQuestion size={18} className="mt-0.5 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[14px] font-semibold whitespace-pre-wrap text-heading">{question}</p>
        {answer !== undefined
          ? <p className="mt-2 mb-0 flex items-center gap-1.5 text-[13px] text-fg-2"><Check size={14} className="text-ok" />你的回答：{answer}</p>
          : open ? <>
            {options.length > 0 && <div className="mt-3 flex flex-wrap gap-2">{options.map((option) => <Button key={option} onClick={() => send(option)}>{option}</Button>)}</div>}
            <form className="mt-3 flex gap-2" onSubmit={(formEvent) => { formEvent.preventDefault(); send(text); }}>
              <input value={text} onChange={(changeEvent) => setText(changeEvent.target.value)} placeholder={options.length ? '或者直接写你的回答' : '写下你的回答'} aria-label="回答 Atlas 的问题"
                className="min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
              <Button type="submit" variant="primary" disabled={!text.trim()}>回答</Button>
            </form>
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
  const open = decided === undefined && store.getRun(event.runId)?.status === 'waiting';
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface">
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
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface px-4 py-3.5 text-[13px]">
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
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface text-[13px]">
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
  return <div className="my-2 ml-10 text-[12.5px] text-fg-2">
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
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface">
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
