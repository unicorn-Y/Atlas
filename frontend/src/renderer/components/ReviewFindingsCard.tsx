import { useState } from 'react';
import { Check, ChevronRight, ClipboardCheck, ClipboardCopy, FileSearch, Hammer, ListChecks, SearchCheck, ShieldCheck } from 'lucide-react';
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
  const [sentAll, setSentAll] = useState(false);
  if (!item.findings.length) {
    return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface">
      <div className="flex items-center gap-2.5 border-l-[3px] border-ok bg-ok-soft px-4 py-3 text-[13px] text-ok">
        <ShieldCheck size={16} className="shrink-0" />代码审查 · {item.scopeLabel}：没有发现问题
      </div>
    </div>;
  }
  const counts: Record<ReviewFinding['severity'], number> = { blocker: 0, major: 0, minor: 0 };
  for (const finding of item.findings) counts[finding.severity] += 1;
  const fixAll = () => {
    if (sentAll) return;
    const body = item.findings.map((finding, index) => `${index + 1}. 文件：${findingWhere(finding)}\n   标题：${finding.title}\n   说明：${finding.explanation}\n   证据：${finding.evidence}\n   建议修法：${finding.suggested_fix}`).join('\n');
    setSentAll(true);
    void store.sendMessage(`请修复代码审查发现的这些问题（${item.scopeLabel}）：\n\n${body}\n\n逐条修，改完说明每一处是怎么处理的。`);
  };
  const copy = () => {
    void navigator.clipboard.writeText(item.findings.map((finding, index) => formatFinding(finding, index)).join('\n\n'))
      .then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 2000); })
      .catch(() => setCopied(false));
  };
  return <div className="my-4 ml-10 overflow-hidden rounded-2xl card-surface">
    <div className="flex flex-wrap items-center gap-2 px-4 py-3">
      <SearchCheck size={16} className="shrink-0 text-brand" />
      <b className="text-[14px] font-semibold text-heading">代码审查 · {item.scopeLabel}</b>
      <span className="ml-auto flex items-center gap-1.5 text-[11.5px]">
        {(Object.keys(counts) as Array<ReviewFinding['severity']>).map((severity) =>
          <span key={severity} className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 tabular-nums', FINDING_SEVERITY[severity].chip, counts[severity] === 0 && 'opacity-40')}>
            <span className={cn('size-[7px] rounded-full', FINDING_SEVERITY[severity].dot)} />{FINDING_SEVERITY[severity].label} {counts[severity]}
          </span>)}
      </span>
    </div>
    <ol className="m-0 grid list-none border-t border-line p-0">
      {item.findings.map((finding, index) => <FindingRow key={`${finding.file}:${finding.line}:${index}`} finding={finding} store={store} workspace={item.workspace} />)}
    </ol>
    <div className="flex items-center gap-4 border-t border-line px-4 py-2.5 text-[12.5px]">
      <button className={cn('inline-flex items-center gap-1.5 hover:text-fg', sentAll ? 'text-ok' : 'text-fg-2')} onClick={fixAll} disabled={sentAll}>
        {sentAll ? <Check size={13} className="text-ok" /> : <ListChecks size={13} />}{sentAll ? '已发回对话' : '全部发回对话修复'}
      </button>
      <button className="inline-flex items-center gap-1.5 text-fg-2 hover:text-fg" onClick={copy}>
        {copied ? <ClipboardCheck size={13} className="text-ok" /> : <ClipboardCopy size={13} />}{copied ? '已复制' : '复制'}
      </button>
    </div>
  </div>;
}

/** 一条发现：默认一行（严重级 + 位置 + 标题），点开看说明、证据和建议修法。 */
export function FindingRow({ finding, store, workspace, defaultOpen = false }: { finding: ReviewFinding; store: Store; workspace: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const [sent, setSent] = useState(false);
  const [note, setNote] = useState('');
  // 通过 Atlas 自己的文件面板打开;浏览器/dev 同样可用。
  const canOpen = Boolean(workspace);
  const openFile = () => {
    store.requestFileOpen(finding.file, finding.line);
    setNote(finding.line ? `已在文件面板打开，定位到第 ${finding.line} 行` : '已在文件面板打开');
  };
  const fix = () => {
    if (sent) return;
    setSent(true);
    void store.sendMessage(fixMessage(finding));
  };
  const hasDetail = Boolean(finding.explanation || finding.evidence || finding.suggested_fix);
  return <li className="border-b border-line last:border-b-0">
    <button type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}
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
        <button className={cn('inline-flex items-center gap-1.5 hover:text-fg', sent ? 'text-ok' : 'text-fg-2')} onClick={fix} disabled={sent}>
          {sent ? <Check size={13} className="text-ok" /> : <Hammer size={13} />}{sent ? '已发回对话' : '让 Atlas 修这一条'}
        </button>
        {note && <span role="status" className="text-fg-3">{note}</span>}
      </div>
    </div>}
  </li>;
}
