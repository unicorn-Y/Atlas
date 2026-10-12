import { useEffect, useRef, useState } from 'react';
import { ChevronDown, SlidersHorizontal } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../ui/cn';

export type ThreadClassId = 'messages' | 'model' | 'tools' | 'approvals' | 'plans' | 'checks' | 'files' | 'status';
export type ThreadPresentationMode = 'normal' | 'thinking' | 'verbose' | 'everything' | 'detailed' | 'compact' | 'quiet' | 'messages' | 'custom';

export interface ThreadPresentationSettings {
  mode: ThreadPresentationMode;
  show: Record<ThreadClassId, boolean>;
  collapsed: Record<ThreadClassId, boolean>;
  groupByClass: boolean;
  announceCompletedReplies: boolean;
}

export const THREAD_CLASSES: Array<{ id: ThreadClassId; label: string }> = [
  { id: 'messages', label: '用户与回复' },
  { id: 'model', label: '模型推理与调用' },
  { id: 'tools', label: '工具与子任务' },
  { id: 'approvals', label: '问题与权限' },
  { id: 'plans', label: '计划' },
  { id: 'checks', label: '检查与审查' },
  { id: 'files', label: '产物与完成状态' },
  { id: 'status', label: '状态提示' },
];

const STORAGE_KEY = 'atlas.thread-presentation.v1';
const ALL_VISIBLE: Record<ThreadClassId, boolean> = {
  messages: true, model: true, tools: true, approvals: true, plans: true, checks: true, files: true, status: true,
};
const NONE_COLLAPSED: Record<ThreadClassId, boolean> = {
  messages: false, model: false, tools: false, approvals: false, plans: false, checks: false, files: false, status: false,
};

export function settingsForMode(mode: ThreadPresentationMode): ThreadPresentationSettings {
  if (mode === 'normal') return {
    mode, show: { ...ALL_VISIBLE },
    collapsed: { ...NONE_COLLAPSED, tools: true, checks: true, files: true, status: true },
    groupByClass: true, announceCompletedReplies: true,
  };
  if (mode === 'thinking') return {
    mode, show: { ...ALL_VISIBLE },
    collapsed: { ...NONE_COLLAPSED, tools: true, checks: true, files: true, status: true },
    groupByClass: true, announceCompletedReplies: true,
  };
  if (mode === 'verbose') return {
    mode, show: { ...ALL_VISIBLE }, collapsed: { ...NONE_COLLAPSED },
    groupByClass: false, announceCompletedReplies: true,
  };
  if (mode === 'compact') return {
    mode, show: { ...ALL_VISIBLE },
    collapsed: { ...NONE_COLLAPSED, model: true, tools: true, checks: true, files: true, status: true },
    groupByClass: true, announceCompletedReplies: true,
  };
  if (mode === 'quiet') return {
    mode,
    show: { messages: true, model: true, tools: false, approvals: true, plans: true, checks: false, files: true, status: true },
    collapsed: { ...NONE_COLLAPSED, model: true }, groupByClass: false, announceCompletedReplies: true,
  };
  if (mode === 'messages') return {
    mode,
    show: { messages: true, model: false, tools: false, approvals: false, plans: false, checks: false, files: false, status: false },
    collapsed: { ...NONE_COLLAPSED }, groupByClass: false, announceCompletedReplies: true,
  };
  return { mode, show: { ...ALL_VISIBLE }, collapsed: { ...NONE_COLLAPSED }, groupByClass: mode === 'detailed', announceCompletedReplies: true };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function readSettings(): ThreadPresentationSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return settingsForMode('everything');
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || !['normal', 'thinking', 'verbose', 'everything', 'detailed', 'compact', 'quiet', 'messages', 'custom'].includes(String(parsed.mode))) {
      return settingsForMode('everything');
    }
    const fallback = settingsForMode(parsed.mode as ThreadPresentationMode);
    const show = isRecord(parsed.show) ? parsed.show : {};
    const collapsed = isRecord(parsed.collapsed) ? parsed.collapsed : {};
    const valid = (key: ThreadClassId, source: Record<string, unknown>, defaults: Record<ThreadClassId, boolean>) =>
      typeof source[key] === 'boolean' ? source[key] as boolean : defaults[key];
    return {
      mode: parsed.mode as ThreadPresentationMode,
      show: Object.fromEntries(THREAD_CLASSES.map(({ id }) => [id, valid(id, show, fallback.show)])) as Record<ThreadClassId, boolean>,
      collapsed: Object.fromEntries(THREAD_CLASSES.map(({ id }) => [id, valid(id, collapsed, fallback.collapsed)])) as Record<ThreadClassId, boolean>,
      groupByClass: typeof parsed.groupByClass === 'boolean' ? parsed.groupByClass : fallback.groupByClass,
      announceCompletedReplies: typeof parsed.announceCompletedReplies === 'boolean' ? parsed.announceCompletedReplies : true,
    };
  } catch {
    return settingsForMode('everything');
  }
}

export function useThreadPresentationSettings() {
  const [settings, setSettings] = useState(readSettings);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(settings)); } catch { /* Storage can be disabled by the host. */ }
  }, [settings]);
  return [settings, setSettings] as const;
}

