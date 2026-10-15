import { useEffect, useRef, useState } from 'react';
import { Check, ChevronDown, ChevronRight, ChevronUp, ClipboardCheck, ClipboardCopy, FileSearch, Hammer, ListChecks, SearchCheck, ShieldCheck } from 'lucide-react';
import type { useAtlasStore } from '../store/useAtlasStore';
import { cn } from '../ui/cn';
import type { ReviewFinding, TimelineItem } from './timeline';

type Store = ReturnType<typeof useAtlasStore.getState>;

/** 审查严重级的中文标签、小圆点和徽标配色（只用 Tailwind 调色板与主题 token）。 */
export const FINDING_SEVERITY: Record<ReviewFinding['severity'], { label: string; chip: string; dot: string }> = {
  blocker: { label: '阻断', chip: 'bg-danger-soft text-danger', dot: 'bg-danger' },
  major: { label: '主要', chip: 'bg-amber-500/15 text-amber-600', dot: 'bg-amber-500' },
  minor: { label: '次要', chip: 'bg-sunken text-fg-3', dot: 'bg-fg-3' },
};

/** `文件:行号`，行号缺失时只给文件。 */
export const findingWhere = (finding: ReviewFinding) => `${finding.file}${finding.line ? `:${finding.line}` : ''}`;

/** 复制/发回对话共用的纯文本格式：一条发现一段，位置、说明、证据、建议修法都在。 */
export function formatFinding(finding: ReviewFinding, index?: number): string {
  const head = `${index === undefined ? '' : `${index + 1}. `}[${FINDING_SEVERITY[finding.severity].label}] ${findingWhere(finding)} ${finding.title}`;
  return `${head}\n   说明：${finding.explanation}\n   证据：${finding.evidence}\n   建议修法：${finding.suggested_fix}`;
}

/** 修复某一条的指令：按位置逐项列清，Atlas 直接照单开修。 */
export const fixMessage = (finding: ReviewFinding) =>
  `请修复代码审查发现的这个问题：\n文件：${findingWhere(finding)}\n标题：${finding.title}\n说明：${finding.explanation}\n证据：${finding.evidence}\n建议修法：${finding.suggested_fix}`;

