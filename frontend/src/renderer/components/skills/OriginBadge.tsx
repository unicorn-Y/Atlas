import { originLabel } from '../../services/skillsMarketApi';

const TONE: Record<string, string> = {
  marketplace: 'bg-brand-soft text-fg',
  plugin: 'bg-sunken text-fg-2',
  project: 'bg-ok-soft text-fg',
  user: 'bg-sunken text-fg-2',
  local_recorded: 'bg-brand-soft text-fg',
  local_evolved: 'bg-ok-soft text-fg',
};

/** 技能来源徽标：市场 / 插件 / 项目 / 用户 / 本机录制 / 自学候选。 */
export default function OriginBadge({ originKind }: { originKind?: string | null }) {
  const key = originKind ?? '';
  return <span className={`inline-flex shrink-0 items-center rounded-full px-2 py-0.5 text-[11px] leading-4 ${TONE[key] ?? 'bg-sunken text-fg-3'}`}>{originLabel(originKind)}</span>;
}
