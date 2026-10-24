import { useEffect, useState } from 'react';
import { ArrowUpCircle, LoaderCircle, X } from 'lucide-react';
import type { ReleaseUpdateStatus, SourceUpdateStatus } from '../../shared/ipc';

const RECHECK_MS = 5 * 60 * 1000;
const CHANNEL_KEY = 'atlas.preference.update-channel';
const SOURCE_KEY = 'atlas.preference.release-source';
// Atlas 自己的发布仓库（私有仓库时主进程会带上 gh 登录令牌）。
export const DEFAULT_RELEASE_SOURCE = 'https://api.github.com/repos/unicorn-Y/Atlas/releases/latest';
type View = { channel: 'release' | 'source'; release?: ReleaseUpdateStatus; source?: SourceUpdateStatus };
export default function UpdateBanner() {
  const [view, setView] = useState<View | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const api = window.atlasDesktop;
  useEffect(() => {
    let alive = true;
    const check = async () => {
      // 用户没选过通道时沿用原来的源码更新（老用户一直用的“立即更新”），发布版通道需显式切换。
      const storedChannel = localStorage.getItem(CHANNEL_KEY);
      const channel = storedChannel === 'release' ? 'release' : 'source';
      if (channel === 'source') {
        const status = await api?.checkForUpdate?.().catch(() => null);
        if (alive) setView({ channel, source: status ?? undefined });
      } else {
        const source = localStorage.getItem(SOURCE_KEY) || DEFAULT_RELEASE_SOURCE;
        const status = await api?.checkReleaseUpdate?.(source).catch(() => null);
        if (alive) setView({ channel, release: status ?? undefined });
      }
      if (alive) setDismissed(false);
    };
    const first = window.setTimeout(() => void check(), 8000);
    const timer = window.setInterval(() => void check(), RECHECK_MS);
    const onFocus = () => void check(); const onChange = () => void check();
    window.addEventListener('focus', onFocus); window.addEventListener('atlas:update-settings-changed', onChange);
    return () => { alive = false; window.clearTimeout(first); window.clearInterval(timer); window.removeEventListener('focus', onFocus); window.removeEventListener('atlas:update-settings-changed', onChange); };
  }, []);
  const download = async () => {
    const version = view?.release?.latest; const source = localStorage.getItem(SOURCE_KEY) || DEFAULT_RELEASE_SOURCE;
    if (!version || !api?.downloadReleaseUpdate || !api.installReleaseUpdate) return;
    setBusy(true); setProgress(0);
    const off = api.onReleaseDownloadProgress?.(setProgress);
    try { await api.downloadReleaseUpdate(source, version); await api.installReleaseUpdate(); }
    catch (error) { setView((old) => old?.release ? { ...old, release: { ...old.release, error: error instanceof Error ? error.message : String(error) } } : old); setBusy(false); }
    finally { off?.(); }
  };
  if (!view || dismissed) return null;
  const sourceUpdate = view.channel === 'source' && view.source?.available;
  const releaseUpdate = view.channel === 'release' && view.release?.available;
  if (!sourceUpdate && !releaseUpdate) return null;
  const commits = view.source?.commits ?? [];
  return <div role="status" className="shrink-0 border-b border-line px-5 py-2 text-[12.5px] text-fg">
    <div className="flex items-start gap-2.5"><ArrowUpCircle className="mt-0.5 size-4 shrink-0 text-brand" /><div className="min-w-0 flex-1">
      <div className="font-medium">{view.channel === 'release' ? `Atlas ${view.release?.latest} 可更新` : `Atlas 有 ${view.source?.behind} 个源码更新`}</div>
      <div className="mt-0.5 text-fg-3">{view.channel === 'release' ? `${view.release?.assetName ?? 'Windows 安装包'} · 下载后先校验 SHA256，再安装并重启。` : view.source?.blocked ?? '源码通道将拉取、重建并重启。'}</div>
      {view.release?.error && <p role="alert" className="mt-1 text-danger">{view.release.error}</p>}
      {expanded && (view.release?.notes || commits.length > 0) && <pre className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap text-[11px] text-fg-2">{view.release?.notes || commits.map((item) => `${item.hash} ${item.subject}`).join('\n')}</pre>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {view.channel === 'release'
          ? <button type="button" disabled={busy} onClick={() => void download()} className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 font-medium text-white disabled:opacity-50">{busy && <LoaderCircle className="size-3.5 animate-spin" />}{busy ? `下载中 ${progress}%` : '下载并重启安装'}</button>
          : <button type="button" disabled={busy || Boolean(view.source?.blocked)} onClick={() => { setBusy(true); void api?.applyUpdate?.().finally(() => setBusy(false)); }} className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 font-medium text-white disabled:opacity-50">{busy && <LoaderCircle className="size-3.5 animate-spin" />}立即更新源码</button>}
        <button type="button" onClick={() => setExpanded((value) => !value)} className="rounded-lg px-2 py-1.5 text-fg-3 hover:bg-hover">{expanded ? '收起' : '查看说明'}</button>
        {view.channel === 'release' && <><button type="button" onClick={() => { if (view.release?.latest) void api?.skipReleaseVersion?.(view.release.latest); setDismissed(true); }} className="rounded-lg px-2 py-1.5 text-fg-3 hover:bg-hover">跳过这个版本</button><button type="button" onClick={() => { void api?.remindReleaseLater?.(); setDismissed(true); }} className="rounded-lg px-2 py-1.5 text-fg-3 hover:bg-hover">稍后提醒</button></>}
      </div>
    </div><button aria-label="关闭更新提示" onClick={() => setDismissed(true)} className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover"><X className="size-3.5" /></button></div>
  </div>;
}
