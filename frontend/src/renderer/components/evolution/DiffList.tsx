import { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { DIFF_CLASS_LABEL, type DiffClass, type EvolutionDiff } from '../../services/evolutionApi';

const PAGE_SIZE = 8;

const CLASS_BADGE: Record<DiffClass, string> = {
  NEW: 'bg-brand-soft text-brand',
  BETTER_THAN_ATLAS: 'bg-selected text-fg',
  ALREADY_HAVE: 'bg-sunken text-fg-3',
  REGRESSION_REMOVED: 'bg-danger-soft text-danger',
  IRRELEVANT: 'bg-sunken text-fg-3',
};

export function DiffClassBadge({ cls }: { cls: DiffClass }) {
  return <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${CLASS_BADGE[cls] ?? CLASS_BADGE.IRRELEVANT}`}>
    {DIFF_CLASS_LABEL[cls] ?? cls}
  </span>;
}

/** 上游能力差异列表：NEW / 上游更强 / 已具备 / 上游移除 / 无关 徽标 + 证据，超出一页折叠。 */
export default function DiffList({ diffs, counts }: { diffs: EvolutionDiff[]; counts: Record<string, number> }) {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const shown = diffs.slice(0, limit);
  const rest = diffs.length - shown.length;

  const summary = (['NEW', 'BETTER_THAN_ATLAS', 'ALREADY_HAVE', 'REGRESSION_REMOVED'] as DiffClass[])
    .filter((cls) => (counts[cls] ?? 0) > 0)
    .map((cls) => `${DIFF_CLASS_LABEL[cls]} ${counts[cls]}`)
    .join(' · ');

  return <div>
    {summary && <p className="m-0 mb-2 text-[12px] text-fg-3">本轮分类：{summary}</p>}
    <ul className="m-0 list-none space-y-1.5 p-0">
      {shown.map((diff, index) => <li key={`${diff.entry_id}-${index}`} className="rounded-lg px-2 py-1.5 hover:bg-hover">
        <div className="flex items-center gap-2">
          <DiffClassBadge cls={diff.cls} />
          <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg">{diff.title}</span>
          <span className="shrink-0 text-[11.5px] text-fg-3">{diff.source}</span>
        </div>
        {diff.evidence && <p className="m-0 mt-0.5 pl-1 text-[12px] leading-[1.5] text-fg-3">{diff.evidence}</p>}
        {diff.matched_files.length > 0 && <p className="m-0 mt-0.5 truncate pl-1 font-mono text-[11.5px] text-fg-3">
          {diff.matched_files.slice(0, 3).join(' · ')}
        </p>}
      </li>)}
      {!diffs.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">
        还没有分类结果。先在上面添加上游来源，再点「立即检查」。
      </li>}
    </ul>
    {rest > 0 && <button type="button" className="btn ghost mt-2 w-full justify-center text-[12.5px]"
      onClick={() => setLimit((value) => value + PAGE_SIZE)}>
      <ChevronDown size={14} />显示更多（还有 {rest} 条）
    </button>}
  </div>;
}
