import { cn } from '../ui/cn';
import type { LspDiagnosticItem } from './timeline';

/** 诊断严重级的圆点配色（Tailwind 调色板，三套主题都可读）与中文标签。 */
export const DIAGNOSTIC_TONE: Record<string, string> = {
  error: 'text-red-500', warning: 'text-amber-500', information: 'text-sky-500', hint: 'text-fg-3',
};
export const SEVERITY_LABEL: Record<string, string> = { error: '错误', warning: '警告', information: '提示', hint: '建议' };

/** 一次诊断列表的头部摘要：按严重级给一排小圆点。 */
export function SeverityDots({ diagnostics }: { diagnostics: LspDiagnosticItem[] }) {
  const counts = new Map<string, number>();
  for (const item of diagnostics) counts.set(item.severity, (counts.get(item.severity) ?? 0) + 1);
  return <span aria-label="问题级别" className="flex items-center gap-0.5">
    {[...counts.entries()].map(([severity, count]) =>
      <span key={severity} title={`${SEVERITY_LABEL[severity] ?? severity} ${count}`}
        className={cn('size-1.5 rounded-full bg-current', DIAGNOSTIC_TONE[severity] ?? 'text-fg-3')} />)}
  </span>;
}

/** 一串 LSP 诊断：行号 + 消息 + 代码，等宽字体；时间线、「改动」面板、InitDialog 共用。 */
export function DiagnosticsList({ diagnostics }: { diagnostics: LspDiagnosticItem[] }) {
  if (!diagnostics.length) return null;
  return <ul className="m-0 grid list-none gap-1 p-0 font-mono text-[12px]">
    {diagnostics.map((item, index) => <li key={index} className="flex items-start gap-2 rounded-lg bg-code px-2.5 py-1.5">
      <span aria-label={SEVERITY_LABEL[item.severity] ?? item.severity} title={SEVERITY_LABEL[item.severity] ?? item.severity}
        className={cn('mt-[6px] size-[7px] shrink-0 rounded-full bg-current', DIAGNOSTIC_TONE[item.severity] ?? 'text-fg-3')} />
      <span className="w-12 shrink-0 text-right tabular-nums text-fg-3">{item.line}{item.column ? `:${item.column}` : ''}</span>
      <span className="min-w-0 flex-1 whitespace-pre-wrap break-all text-fg-2">{item.message}</span>
      {item.code && <code className="shrink-0 rounded-[5px] bg-overlay px-1.5 text-[11px] text-fg-3">{item.code}</code>}
    </li>)}
  </ul>;
}
