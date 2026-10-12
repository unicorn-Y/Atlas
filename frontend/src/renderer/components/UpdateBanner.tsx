import { useEffect, useState } from 'react';
import { ArrowUpCircle, LoaderCircle, X } from 'lucide-react';
import type { SourceUpdateStatus } from '../../shared/ipc';

const RECHECK_MS = 5 * 60 * 1000;

/**
 * Source-mode update notice: when Atlas runs from a git checkout and the remote has new
 * commits, offer to pull, rebuild and restart (scripts/atlas-update.mjs does the work).
 */
export default function UpdateBanner() {
  const [update, setUpdate] = useState<SourceUpdateStatus | null>(null);
  const [dismissedAt, setDismissedAt] = useState<number | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    const api = window.atlasDesktop;
    if (!api?.checkForUpdate) return;
    let alive = true;
    const check = () => { void api.checkForUpdate!().then((status) => { if (alive) setUpdate(status); }).catch(() => undefined); };
    const first = window.setTimeout(check, 8_000);
    const timer = window.setInterval(check, RECHECK_MS);
    // Coming back to the window re-checks too (at most once a minute), so a fresh push shows up promptly.
    let lastFocusCheck = 0;
    const onFocus = () => { if (Date.now() - lastFocusCheck > 60_000) { lastFocusCheck = Date.now(); check(); } };
    window.addEventListener('focus', onFocus);
    return () => { alive = false; window.clearTimeout(first); window.clearInterval(timer); window.removeEventListener('focus', onFocus); };
  }, []);

  if (!update?.available || (dismissedAt && update.behind <= dismissedAt)) return null;

  const apply = async () => {
    setApplying(true);
    const started = await window.atlasDesktop?.applyUpdate?.().catch(() => false);
    if (!started) setApplying(false);
  };

  return <div role="status" className="shrink-0 border-b border-line px-5 py-2 text-[12.5px] text-fg">
    <div className="flex items-start gap-2.5">
      <ArrowUpCircle className="mt-0.5 size-4 shrink-0 text-brand" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">Atlas 有 {update.behind} 个更新</div>
        {update.blocked
          ? <div className="mt-0.5 text-fg-3">{update.blocked}</div>
          : <div className="mt-0.5 text-fg-3">更新会拉取最新代码、按需重新构建，然后自动重启。</div>}
        {expanded && <ul className="mt-2 max-h-40 space-y-1 overflow-auto text-[12.5px] text-fg-2">
          {update.commits.map((commit) => <li key={commit.hash} className="truncate"><span className="font-mono text-fg-3">{commit.hash}</span> {commit.subject}</li>)}
        </ul>}
        <div className="mt-2.5 flex items-center gap-2">
          <button disabled={applying || Boolean(update.blocked)} onClick={() => void apply()}
            className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-[12.5px] font-medium text-white disabled:opacity-50">
            {applying && <LoaderCircle className="size-3.5 animate-spin" />}{applying ? '正在重启更新…' : '立即更新'}
          </button>
          <button onClick={() => setExpanded((value) => !value)} className="rounded-lg px-2 py-1.5 text-[12.5px] text-fg-3 hover:bg-hover hover:text-fg">
            {expanded ? '收起' : '查看改动'}
          </button>
        </div>
      </div>
      <button aria-label="稍后再说" onClick={() => setDismissedAt(update.behind)} className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg">
        <X className="size-3.5" />
      </button>
    </div>
  </div>;
}
