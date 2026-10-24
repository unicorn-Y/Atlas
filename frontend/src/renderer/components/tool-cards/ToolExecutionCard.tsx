import { useEffect, useState, type ReactNode } from 'react';
import {
  Activity, Brain, Check, ChevronRight, Code2, FileDiff, FileText, GitBranch,
  Globe, Image, ListChecks, LoaderCircle, MessageCircleQuestion, Monitor,
  Pencil, Search, Terminal, Users, Wrench, X, type LucideIcon,
} from 'lucide-react';
import { cn } from '../../ui/cn';
import ClipboardAction from '../message-actions/ClipboardAction';
import ImagePreview from '../message-actions/ImagePreview';
import { duration, type Step, type ToolCategory } from '../timeline';

export const CATEGORY: Record<ToolCategory, { label: string; icon: LucideIcon }> = {
  'file-read': { label: '读取文件', icon: FileText },
  'file-write': { label: '写入文件', icon: FileText },
  'file-edit': { label: '编辑文件', icon: Pencil },
  'file-patch': { label: '应用补丁', icon: FileDiff },
  shell: { label: '终端命令', icon: Terminal },
  exec: { label: '执行程序', icon: Code2 },
  search: { label: '搜索', icon: Search },
  todo: { label: '更新待办', icon: ListChecks },
  plan: { label: '计划', icon: ListChecks },
  question: { label: '向你提问', icon: MessageCircleQuestion },
  agent: { label: 'Agent / Task', icon: Users },
  browser: { label: '浏览器', icon: Globe },
  computer: { label: '桌面操作', icon: Monitor },
  git: { label: 'Git', icon: GitBranch },
  process: { label: '后台进程', icon: Activity },
  web: { label: '网页 / 网络', icon: Globe },
  checks: { label: '运行检查', icon: Check },
  image: { label: '图像', icon: Image },
  memory: { label: '记忆', icon: Brain },
  other: { label: '工具', icon: Wrench },
};

const compact = (value: string) => value.replace(/\s+/g, ' ').trim();

