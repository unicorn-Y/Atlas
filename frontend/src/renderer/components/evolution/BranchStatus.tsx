import { FileText, GitBranch, GitMerge } from 'lucide-react';
import type { EvolutionBranch } from '../../services/evolutionApi';

const STATUS_BADGE: Record<string, string> = {
  proposal: 'bg-brand-soft text-brand',
  merged: 'bg-ok-soft text-ok',
};

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_BADGE[status] ?? 'bg-sunken text-fg-2';
  const label = status === 'proposal' ? '待人工合并' : status === 'merged' ? '已合并' : status;
  return <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${cls}`}>{label}</span>;
}

/** 隔离分支状态：批准草稿后生成，合并命令写在 MERGE-PROPOSAL 里等人工执行。 */
export default function BranchStatus({ branches, note }: { branches: EvolutionBranch[]; note: string }) {
  return <div>
    {note && <p className="m-0 mb-2 flex items-center gap-1.5 text-[12px] text-fg-3">
      <GitMerge size={13} className="shrink-0" />{note}
    </p>}
    <ul className="m-0 list-none space-y-1.5 p-0">
      {branches.map((branch) => <li key={branch.name} className="rounded-lg px-2 py-1.5 hover:bg-hover">
        <div className="flex items-center gap-2">
          <GitBranch size={13} className="shrink-0 text-fg-3" />
          <span className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-fg">{branch.name}</span>
          <StatusBadge status={branch.status} />
        </div>
        <p className="m-0 mt-0.5 truncate pl-1 text-[11.5px] text-fg-3">
          {branch.worktree ? `worktree：${branch.worktree}` : ''}
          {branch.base ? ` · 基线 ${branch.base}` : ''}
          {branch.created_at ? ` · ${branch.created_at.replace('T', ' ')}` : ''}
        </p>
        {branch.proposal_path && <p className="m-0 mt-0.5 flex items-center gap-1 truncate pl-1 text-[11.5px] text-fg-3">
          <FileText size={11} className="shrink-0" /><span className="font-mono">{branch.proposal_path}</span>
        </p>}
      </li>)}
      {!branches.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">
        还没有隔离分支。批准一条任务书草稿后，这里会出现分支和合并提案的位置。
      </li>}
    </ul>
  </div>;
}
