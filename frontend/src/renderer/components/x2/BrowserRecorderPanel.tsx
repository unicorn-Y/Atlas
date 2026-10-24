import { useMemo, useState, type FormEvent } from 'react';
import { Check, CircleAlert, LoaderCircle, Play, ScrollText, Square } from 'lucide-react';
import type { AgentEvent } from '../../../types/runtime';
import { controlBrowserRecording, recordingToSkill, type RecordingSkill } from '../../services/x2Api';
import { useAtlasStore } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

export interface BrowserStepView { id: string; index: number; action: string; target: string; url: string }

/** 从 browser.step 事件流里整理出可渲染的步骤；runId 给定时只看那一次任务。 */
export function browserStepsFromEvents(events: AgentEvent[], runId?: string): BrowserStepView[] {
  const seen = new Set<string>();
  const steps: BrowserStepView[] = [];
  for (const event of events) {
    if (event.type !== 'browser.step' || seen.has(event.id)) continue;
    if (runId && event.runId !== runId) continue;
    seen.add(event.id);
    steps.push({
      id: event.id,
      index: typeof event.data.index === 'number' ? event.data.index : steps.length + 1,
      action: typeof event.data.action === 'string' && event.data.action ? event.data.action : '浏览器操作',
      target: typeof event.data.target === 'string' ? event.data.target : '',
      url: typeof event.data.url === 'string' ? event.data.url : '',
    });
  }
  return steps;
}

function StepList({ steps }: { steps: BrowserStepView[] }) {
  if (!steps.length) return <p className="m-0 text-[13px] text-fg-3">还没有录到步骤；点一下页面上的操作就会出现在这里。</p>;
  return <ol className="m-0 grid list-none gap-1.5 p-0">
    {steps.map((step) => <li key={step.id} className="flex items-baseline gap-2 text-[13px]">
      <span className="w-5 shrink-0 text-right text-[12px] tabular-nums text-fg-3">{step.index}</span>
      <span className="min-w-0 text-fg">{step.action}</span>
      {step.target && <code className="min-w-0 truncate rounded-[5px] bg-code px-1.5 font-mono text-[12px] text-fg-2">{step.target}</code>}
      {step.url && <span className="min-w-0 truncate text-[12px] text-fg-3">{step.url}</span>}
    </li>)}
  </ol>;
}

/** SKILL.md 预览块：保存前给人过目的技能内容。 */
export function SkillPreview({ preview }: { preview: RecordingSkill }) {
  if (!preview.skill_md) return null;
  return <div className="anim-fade">
    <p className="m-0 mb-1 text-[12px] text-fg-3">SKILL.md 预览（保存前请确认步骤无误）：</p>
    <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-code p-3 font-mono text-[12px] leading-[1.6] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">{preview.skill_md}</pre>
  </div>;
}