export function ThreadPresentationControls({ settings, onChange }: {
  settings: ThreadPresentationSettings;
  onChange: (settings: ThreadPresentationSettings) => void;
  hasReasoning: boolean;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
      requestAnimationFrame(() => triggerRef.current?.focus());
    };
    document.addEventListener('keydown', closeOnEscape);
    return () => document.removeEventListener('keydown', closeOnEscape);
  }, [open]);
  const chooseMode = (mode: ThreadPresentationMode) => {
    onChange(mode === 'custom'
      ? { ...settings, mode }
      : settingsForMode(mode));
  };
  const changeClass = (id: ThreadClassId, field: 'show' | 'collapsed', value: boolean) => {
    onChange({ ...settings, mode: 'custom', [field]: { ...settings[field], [id]: value } });
  };

  return <div className="sticky top-2 z-30 h-0 overflow-visible pointer-events-none">
    <div className="relative w-fit max-w-full pointer-events-auto">
      <button ref={triggerRef} type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls="thread-presentation-panel"
        className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[12px] text-fg-2 shadow hover:bg-surface-2"
        aria-label="时间线显示设置">
        <SlidersHorizontal size={14} aria-hidden="true" />显示方式 <span className="text-fg-3">· {MODE_LABELS[settings.mode]}</span><ChevronDown size={12} aria-hidden="true" />
      </button>
      {open && <div id="thread-presentation-panel" className="absolute left-0 top-9 w-[min(360px,calc(100vw-2rem))] rounded-xl border border-border bg-surface p-3 shadow-xl" role="group" aria-label="时间线显示选项">
        <fieldset className="m-0 border-0 p-0">
          <legend className="mb-2 text-[12px] font-semibold text-heading">预设</legend>
          <div className="grid grid-cols-2 gap-1.5">
            {MODES.map(({ id, label }) => <button key={id} type="button" aria-pressed={settings.mode === id} onClick={() => chooseMode(id)}
              className={cn('rounded-lg border px-2 py-1.5 text-left text-[12px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand', settings.mode === id ? 'border-brand bg-brand-soft text-heading' : 'border-line text-fg-2 hover:bg-hover')}>
              <span className="block">{label}</span>
              {id === 'normal' && <span className="mt-0.5 block text-[10.5px] font-normal text-fg-3">文本完整显示，活动摘要收起</span>}
              {id === 'thinking' && <span className="mt-0.5 block text-[10.5px] font-normal text-fg-3">显示思考，活动摘要收起</span>}
              {id === 'verbose' && <span className="mt-0.5 block text-[10.5px] font-normal text-fg-3">展开 Atlas 已记录的全部活动</span>}
            </button>)}
          </div>
        </fieldset>
        <div className="my-3 border-t border-line" />
        <label className="flex items-center gap-2 text-[12px] text-fg-2">
          <input type="checkbox" checked={settings.groupByClass} onChange={(event) => onChange({ ...settings, mode: 'custom', groupByClass: event.target.checked })} />
          按类别分组连续活动
        </label>
        <label className="mt-2 flex items-center gap-2 text-[12px] text-fg-2">
          <input type="checkbox" checked={settings.announceCompletedReplies} onChange={(event) => onChange({ ...settings, mode: 'custom', announceCompletedReplies: event.target.checked })} />
          屏幕阅读器朗读完成的回复
        </label>
        <div className="mt-2.5 grid gap-2">
          {THREAD_CLASSES.map(({ id, label }) => <div key={id} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px]">
            <label className="flex min-w-0 flex-1 items-center gap-2 text-fg-2">
              <input type="checkbox" checked={settings.show[id]} onChange={(event) => changeClass(id, 'show', event.target.checked)} />{label}
            </label>
            <label className="flex items-center gap-1.5 text-fg-3">
              <input type="checkbox" checked={settings.collapsed[id]} onChange={(event) => changeClass(id, 'collapsed', event.target.checked)} />默认收起
            </label>
          </div>)}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <button type="button" onClick={() => onChange(settingsForMode('everything'))} className="rounded-md px-2 py-1 text-[11.5px] text-fg-2 hover:bg-hover">重置为全部显示</button>
          <button type="button" onClick={() => { setOpen(false); requestAnimationFrame(() => triggerRef.current?.focus()); }} className="rounded-md px-2 py-1 text-[11.5px] text-fg-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">完成</button>
        </div>
      </div>}
    </div>
  </div>;
}

const MODES: Array<{ id: ThreadPresentationMode; label: string }> = [
  { id: 'normal', label: 'Normal · 常规' },
  { id: 'thinking', label: 'Thinking · 思考' },
  { id: 'verbose', label: 'Verbose · 详细' },
  { id: 'everything', label: 'Everything · 全部' },
  { id: 'detailed', label: 'Detailed · 详细分组' },
  { id: 'compact', label: 'Compact · 紧凑' },
  { id: 'quiet', label: 'Quiet · 安静' },
  { id: 'messages', label: 'Messages only · 仅消息' },
  { id: 'custom', label: 'Custom · 自定义' },
];
const MODE_LABELS = Object.fromEntries(MODES.map(({ id, label }) => [id, label.split(' · ')[0]])) as Record<ThreadPresentationMode, string>;

export function ThreadClassGroup({ classId, label, count, collapsed, children }: {
  classId: ThreadClassId;
  label: string;
  count: number;
  collapsed: boolean;
  children: ReactNode;
}) {
  return <details open={!collapsed} className="my-2 rounded-xl border border-line/70 bg-surface/30" data-timeline-class={classId}>
    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2 text-[12px] text-fg-2 hover:bg-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
      <ChevronDown size={13} aria-hidden="true" className="shrink-0 transition-transform [details:not([open])_&]:-rotate-90" />
      <span>{label}</span><span className="ml-auto tabular-nums text-fg-3">{count} 项</span>
    </summary>
    <div className="border-t border-line/70 px-2 py-1.5">{children}</div>
  </details>;
}
