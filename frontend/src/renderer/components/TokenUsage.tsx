import * as Popover from '@radix-ui/react-popover';
import { ChevronDown } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../ui/cn';
import { formatCost, formatTokens, type UsageSummary } from './runInsights';

/** Context categories get fixed hues that read on all three themes. */
const CATEGORY_COLOR: Record<string, string> = {
  system_prompt: '#C8964A', tool_definitions: '#5B8DEF', rules: '#3FA37A', skills: '#A77BD6',
  mcp: '#E07A5F', subagent_definitions: '#4FB3BF', memory: '#D4A373', conversation: '#7C8CA3',
};
const SEGMENT = { fresh: 'var(--brand)', cached: 'color-mix(in srgb, var(--brand) 38%, transparent)', output: 'var(--ok)' };

function Row({ color, label, value, note }: { color: string; label: string; value: string; note?: string }) {
  return <div className="flex items-center gap-2 text-[12.5px]">
    <i className="size-2 shrink-0 rounded-[3px]" style={{ background: color }} />
    <span className="text-fg-2">{label}</span>
    {note && <span className="text-[11.5px] text-fg-3">{note}</span>}
    <span className="flex-1" />
    <span className="tabular-nums text-fg">{value}</span>
  </div>;
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  return <div className="flex h-8 items-end gap-[3px]" aria-hidden>
    {values.slice(-60).map((value, index) => <i key={index} title={`第 ${index + 1} 次：${formatTokens(value)}`}
      className="block max-w-[14px] min-w-[3px] flex-1 rounded-t-[3px] bg-brand transition-[height] duration-500"
      style={{ height: `${Math.max(6, value / max * 100)}%`, opacity: 0.35 + 0.65 * (value / max) }} />)}
  </div>;
}

/** The full breakdown: where the tokens went, how full the context window is, which models were used. */
export function UsageBreakdown({ usage, title = '本次用量' }: { usage: UsageSummary; title?: string }) {
  const total = usage.input + usage.output;
  const fresh = Math.max(0, usage.input - usage.cached);
  const share = (value: number) => total ? `${value / total * 100}%` : '0%';
  const hit = usage.input ? Math.round(usage.cached / usage.input * 100) : 0;
  const context = usage.context;
  const categoryTotal = context?.categories.reduce((sum, item) => sum + item.tokens, 0) ?? 0;
  return <div className="grid gap-3.5">
    <div className="flex items-baseline gap-2">
      <span className="text-[12px] font-medium tracking-[.04em] text-fg-3">{title}</span>
      <span className="flex-1" />
      <b className="font-serif text-[22px] leading-none font-semibold tabular-nums text-heading">{formatTokens(total)}</b>
      <span className="text-[12px] text-fg-3">tokens</span>
    </div>

    <div className="grid gap-2">
      <div className="flex h-2 overflow-hidden rounded-full bg-sunken" role="img" aria-label={`新输入 ${fresh}，缓存命中 ${usage.cached}，输出 ${usage.output}`}>
        <i className="block h-full transition-[width] duration-500" style={{ width: share(usage.cached), background: SEGMENT.cached }} />
        <i className="block h-full transition-[width] duration-500" style={{ width: share(fresh), background: SEGMENT.fresh }} />
        <i className="block h-full transition-[width] duration-500" style={{ width: share(usage.output), background: SEGMENT.output }} />
      </div>
      <Row color={SEGMENT.fresh} label="新输入" value={formatTokens(fresh)} />
      <Row color={SEGMENT.cached} label="缓存命中" note={hit ? `命中率 ${hit}%` : undefined} value={formatTokens(usage.cached)} />
      <Row color={SEGMENT.output} label="输出" note={usage.reasoning ? `含推理 ${formatTokens(usage.reasoning)}` : undefined} value={formatTokens(usage.output)} />
      {usage.cacheWrite > 0 && <Row color="var(--line-strong)" label="写入缓存" value={formatTokens(usage.cacheWrite)} />}
    </div>

    <div className="flex flex-wrap gap-1.5 text-[11.5px]">
      <span className="rounded-md bg-sunken px-2 py-0.5 text-fg-2">调用模型 <b className="font-medium tabular-nums text-fg">{usage.requests}</b> 次</span>
      {usage.subtaskTokens > 0 && <span className="rounded-md bg-sunken px-2 py-0.5 text-fg-2">子 Agent <b className="font-medium tabular-nums text-fg">{formatTokens(usage.subtaskTokens)}</b></span>}
      {usage.sideTokens > 0 && <span className="rounded-md bg-sunken px-2 py-0.5 text-fg-2">后台（标题/记忆）<b className="font-medium tabular-nums text-fg">{formatTokens(usage.sideTokens)}</b></span>}
      {usage.cost !== null && <span className="rounded-md bg-brand-soft px-2 py-0.5 text-fg-2">费用约 <b className="font-medium tabular-nums text-fg">{formatCost(usage.cost)}</b></span>}
    </div>

    {usage.perRequest.length > 1 && <div className="grid gap-1">
      <span className="text-[11.5px] text-fg-3">每次调用</span>
      <Sparkline values={usage.perRequest} />
    </div>}

    {context && <div className="grid gap-2 border-t border-line pt-3">
      <div className="flex items-baseline gap-2 text-[12px]">
        <span className="font-medium text-fg-2">上下文窗口</span>
        {context.estimated && <span className="text-[11px] text-fg-3">估算</span>}
        <span className="flex-1" />
        <span className="tabular-nums text-fg-3">{formatTokens(context.used)} / {formatTokens(context.limit)}</span>
        <b className={cn('tabular-nums font-semibold', context.percent >= 80 ? 'text-danger' : 'text-fg')}>{context.percent}%</b>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full bg-sunken">
        {categoryTotal > 0
          ? context.categories.map((item) => <i key={item.id} className="block h-full" title={`${item.label} ${formatTokens(item.tokens)}`}
            style={{ width: `${item.tokens / context.limit * 100}%`, background: CATEGORY_COLOR[item.id] ?? 'var(--fg-3)' }} />)
          : <i className={cn('block h-full', context.percent >= 80 ? 'bg-danger' : 'bg-brand')} style={{ width: `${context.percent}%` }} />}
      </div>
      {categoryTotal > 0 && <div className="grid grid-cols-2 gap-x-4 gap-y-1">
        {context.categories.map((item) => <Row key={item.id} color={CATEGORY_COLOR[item.id] ?? 'var(--fg-3)'} label={item.label} value={formatTokens(item.tokens)} />)}
      </div>}
      {context.percent >= 80 && <p className="m-0 text-[11.5px] text-danger">快满了，可以用 /compact 压缩上下文</p>}
    </div>}

    {usage.byModel.length > 0 && <div className="grid gap-1.5 border-t border-line pt-3">
      <span className="text-[12px] font-medium text-fg-2">按模型</span>
      {usage.byModel.map((model) => {
        const tokens = model.input + model.output;
        return <div key={model.model} className="grid gap-1">
          <div className="flex items-baseline gap-2 text-[12px]">
            <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-fg" title={model.model}>{model.model}</span>
            <span className="shrink-0 text-fg-3">{model.requests} 次</span>
            <span className="w-12 shrink-0 text-right tabular-nums text-fg">{formatTokens(tokens)}</span>
          </div>
          <span className="h-[3px] overflow-hidden rounded-full bg-sunken"><i className="block h-full rounded-full bg-brand/70" style={{ width: `${total ? tokens / total * 100 : 0}%` }} /></span>
        </div>;
      })}
    </div>}
  </div>;
}

