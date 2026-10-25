import { useState } from 'react';
import { ChevronDown, LoaderCircle, Puzzle, RotateCcw, ThumbsUp } from 'lucide-react';
import { candidateOriginLabel, type SkillCandidate } from '../../services/evolutionApi';

const STATUS_BADGE: Record<string, string> = {
  candidate: 'bg-brand-soft text-brand',
  approved: 'bg-ok-soft text-ok',
  rejected: 'bg-sunken text-fg-3',
  stale: 'bg-sunken text-fg-3',
  merged: 'bg-ok-soft text-ok',
  rolled_back: 'bg-sunken text-fg-3',
};

function statusLabel(status: string): string {
  const known: Record<string, string> = {
    candidate: '候选', approved: '已批准', rejected: '已拒绝', stale: '已闲置', merged: '已并入', rolled_back: '已回滚',
  };
  return known[status] ?? status;
}

/** 技能候选：自学/上游启发产生的候选技能，可展开预览再批准（交给统一 SkillManager 落盘）。 */
export default function SkillCandidates({ candidates, busyId, onApprove, onRollback }: {
  candidates: SkillCandidate[];
  busyId: string;
  onApprove: (candidate: SkillCandidate) => void;
  onRollback: (candidate: SkillCandidate) => void;
}) {
  const [expandedId, setExpandedId] = useState('');

  return <ul className="m-0 list-none space-y-1.5 p-0">
    {candidates.map((candidate) => {
      const expanded = expandedId === candidate.id;
      const busy = busyId === candidate.id;
      const badgeCls = STATUS_BADGE[candidate.status] ?? 'bg-sunken text-fg-2';
      return <li key={candidate.id} className="rounded-lg px-2 py-1.5 hover:bg-hover">
        <div className="flex items-center gap-2">
          <button type="button" aria-expanded={expanded} aria-label={`预览候选技能 ${candidate.title}`}
            onClick={() => setExpandedId(expanded ? '' : candidate.id)}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg text-left">
            <ChevronDown size={14} className={expanded ? 'shrink-0 rotate-180 transition-transform' : 'shrink-0 transition-transform'} />
            <Puzzle size={13} className="shrink-0 text-brand" />
            <span className="min-w-0 truncate text-[12.5px] font-medium text-fg">{candidate.title}</span>
          </button>
          <span className="shrink-0 rounded-md bg-sunken px-1.5 py-0.5 text-[11px] text-fg-2">{candidateOriginLabel(candidate.origin)}</span>
          <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${badgeCls}`}>{statusLabel(candidate.status)}</span>
          {candidate.status === 'candidate' &&
            <button type="button" className="btn ghost h-7 shrink-0 px-2 text-[12px]" disabled={busy}
              onClick={() => onApprove(candidate)} aria-label={`批准候选技能 ${candidate.title}`}>
              {busy ? <LoaderCircle size={13} className="spin" /> : <ThumbsUp size={13} />}
              {busy ? '正在批准…' : '批准'}
            </button>}
          {candidate.status === 'approved' && candidate.origin === 'successful_run' &&
            <button type="button" className="btn ghost h-7 shrink-0 px-2 text-[12px]" disabled={busy}
              onClick={() => onRollback(candidate)} aria-label={`回滚技能 ${candidate.title}`}>
              {busy ? <LoaderCircle size={13} className="spin" /> : <RotateCcw size={13} />}
              {busy ? '正在回滚…' : '回滚'}
            </button>}
        </div>
        {expanded && <pre className="m-0 mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-sunken p-3 font-mono text-[11.5px] leading-[1.6] text-fg-2">
          {candidate.preview_md || candidate.description || '这条候选还没有可预览的内容。'}
        </pre>}
        {expanded && candidate.source_runs.length > 0 && <p className="m-0 mt-1 px-1 text-[10.5px] text-fg-3">来源运行：{candidate.source_runs.join('、')}</p>}
      </li>;
    })}
    {!candidates.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">
      还没有技能候选。运行沉淀或录制沉淀达到条件时会出现在这里，先预览再批准。
    </li>}
  </ul>;
}