export default function ToolExecutionCard({ step, live, children }: {
  step: Step;
  live: boolean;
  children?: ReactNode;
}) {
  const [open, setOpen] = useState(step.state === 'failed');
  const active = step.state === 'running' && live;
  const hasDetails = Boolean(step.input || step.result || step.output || step.fullOutputPath);
  const hasCopyableFailureReason = Boolean(step.failureReason && !['工具返回失败状态', '子任务执行失败', 'Hook 执行失败'].includes(step.failureReason));
  const { label, icon: Icon } = CATEGORY[step.category] ?? CATEGORY.other;
  const mcpTool = /^(?:mcp__|mcp\.)/i.test(step.toolName) || /"server(?:_name)?"\s*:/.test(step.input ?? '');
  const mcpServer = (() => {
    const explicit = /"server(?:_name)?"\s*:\s*"([^"]+)"/.exec(step.input ?? '')?.[1];
    const encoded = /^mcp__(.+?)__(.+)$/i.exec(step.toolName)?.[1];
    const dotted = /^mcp\.([^.]+)\./i.exec(step.toolName)?.[1];
    return explicit || encoded || dotted || 'MCP';
  })();
  const status = step.state === 'failed' ? '失败'
    : step.state === 'cancelled' ? '已取消'
      : active ? '进行中'
        : step.state === 'running' ? '未完成'
          : `完成${step.endedAt ? ` · ${duration(step.startedAt, step.endedAt)}` : ''}`;

  useEffect(() => {
    if (step.state === 'failed') setOpen(true);
  }, [step.state]);

  return <div className="overflow-hidden rounded-xl card-surface text-[13px]">
    <div className="px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <Icon size={15} className={cn('shrink-0', step.state === 'failed' ? 'text-danger' : active ? 'text-brand' : 'text-fg-3')} />
        <span className="shrink-0 font-medium text-fg">{label}</span>
        {step.target && <span className="min-w-0 truncate text-[10.5px] text-fg-3">{step.toolName}</span>}
        {mcpTool && <span className="shrink-0 rounded bg-brand-soft px-1.5 py-0.5 text-[10.5px] text-brand">{mcpServer} · MCP</span>}
        <code className="min-w-0 truncate rounded-[5px] bg-code px-1.5 font-mono text-[11.5px] text-fg-2" title={step.target ?? step.toolName}>
          {step.target || step.toolName}
        </code>
        <span className="flex-1" />
        <span className={cn('inline-flex shrink-0 items-center gap-1 text-[11.5px]',
          step.state === 'failed' ? 'text-danger' : active ? 'text-brand' : step.state === 'done' ? 'text-ok' : 'text-fg-3')}>
          {active ? <LoaderCircle size={12} className="spin" /> : step.state === 'failed' ? <X size={12} /> : step.state === 'done' ? <Check size={12} /> : null}
          {status}
        </span>
      </div>
      {step.summary && <p className="m-0 mt-1.5 pl-[23px] break-words leading-[1.55] text-fg-2">{compact(step.summary)}</p>}
      {step.failureReason && <p role="alert" className="m-0 mt-2 flex items-start gap-2 rounded-lg bg-danger-soft px-2.5 py-2 pl-[23px] leading-[1.55] text-danger">
        <span className="min-w-0 flex-1 break-words">失败原因：{step.failureReason}</span>
        {step.state === 'failed' && hasCopyableFailureReason && <ClipboardAction text={step.failureReason} label="复制失败原因" />}
      </p>}
      {step.imagePreview && <div className="mt-2 ml-[23px] max-w-48 [&_img]:!max-h-32 [&_img]:rounded-lg [&_img]:border [&_img]:border-line [&_img]:object-contain">
        <ImagePreview src={step.imagePreview} alt={step.target || '工具读取的图片'} title="点击预览工具返回的图片" />
      </div>}
      {step.subtaskId && children && <div className="mt-2 pl-[23px]">{children}</div>}
      {hasDetails && <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}
        className="mt-2 ml-[21px] inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-fg-3 hover:bg-hover hover:text-fg">
        <ChevronRight size={12} className={cn('transition-transform', open && 'rotate-90')} />{open ? '收起原始详情' : step.output && step.output.length > 500 ? '展开长输出与参数' : '查看原始详情'}
      </button>}
      {open && hasDetails && <div className="anim-fade mt-2 ml-[23px] grid gap-2">
        {step.input && <Detail label="输入参数" value={step.input} />}
        {step.result && <Detail label="工具结果" value={step.result} copyLabel={step.state === 'failed' ? '复制工具结果' : undefined} />}
        {step.output && <Detail label="运行输出" value={step.output} copyLabel={step.state === 'failed' ? '复制运行输出' : undefined} />}
        {step.fullOutputPath && <p className="m-0 text-[11.5px] text-fg-3">
          完整输出：{window.atlasDesktop?.openPath
            ? <button type="button" onClick={() => void window.atlasDesktop!.openPath(step.fullOutputPath!)} className="break-all font-mono text-fg-2 underline decoration-line-strong underline-offset-2 hover:text-fg">{step.fullOutputPath}</button>
            : <code className="break-all">{step.fullOutputPath}</code>}
        </p>}
      </div>}
    </div>
  </div>;
}

export function Detail({ label, value, copyLabel }: { label: string; value: string; copyLabel?: string }) {
  return <div className="min-w-0 overflow-hidden rounded-lg bg-code shadow-[inset_0_0_0_1px_var(--line)]">
    <div className="flex items-center justify-between border-b border-line px-2.5 py-1">
      <p className="m-0 text-[10.5px] text-fg-3">{label}</p>
      {copyLabel && <ClipboardAction text={value} label={copyLabel} />}
    </div>
    <pre className="m-0 max-h-72 overflow-auto px-2.5 py-2 font-mono text-[11.5px] leading-[1.55] whitespace-pre-wrap break-words text-fg-2">{value}</pre>
  </div>;
}
