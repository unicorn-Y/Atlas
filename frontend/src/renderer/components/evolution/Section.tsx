import { ChevronRight, LoaderCircle, X, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

/** 自动追新各板块共用的可折叠卡片外壳：标题 + 计数 + 提示，内置加载与中文错误条。 */
export default function Section({ icon: Icon, title, count, hint, open, onToggle, loading, error, onDismissError, onRetry, children, controls }: {
  icon: LucideIcon;
  title: string;
  count?: number;
  hint?: string;
  open: boolean;
  onToggle: () => void;
  loading?: boolean;
  error?: string;
  onDismissError?: () => void;
  onRetry?: () => void;
  /** 头部右侧的操作区（如「立即检查」「生成草稿」按钮）。 */
  controls?: ReactNode;
  children: ReactNode;
}) {
  return <section className="card-surface rounded-xl" aria-label={title} aria-busy={loading}>
    <div className="flex items-center gap-1.5 px-3.5 py-2.5">
      <button type="button" aria-expanded={open} onClick={onToggle}
        className="flex min-w-0 flex-1 items-center gap-1.5 rounded-lg text-left text-[13px] text-fg-2 hover:text-fg">
        <ChevronRight size={14} className={open ? 'rotate-90 transition-transform' : 'transition-transform'} />
        <Icon size={14} className="shrink-0" />
        <span className="min-w-0 truncate font-medium text-fg">{title}</span>
        {typeof count === 'number' && <span className="shrink-0 rounded-md bg-sunken px-1.5 py-0.5 text-[11.5px] text-fg-2">{count}</span>}
        {hint && <span className="ml-auto hidden shrink-0 text-[11.5px] text-fg-3 sm:inline">{hint}</span>}
      </button>
      {controls}
    </div>
    {open && <div className="border-t border-[var(--line)] p-3.5 pt-3">
      {loading && <p role="status" className="m-0 flex items-center gap-2 text-[12.5px] text-fg-3"><LoaderCircle size={14} className="spin" />正在读取…</p>}
      {error && <div role="alert" className="error-note">
        <span className="min-w-0 flex-1">{error}</span>
        {onRetry && <button type="button" className="btn ghost" onClick={onRetry}>重试</button>}
        {onDismissError && <button type="button" className="iconbtn" aria-label="关闭错误提示" onClick={onDismissError}><X size={15} /></button>}
      </div>}
      {!loading && children}
    </div>}
  </section>;
}
