import { useEffect, useRef, useState } from 'react';
import { ArrowUpCircle, LoaderCircle, X } from 'lucide-react';
import type { AtlasDesktopApi, ReleaseUpdateStatus, SourceUpdateStatus } from '../../shared/ipc';
import { appendUpdateJournal, createUpdateCoordinator } from '../services/update-coordinator';
import { tn } from '../services/i18n';

const CHANNEL_KEY = 'atlas.preference.update-channel';
const SOURCE_KEY = 'atlas.preference.release-source';
// Atlas 自己的发布仓库（私有仓库时主进程会带上 gh 登录令牌）。
export const DEFAULT_RELEASE_SOURCE = 'https://api.github.com/repos/unicorn-Y/Atlas/releases/latest';
type View = { channel: 'release' | 'source'; release?: ReleaseUpdateStatus; source?: SourceUpdateStatus };

export async function checkUpdateChannel(api: Pick<AtlasDesktopApi, 'checkForUpdate' | 'checkReleaseUpdate'> | undefined,
  channel: 'source' | 'release', releaseSource: string): Promise<{ source?: SourceUpdateStatus; release?: ReleaseUpdateStatus | null }> {
  if (channel === 'source') {
    if (!api?.checkForUpdate) throw new Error('源码更新检查不可用');
    const [source, release] = await Promise.all([
      api.checkForUpdate(),
      api.checkReleaseUpdate?.(releaseSource).catch(() => null) ?? Promise.resolve(null),
    ]);
    return { source, release };
  }
  if (!api?.checkReleaseUpdate) throw new Error('发布版更新检查不可用');
  const release = await api.checkReleaseUpdate(releaseSource);
  if (release.error) throw new Error(release.error);
  return { release };
}

export function MandatoryUpdateDialog({ release, busy, progress, onDownload }: {
  release: ReleaseUpdateStatus; busy: boolean; progress: number; onDownload: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} role="alertdialog" aria-modal="true" aria-label="必须更新 Atlas" onCancel={(event) => event.preventDefault()} className="fixed inset-0 m-0 grid h-dvh w-dvw max-h-none max-w-none place-items-center border-0 bg-black/70 p-6 text-fg backdrop-blur-sm">
    <section className="grid w-full max-w-lg gap-4 rounded-2xl border border-line bg-panel p-6 text-fg shadow-2xl">
      <div><h1 className="m-0 text-lg font-semibold">{tn('updates', '必须更新 Atlas')}</h1><p className="mb-0 mt-2 text-sm leading-relaxed text-fg-2">{tn('updates', `当前版本 ${release.current} 已停止支持。最低支持版本为 ${release.minimumVersion}，请安装 ${release.latest} 后继续使用。`)}</p></div>
      {release.error && <p role="alert" className="m-0 text-sm text-danger">{release.error}</p>}
      <button type="button" disabled={busy || !release.available || !release.assetName} onClick={onDownload} className="inline-flex min-h-10 items-center justify-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50">
        {busy && <LoaderCircle className="size-4 animate-spin" />}{busy ? `正在下载 ${progress}%` : tn('updates', '下载并安装受支持版本')}
      </button>
      {!release.assetName && <p className="m-0 text-xs text-fg-3">{tn('updates', '该 Release 暂无 Windows 安装包，应用将保持锁定，直到发布包可用。')}</p>}
    </section>
  </dialog>;
}

