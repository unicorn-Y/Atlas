import { GitBranch, Hammer, LoaderCircle, ScrollText } from 'lucide-react';
import { SuggestionBadge } from './ParitySuggestions';
import type { EvolutionDraft, ParitySuggestion } from '../../services/evolutionApi';

/** 任务书草稿：批准后由后端建隔离分支 + worktree，永不自动合并 main。 */
export default function DraftList({ drafts, busyId, onApprove, onGenerate, generating }: {
  drafts: EvolutionDraft[];
  busyId: string;
  onApprove: (draft: EvolutionDraft) => void;
  onGenerate: () => void;
  generating: boolean;
}) {
  return <div>
    <div className="mb-2 flex items-center gap-2">
      <button type="button" className="btn ghost h-8 text-[12.5px]" disabled={generating || busyId !== ''}
        onClick={onGenerate} aria-label="按当前建议生成任务书草稿">
        {generating ? <LoaderCircle size={14} className="spin" /> : <ScrollText size={14} />}
        {generating ? '正在生成…' : '按建议生成草稿'}
      </button>
      <span className="text-[11.5px] text-fg-3">批准 = 创建隔离分支施工，合并永远需要人工确认。</span>
    </div>
    <ul className="m-0 list-none space-y-1.5 p-0">
      {drafts.map((draft) => {
        const approved = draft.status === 'approved';
        const busy = busyId === draft.id || generating;
        const suggestion = draft.suggestion === 'UPGRADE' || draft.suggestion === 'REPLACE' ? draft.suggestion : null;
        return <li key={draft.id} className="rounded-lg px-2 py-1.5 hover:bg-hover">
          <div className="flex items-center gap-2">
            {suggestion && <SuggestionBadge suggestion={suggestion as ParitySuggestion} />}
            <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{draft.title}</span>
            {approved
              ? <span className="flex shrink-0 items-center gap-1 rounded-full bg-ok-soft px-2 py-0.5 text-[11px] text-fg">
                  <GitBranch size={11} />已批准
                </span>
              : <button type="button" className="btn ghost h-7 shrink-0 px-2 text-[12px]" disabled={busy}
                  onClick={() => onApprove(draft)} aria-label={`批准任务书 ${draft.title}`}>
                  {busyId === draft.id ? <LoaderCircle size={13} className="spin" /> : <Hammer size={13} />}
                  {busyId === draft.id ? '正在批准…' : '批准施工'}
                </button>}
          </div>
          {draft.acceptance && <p className="m-0 mt-0.5 pl-1 text-[12px] leading-[1.5] text-fg-3">{draft.acceptance}</p>}
          <p className="m-0 mt-0.5 truncate pl-1 text-[11.5px] text-fg-3">
            {draft.source_repo}{draft.created ? ` · ${draft.created.replace('T', ' ')}` : ''}
            {draft.path ? ` · ${draft.path}` : ''}
          </p>
          {draft.atlas_integration_point && <p className="m-0 mt-0.5 truncate pl-1 text-[11.5px] text-fg-3">
            集成点：<span className="font-mono">{draft.atlas_integration_point}</span>
          </p>}
          {approved && draft.branch && <p className="m-0 mt-0.5 flex items-center gap-1 pl-1 text-[11.5px] text-ok">
            <GitBranch size={11} className="shrink-0" /><span className="font-mono">{draft.branch}</span>
          </p>}
        </li>;
      })}
      {!drafts.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">
        还没有任务书草稿。检查上游后点「按建议生成草稿」，或批准前先看上面的对标建议。
      </li>}
    </ul>
  </div>;
}
