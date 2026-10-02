import { useState } from 'react';
import { LoaderCircle, PauseCircle } from 'lucide-react';
import { pauseComputer } from '../../services/x2Api';
import { cn } from '../../ui/cn';

/**
 * 前台操作进行中的细条提示，贴在应用窗口顶部（模拟置顶条；真正的跨窗口置顶由 Electron 主进程负责）。
 * 移动鼠标时后端会自行暂停；这里也提供手动暂停（POST /api/computer/pause）。
 */
export default function ComputerEdgeBar({ apiBaseUrl, runId, className }: {
  apiBaseUrl: string;
  runId: string;
  className?: string;
}) {
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pause = () => {
    if (busy || paused) return;
    setBusy(true);
    setError('');
    pauseComputer(apiBaseUrl, runId)
      .then(() => setPaused(true))
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  return <div role="status" aria-label={paused ? '前台操作已暂停' : '前台操作进行中'}
    className={cn('flex h-7 items-center justify-center gap-2 bg-brand-soft px-3 text-[12px] text-fg shadow-[inset_0_-1px_0_0_var(--line)]', className)}>
    <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', paused ? 'bg-fg-3' : 'animate-pulse bg-brand')} />
    <span className="truncate">{paused ? '已暂停 — Atlas 收到 computer.foreground_resumed 后继续' : '前台操作中 — 移动鼠标即暂停'}</span>
    {!paused && <button type="button" disabled={busy} onClick={pause}
      className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-45">
      {busy ? <LoaderCircle size={12} className="spin" /> : <PauseCircle size={12} />}暂停操作
    </button>}
    {error && <span role="alert" className="shrink-0 truncate text-[11.5px] text-danger">暂停失败：{error}</span>}
  </div>;
}