export default function UpdateBanner() {
  const [view, setView] = useState<View | null>(null);
  const [forcedRelease, setForcedRelease] = useState<ReleaseUpdateStatus | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const api = window.atlasDesktop;
  useEffect(() => {
    let alive = true;
    let checkedChannel: 'source' | 'release' = 'source';
    const check = async () => {
      // 用户没选过通道时沿用原来的源码更新（老用户一直用的“立即更新”），发布版通道需显式切换。
      const storedChannel = localStorage.getItem(CHANNEL_KEY);
      const channel = storedChannel === 'release' ? 'release' : 'source';
      checkedChannel = channel;
      const releaseSource = localStorage.getItem(SOURCE_KEY) || DEFAULT_RELEASE_SOURCE;
      return checkUpdateChannel(api, channel, releaseSource);
    };
    const coordinator = createUpdateCoordinator({
      check,
      channel: () => localStorage.getItem(CHANNEL_KEY) === 'release' ? 'release' : 'source',
      initialDelayMs: 8000,
      journal: (entry) => appendUpdateJournal(entry, localStorage),
      onResult: (result) => {
        if (!alive) return;
        const release = result.release as ReleaseUpdateStatus | undefined;
        if (release && !release.error) setForcedRelease(release.mandatory ? release : null);
        setView(checkedChannel === 'source' ? { channel: 'source', source: result.source as SourceUpdateStatus, release } : { channel: 'release', release });
        setDismissed(false);
      },
    });
    coordinator.start();
    const onFocus = () => coordinator.checkNow(); const onChange = () => coordinator.checkNow();
    window.addEventListener('focus', onFocus); window.addEventListener('atlas:update-settings-changed', onChange);
    return () => { alive = false; coordinator.stop(); window.removeEventListener('focus', onFocus); window.removeEventListener('atlas:update-settings-changed', onChange); };
  }, [api]);
  const download = async () => {
    const version = forcedRelease?.latest ?? view?.release?.latest; const source = localStorage.getItem(SOURCE_KEY) || DEFAULT_RELEASE_SOURCE;
    if (!version || !api?.downloadReleaseUpdate || !api.installReleaseUpdate) return;
    setBusy(true); setProgress(0);
    const off = api.onReleaseDownloadProgress?.(setProgress);
    try { await api.downloadReleaseUpdate(source, version); await api.installReleaseUpdate(); }
    catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setView((old) => old?.release ? { ...old, release: { ...old.release, error: message } } : old);
      setForcedRelease((old) => old ? { ...old, error: message } : old);
      setBusy(false);
    }
    finally { off?.(); }
  };
  if (forcedRelease) return <MandatoryUpdateDialog release={forcedRelease} busy={busy} progress={progress} onDownload={() => void download()} />;
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
          ? <button type="button" disabled={busy} onClick={() => void download()} className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 font-medium text-white disabled:opacity-50">{busy && <LoaderCircle className="size-3.5 animate-spin" />}{busy ? `下载中 ${progress}%` : tn('updates', '下载并重启安装')}</button>
          : <button type="button" disabled={busy || Boolean(view.source?.blocked)} onClick={() => { setBusy(true); void api?.applyUpdate?.().finally(() => setBusy(false)); }} className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 font-medium text-white disabled:opacity-50">{busy && <LoaderCircle className="size-3.5 animate-spin" />}{tn('updates', '立即更新源码')}</button>}
        <button type="button" onClick={() => setExpanded((value) => !value)} className="rounded-lg px-2 py-1.5 text-fg-3 hover:bg-hover">{tn('updates', expanded ? '收起' : '查看说明')}</button>
        {view.channel === 'release' && <><button type="button" onClick={() => { if (view.release?.latest) void api?.skipReleaseVersion?.(view.release.latest); setDismissed(true); }} className="rounded-lg px-2 py-1.5 text-fg-3 hover:bg-hover">{tn('updates', '跳过这个版本')}</button><button type="button" onClick={() => { void api?.remindReleaseLater?.(); setDismissed(true); }} className="rounded-lg px-2 py-1.5 text-fg-3 hover:bg-hover">{tn('updates', '稍后提醒')}</button></>}
      </div>
    </div><button aria-label="关闭更新提示" onClick={() => setDismissed(true)} className="grid size-6 place-items-center rounded-md text-fg-3 hover:bg-hover"><X className="size-3.5" /></button></div>
  </div>;
}