/** Popover shell shared by the token chip and the progress capsule. */
export function InsightPopover({ trigger, children, align = 'start', side = 'top', width = 340 }: { trigger: ReactNode; children: ReactNode; align?: 'start' | 'center' | 'end'; side?: 'top' | 'bottom'; width?: number }) {
  return <Popover.Root>
    <Popover.Trigger asChild>{trigger}</Popover.Trigger>
    <Popover.Portal>
      <Popover.Content side={side} align={align} sideOffset={8} collisionPadding={12}
        className="pop anim-pop z-[60] max-h-[min(560px,80vh)] overflow-y-auto rounded-2xl p-4 outline-none" style={{ width }}>
        {children}
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}

/** Inline "12.4k tokens · 缓存 28%" in the finished-turn line; click to unfold the breakdown card right in the thread. */
export function TokenUsageToggle({ usage, open, onToggle }: { usage: UsageSummary; open: boolean; onToggle: () => void }) {
  const total = usage.input + usage.output;
  const hit = usage.input ? Math.round(usage.cached / usage.input * 100) : 0;
  return <button type="button" onClick={onToggle} aria-expanded={open} aria-label="查看 token 用量明细"
    className="inline-flex items-center gap-1 tabular-nums text-fg-3 hover:text-fg">
    · {formatTokens(total)} tokens{hit > 0 ? ` · 缓存 ${hit}%` : ''}{usage.cost !== null ? ` · ${formatCost(usage.cost)}` : ''}
    <ChevronDown size={12} className={cn('transition-transform', open && 'rotate-180')} />
  </button>;
}

/** The unfolded breakdown card, sitting under the finished-turn line. */
export function TokenUsageCard({ usage }: { usage: UsageSummary }) {
  return <div className="anim-pop mt-2 mb-1 basis-full rounded-2xl card-surface px-4 py-3.5 text-fg">
    <UsageBreakdown usage={usage} />
  </div>;
}
