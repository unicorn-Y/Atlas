import { useState } from 'react';
import { ChevronDown, FileText } from 'lucide-react';
import { SUGGESTION_LABEL, type ParityRow, type ParitySuggestion } from '../../services/evolutionApi';

const SUGGESTION_BADGE: Record<ParitySuggestion, string> = {
  KEEP: 'bg-sunken text-fg-2',
  UPGRADE: 'bg-brand-soft text-brand',
  REPLACE: 'bg-danger-soft text-danger',
};

export function SuggestionBadge({ suggestion }: { suggestion: ParitySuggestion }) {
  return <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${SUGGESTION_BADGE[suggestion]}`}>
    {SUGGESTION_LABEL[suggestion]}
  </span>;
}

/** 对标建议：KEEP / UPGRADE / REPLACE，附 Atlas 现状与上游出处；补丁提案只读预览。 */
export default function ParitySuggestions({ rows, patchProposal }: { rows: ParityRow[]; patchProposal: string }) {
  const [proposalOpen, setProposalOpen] = useState(false);

  return <div>
    <ul className="m-0 list-none space-y-1.5 p-0">
      {rows.map((row, index) => <li key={`${row.capability_id}-${index}`} className="rounded-lg px-2 py-1.5 hover:bg-hover">
        <div className="flex items-center gap-2">
          <SuggestionBadge suggestion={row.suggestion} />
          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-fg">{row.capability}</span>
          <span className="shrink-0 text-[11.5px] text-fg-3">{row.source}</span>
        </div>
        {row.why_stronger && <p className="m-0 mt-0.5 pl-1 text-[12px] leading-[1.5] text-fg-3">{row.why_stronger}</p>}
        <p className="m-0 mt-0.5 truncate pl-1 text-[11.5px] text-fg-3">
          {row.repo_file ? <span className="font-mono">{row.repo_file}</span> : '上游文件待定位'}
          {row.atlas_impl ? ` · Atlas 现状：${row.atlas_impl}` : ' · Atlas 尚无对应实现'}
          {!row.advisory ? ' · 仅记录' : ''}
        </p>
      </li>)}
      {!rows.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">
        暂无对标建议。检查过上游之后，这里会给出每项能力「保持 / 升级 / 替换」的判断。
      </li>}
    </ul>
    {patchProposal && <div className="mt-2">
      <button type="button" aria-expanded={proposalOpen} onClick={() => setProposalOpen((value) => !value)}
        className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg">
        <ChevronDown size={14} className={proposalOpen ? 'rotate-180 transition-transform' : 'transition-transform'} />
        <FileText size={14} />CORE-PARITY 补丁提案（只读预览，不会自动写入文档）
      </button>
      {proposalOpen && <pre className="m-0 mt-1 max-h-72 overflow-auto rounded-lg bg-sunken p-3 font-mono text-[11.5px] leading-[1.6] text-fg-2">{patchProposal}</pre>}
    </div>}
  </div>;
}