/** /review 的结构化结论：头部计数、逐条展开、一键发回对话修复。 */
export default function ReviewFindingsCard({ item, store }: { item: Extract<TimelineItem, { kind: 'review' }>; store: Store }) {
  const [copied, setCopied] = useState(false);
  const [dismissed, setDismissed] = useState<number[]>([]);
  const [sent, setSent] = useState<number[]>([]);
  const [sending, setSending] = useState<number[]>([]);
  const [sendError, setSendError] = useState('');
  const [activeFinding, setActiveFinding] = useState<number | null>(null);
  const findingRefs = useRef<Record<number, HTMLLIElement | null>>({});
  if (!item.findings.length) {
    return <div className="my-4 overflow-hidden rounded-xl card-surface">
      <div className="flex items-center gap-2.5 border-l-[3px] border-ok bg-ok-soft px-4 py-3 text-[13px] text-ok">
        <ShieldCheck size={16} className="shrink-0" />代码审查 · {item.scopeLabel}：没有发现问题
      </div>
    </div>;
  }
  const counts: Record<ReviewFinding['severity'], number> = { blocker: 0, major: 0, minor: 0 };
  for (const finding of item.findings) counts[finding.severity] += 1;
  const applyFixes = async () => {
    const pending = item.findings.map((finding, index) => ({ finding, index })).filter(({ index }) => !dismissed.includes(index) && !sent.includes(index));
    if (!pending.length || sending.length) return;
    const body = pending.map(({ finding }, index) => `${index + 1}. 文件：${findingWhere(finding)}\n   标题：${finding.title}\n   说明：${finding.explanation}\n   证据：${finding.evidence}\n   建议修法：${finding.suggested_fix}`).join('\n');
    const indexes = pending.map(({ index }) => index);
    setSending(indexes);
    setSendError('');
    try {
      await store.sendMessage(`请修复代码审查发现的这些问题（${item.scopeLabel}）：\n\n${body}\n\n逐条修，改完说明每一处是怎么处理的。`);
      setSent((current) => [...new Set([...current, ...indexes])]);
    } catch (error) { setSendError(error instanceof Error ? error.message : String(error)); }
    finally { setSending([]); }
  };
  const fixOne = async (index: number, finding: ReviewFinding) => {
    if (sent.includes(index) || sending.length) return;
    setSending([index]);
    setSendError('');
    try { await store.sendMessage(fixMessage(finding)); setSent((current) => [...new Set([...current, index])]); }
    catch (error) { setSendError(error instanceof Error ? error.message : String(error)); }
    finally { setSending([]); }
  };
  const visibleFindingIndexes = item.findings.map((_, index) => index).filter((index) => !dismissed.includes(index));
  const activePosition = activeFinding === null ? -1 : visibleFindingIndexes.indexOf(activeFinding);
  const navigateFinding = (direction: -1 | 1) => {
    const nextPosition = activePosition < 0 ? 0 : activePosition + direction;
    const targetIndex = visibleFindingIndexes[nextPosition];
    if (targetIndex === undefined) return;
    setActiveFinding(targetIndex);
    requestAnimationFrame(() => {
      const row = findingRefs.current[targetIndex];
      row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      row?.querySelector('button')?.focus();
    });
  };
  const copy = () => {
    void navigator.clipboard.writeText(item.findings.map((finding, index) => formatFinding(finding, index)).join('\n\n'))
      .then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000); })
      .catch(() => setCopied(false));
  };
  return <div className="my-4 overflow-hidden rounded-xl card-surface" onKeyDown={(event) => {
    if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing || (event.nativeEvent as KeyboardEvent).keyCode === 229) return;
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return;
    if (event.key === 'ArrowUp' && activePosition > 0) { event.preventDefault(); navigateFinding(-1); }
    else if (event.key === 'ArrowDown' && activePosition < visibleFindingIndexes.length - 1) { event.preventDefault(); navigateFinding(1); }
  }}>
    <div className="flex flex-wrap items-center gap-2 px-4 py-3">
      <SearchCheck size={16} className="shrink-0 text-brand" />
      <b className="text-[14px] font-semibold text-heading">代码审查 · {item.scopeLabel}</b>
      <span className="ml-auto flex items-center gap-1.5 text-[11.5px]">
        {(Object.keys(counts) as Array<ReviewFinding['severity']>).map((severity) =>
          <span key={severity} className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 tabular-nums', FINDING_SEVERITY[severity].chip, counts[severity] === 0 && 'opacity-40')}>
            <span className={cn('size-[7px] rounded-full', FINDING_SEVERITY[severity].dot)} />{FINDING_SEVERITY[severity].label} {counts[severity]}
          </span>)}
      </span>
      <span className="flex shrink-0 items-center gap-1 border-l border-line pl-2">
        <span className="mr-1 text-[11px] text-fg-3">逐条查看 {activePosition < 0 ? '—' : `${activePosition + 1}/${visibleFindingIndexes.length}`}</span>
        <button type="button" aria-label="上一个审查发现" title="上一个发现（Alt+↑）" disabled={!visibleFindingIndexes.length || activePosition <= 0}
          onClick={() => navigateFinding(-1)} className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:opacity-40"><ChevronUp size={14} /></button>
        <button type="button" aria-label="下一个审查发现" title="下一个发现（Alt+↓）" disabled={!visibleFindingIndexes.length || activePosition >= visibleFindingIndexes.length - 1}
          onClick={() => navigateFinding(1)} className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:opacity-40"><ChevronDown size={14} /></button>
      </span>
    </div>
    <ol className="m-0 grid list-none border-t border-line p-0">
      {item.findings.map((finding, index) => dismissed.includes(index) ? null : <FindingRow key={`${finding.file}:${finding.line}:${index}`} finding={finding} store={store} workspace={item.workspace}
        rowRef={(node) => { findingRefs.current[index] = node; }} active={activeFinding === index} onSelect={() => setActiveFinding(index)}
        sent={sent.includes(index)} sending={sending.includes(index)} onFix={() => fixOne(index, finding)} onDismiss={() => setDismissed((current) => [...current, index])} />)}
    </ol>
    {dismissed.length > 0 && <div className="flex items-center gap-2 border-t border-line px-4 py-2 text-[12px] text-fg-3">
      <span className="flex-1">已忽略 {dismissed.length} 条</span>
      <button type="button" className="text-fg-2 hover:text-fg" onClick={() => setDismissed([])}>恢复查看</button>
    </div>}
    <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 text-[12.5px]">
      <button className={cn('inline-flex items-center gap-1.5 hover:text-fg', sent.length && sent.length === item.findings.length - dismissed.length ? 'text-ok' : 'text-fg-2')} onClick={() => void applyFixes()} disabled={sending.length > 0 || sent.length + dismissed.length === item.findings.length}>
        {sending.length > 0 ? <Check size={13} /> : sent.length + dismissed.length === item.findings.length ? <Check size={13} className="text-ok" /> : <ListChecks size={13} />}{sending.length > 0 ? '正在提交…' : sent.length + dismissed.length === item.findings.length ? '已提交/忽略' : `Apply fixes（${item.findings.length - dismissed.length - sent.length}）`}
      </button>
      <button className="inline-flex items-center gap-1.5 text-fg-2 hover:text-fg" onClick={copy}>
        {copied ? <ClipboardCheck size={13} className="text-ok" /> : <ClipboardCopy size={13} />}{copied ? '已复制' : '复制'}
      </button>
    </div>
    {sendError && <p role="alert" className="m-0 border-t border-line px-4 py-2 text-[12px] text-danger">未能提交修复要求：{sendError}</p>}
  </div>;
}