/** 存为技能：先 dry_run 拿 SKILL.md 预览，确认无误再真正保存。 */
export function SkillForm({ apiBaseUrl, recordingId, defaultName }: {
  apiBaseUrl: string;
  recordingId: string;
  defaultName?: string;
}) {
  const [name, setName] = useState('');
  const [preview, setPreview] = useState<RecordingSkill | null>(null);
  const [saved, setSaved] = useState<RecordingSkill | null>(null);
  const [busy, setBusy] = useState<'' | 'preview' | 'save'>('');
  const [error, setError] = useState('');
  const submit = (dryRun: boolean) => (event: FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(dryRun ? 'preview' : 'save');
    setError('');
    recordingToSkill(apiBaseUrl, recordingId, { dry_run: dryRun, name: name.trim() || undefined })
      .then((skill) => {
        if (dryRun) { setPreview(skill); setSaved(null); }
        else { setSaved(skill); setPreview(null); }
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(''));
  };
  if (saved) return <p className="m-0 flex items-center gap-1.5 text-[13px] text-ok">
    <Check size={14} className="shrink-0" />已存为技能{saved.name ? `「${saved.name}」` : ''}{saved.path ? <code className="rounded-[5px] bg-code px-1.5 font-mono text-[12px] text-fg-2">{saved.path}</code> : ''}，之后可以直接让 Atlas 复用。
  </p>;
  return <form onSubmit={submit(false)} className="mt-3 grid gap-2 border-t border-line pt-3">
    <p className="m-0 text-[13px] text-fg-2"><ScrollText size={13} className="mr-1 inline align-[-2px] text-brand" />把这次录制的步骤存成技能，以后一句话就能复跑。</p>
    <div className="flex flex-wrap items-center gap-2">
      <input value={name} onChange={(event) => setName(event.target.value)} placeholder={defaultName || '技能名称，例如：导出每周订单报表'} aria-label="技能名称"
        className="h-8 min-w-0 flex-1 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <Button size="md" variant="secondary" disabled={busy !== ''} onClick={submit(true)}>
        {busy === 'preview' ? <LoaderCircle size={14} className="spin" /> : <ScrollText size={14} />}生成预览
      </Button>
      <Button size="md" variant="primary" type="submit" disabled={busy !== ''}>
        {busy === 'save' ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}保存为技能
      </Button>
    </div>
    {preview?.skill_md && <SkillPreview preview={preview} />}
    {error && <p role="alert" className="m-0 flex items-center gap-1 text-[12.5px] text-danger"><CircleAlert size={13} className="shrink-0" />{error}。可以再试一次。</p>}
  </form>;
}

/**
 * 浏览器操作录制：开始/停止（POST /api/browser/recordings），录制中的每一步来自 browser.step 事件实时滚动，
 * 停止后可把步骤存为技能（先预览 SKILL.md 再保存）。
 * 事件来源：宿主直接传某次任务的事件（events），不传则自己从全局运行流里取。
 */
export default function BrowserRecorderPanel({ apiBaseUrl, runId, events, className, userSteps = [], onRecordingChange }: {
  apiBaseUrl: string;
  /** 只显示这次任务的步骤；缺省时显示所有 browser.step。 */
  runId?: string;
  /** 宿主持有的事件流（如活动任务的 run.events）；缺省时从全局 store 订阅。 */
  events?: AgentEvent[];
  userSteps?: BrowserStepView[];
  onRecordingChange?: (recording: boolean, recordingId: string | null) => void;
  className?: string;
}) {
  const runs = useAtlasStore((state) => state.runs);
  const storeEvents = useMemo(() => runs.flatMap((run) => run.events), [runs]);
  const merged = events ?? storeEvents;
  const steps = useMemo(() => [...browserStepsFromEvents(merged, runId), ...userSteps], [merged, runId, userSteps]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const toggle = () => {
    if (busy) return;
    const starting = !recording;
    setBusy(true);
    setError('');
    controlBrowserRecording(apiBaseUrl, starting ? 'start' : 'stop', starting ? undefined : sessionId ?? undefined)
      .then((session) => {
        if (starting && session.recording_id) setSessionId(session.recording_id);
        setRecording(starting);
        onRecordingChange?.(starting, session.recording_id ?? sessionId);
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  return <section aria-label="浏览器操作录制" className={className}>
    <div className="flex flex-wrap items-center gap-2">
      <h3 className="m-0 text-[15px] font-semibold text-heading">浏览器操作录制</h3>
      {recording && <span className="inline-flex items-center gap-1.5 rounded-full bg-danger-soft px-2 py-0.5 text-[11.5px] text-danger">
        <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-danger" />录制中 · {steps.length} 步
      </span>}
      <span className="flex-1" />
      <Button size="sm" variant={recording ? 'danger' : 'primary'} disabled={busy} onClick={toggle}>
        {busy ? <LoaderCircle size={13} className="spin" /> : recording ? <Square size={13} /> : <Play size={13} />}
        {recording ? '停止录制' : '开始录制'}
      </Button>
    </div>
    <p className="m-0 mt-1 mb-3 text-[13px] text-fg-3">把你要 Atlas 学的一串网页操作录下来：每一步都会列在下面，停止后可以检查并存为技能。</p>
    {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{recording ? '停止' : '开始'}录制失败：{error}。可以再试一次。</p>}
    <div className={cn(!steps.length && !recording && 'text-fg-3')}>
      <StepList steps={steps} />
    </div>
    {sessionId && !recording && <SkillForm apiBaseUrl={apiBaseUrl} recordingId={sessionId} />}
  </section>;
}
