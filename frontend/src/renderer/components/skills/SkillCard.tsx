import { Download, Puzzle, Star } from 'lucide-react';
import { SOURCE_KIND_LABEL, type MarketSearchHit } from '../../services/skillsMarketApi';
import { cn } from '../../ui/cn';

const kindLabel = (source: string) => SOURCE_KIND_LABEL[source as keyof typeof SOURCE_KIND_LABEL] ?? source;
const metric = (value: number | null) => (value === null ? '' : value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value));

/** 市场里的技能卡片：点卡片看详情，安装动作放在详情里。 */
export default function SkillCard({ hit, selected, onSelect }: {
  hit: MarketSearchHit;
  selected?: boolean;
  onSelect?: (hit: MarketSearchHit) => void;
}) {
  const stat = hit.stars !== null
    ? { icon: Star, value: metric(hit.stars), label: '星标' }
    : hit.downloads !== null
      ? { icon: Download, value: metric(hit.downloads), label: '下载量' }
      : null;
  const kind = kindLabel(hit.source);
  return <button type="button" aria-pressed={selected} onClick={() => onSelect?.(hit)}
    className={cn('card-surface group flex flex-col gap-1.5 rounded-xl p-3.5 text-left transition-shadow hover:shadow-md',
      selected && 'ring-2 ring-[var(--brand)]')}>
    <span className="flex items-center gap-2">
      <Puzzle size={16} className="shrink-0 text-brand" />
      <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-fg">{hit.name}</span>
      {hit.installed && <span className="shrink-0 rounded-full bg-ok-soft px-2 py-0.5 text-[11px] text-fg">已安装</span>}
    </span>
    <span className="line-clamp-2 min-h-[2.6em] text-[12.5px] leading-[1.45] text-fg-2">{hit.description || '作者没有写介绍。'}</span>
    <span className="flex items-center gap-2 text-[11.5px] text-fg-3">
      <span className="rounded-md bg-sunken px-1.5 py-0.5">{kind}</span>
      {stat && <span className="inline-flex items-center gap-1" aria-label={`${kind} ${stat.label}`}><stat.icon size={12} />{stat.value || `无${stat.label}`}</span>}
    </span>
  </button>;
}