/** 一条发现：默认一行（严重级 + 位置 + 标题），点开看说明、证据和建议修法。 */
export function FindingRow({ finding, store, workspace, defaultOpen = false, sent = false, sending = false, active = false, rowRef, onSelect, onFix, onDismiss }: { finding: ReviewFinding; store: Store; workspace: string; defaultOpen?: boolean; sent?: boolean; sending?: boolean; active?: boolean; rowRef?: (node: HTMLLIElement | null) => void; onSelect?: () => void; onFix?: () => void; onDismiss?: () => void }) {
  const [open, setOpen] = useState(defaultOpen);
  useEffect(() => { if (active) setOpen(true); }, [active]);
  const [note, setNote] = useState('');
  // 通过 Atlas 自己的文件面板打开;浏览器/dev 同样可用。
  const canOpen = Boolean(workspace);
  const openFile = () => {
    store.requestFileOpen(finding.file, finding.line);
    setNote(finding.line ? `已在文件面板打开，定位到第 ${finding.line} 行` : '已在文件面板打开');
  };
  const fix = () => { if (!sent && !sending) onFix?.(); };
  const hasDetail = Boolean(finding.explanation || finding.evidence || finding.suggested_fix);
  return <li ref={rowRef} className={cn('border-b border-line last:border-b-0', active && 'bg-brand-soft/30')}>
    <button type="button" onClick={() => { onSelect?.(); setOpen((value) => !value); }} aria-expanded={open}
      className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left text-[13px] hover:bg-hover">
      <span className={cn('mt-px shrink-0 rounded-full px-2 py-0.5 text-[11px]', FINDING_SEVERITY[finding.severity].chip)}>{FINDING_SEVERITY[finding.severity].label}</span>
      <span className="min-w-0 flex-1"><code className="font-mono text-[12px] text-fg-2">{findingWhere(finding)}</code> <span className="text-fg">{finding.title}</span></span>
      {hasDetail && <ChevronRight size={14} className={cn('mt-0.5 shrink-0 text-fg-3 transition-transform', open && 'rotate-90')} />}
    </button>
    {open && <div className="anim-fade grid gap-2 px-4 pb-3 text-[12.5px]">
      {finding.explanation && <p className="m-0 leading-[1.7] text-fg-2">{finding.explanation}</p>}
      {finding.evidence && <pre className="m-0 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-code p-2.5 font-mono text-[11.5px] leading-[1.6] text-fg-2 shadow-[inset_0_0_0_1px_var(--line)]">{finding.evidence}</pre>}
      {finding.suggested_fix && <p className="m-0 text-fg-2"><span className="text-fg-3">建议修法：</span>{finding.suggested_fix}</p>}
      <div className="flex flex-wrap items-center gap-4">
        {canOpen && <button className="inline-flex items-center gap-1.5 text-fg-2 hover:text-fg" onClick={openFile}><FileSearch size={13} />打开文件</button>}
        <button className={cn('inline-flex items-center gap-1.5 hover:text-fg', sent ? 'text-ok' : 'text-fg-2')} onClick={fix} disabled={sent || sending}>
          {sent ? <Check size={13} className="text-ok" /> : <Hammer size={13} />}{sending ? '正在提交…' : sent ? '已提交对话' : 'Fix'}
        </button>
        {!sent && <button className="inline-flex items-center gap-1.5 text-fg-2 hover:text-fg disabled:opacity-50" disabled={sending} onClick={onDismiss}>Dismiss</button>}
        {note && <span role="status" className="text-fg-3">{note}</span>}
      </div>
    </div>}
  </li>;
}
