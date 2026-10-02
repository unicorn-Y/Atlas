import { useEffect, useState } from 'react';
import { MessageCircle, Puzzle, Trash2 } from 'lucide-react';
import type { InstalledSkillRecord } from '../../services/skillsMarketApi';
import { cn } from '../../ui/cn';
import OriginBadge from './OriginBadge';

/** 两段式确认按钮（再点一次才执行），与侧栏删除、记忆页的确认交互一致。 */
export function ConfirmActionButton({ label, confirmLabel, disabled, onConfirm }: {
  label: string;
  confirmLabel: string;
  disabled?: boolean;
  onConfirm: () => void;
}) {
  const [armed, setArmed] = useState(false);
  useEffect(() => { if (!armed) return; const timer = window.setTimeout(() => setArmed(false), 3000); return () => window.clearTimeout(timer); }, [armed]);
  return <button type="button" className={cn('btn ghost h-7 px-2 text-[12px]', armed && 'text-danger')} disabled={disabled}
    onClick={() => { if (armed) { setArmed(false); onConfirm(); } else setArmed(true); }}>
    <Trash2 size={13} />{armed ? confirmLabel : label}
  </button>;
}

/** 已安装技能卡片：来源徽标、版本、启用开关、卸载、「在对话里试用」。 */
export default function InstalledSkillCard({ skill, busy, onToggle, onUninstall, onTryInConversation }: {
  skill: InstalledSkillRecord;
  busy?: boolean;
  onToggle: (enabled: boolean) => void;
  onUninstall: () => void;
  onTryInConversation?: (name: string) => void;
}) {
  // 后端还没补 enabled 字段时按「已启用」对待，避免老数据看起来全部被关掉了。
  const enabled = skill.enabled !== false;
  return <article className={cn('card-surface mb-2 rounded-xl p-3.5 transition-opacity', busy && 'opacity-60')} aria-label={`已安装技能 ${skill.name}`}>
    <div className="flex flex-wrap items-center gap-2">
      <Puzzle size={15} className="shrink-0 text-brand" />
      <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-fg">{skill.name}</span>
      <OriginBadge originKind={skill.origin_kind} />
      {skill.version && <span className="text-[12px] tabular-nums text-fg-3">v{skill.version}</span>}
      <button type="button" role="switch" aria-checked={enabled} disabled={busy}
        title={enabled ? '已在技能列表里，点击停用' : '已停用，点击重新启用'}
        onClick={() => onToggle(!enabled)}
        className={cn('relative h-[20px] w-[34px] shrink-0 rounded-full transition-colors', enabled ? 'bg-brand' : 'bg-[var(--line-strong)]')}>
        <i className={cn('absolute top-[2px] size-4 rounded-full bg-white shadow transition-all', enabled ? 'left-[16px]' : 'left-[2px]')} />
      </button>
    </div>
    {skill.description && <p className="m-0 mt-1 line-clamp-2 text-[12.5px] leading-relaxed text-fg-2">{skill.description}</p>}
    <div className="mt-2 flex flex-wrap items-center gap-1.5">
      <span className="text-[11.5px] text-fg-3">来源 {skill.source || '本地'}</span>
      <span className="flex-1" />
      {onTryInConversation && <button type="button" className="btn h-7 px-2 text-[12px]" disabled={busy}
        onClick={() => onTryInConversation(skill.name)}><MessageCircle size={13} />在对话里试用</button>}
      <ConfirmActionButton label="卸载" confirmLabel="再点一次确认卸载" disabled={busy} onConfirm={onUninstall} />
    </div>
  </article>;
}
