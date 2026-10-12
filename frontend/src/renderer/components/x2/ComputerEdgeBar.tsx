import { useEffect, useState } from 'react';
import { Check, LoaderCircle, PauseCircle, ShieldAlert, Square, X } from 'lucide-react';
import {
  getComputerAccessRequests, pauseComputer, resolveComputerAccess,
  stopComputerRun, type ComputerAccessRequest,
} from '../../services/x2Api';
import { cn } from '../../ui/cn';

/**
 * 前台操作进行中的细条提示，贴在应用窗口顶部（模拟置顶条；真正的跨窗口置顶由 Electron 主进程负责）。
 * Computer Use 活动时显示真实待批权限、批准/拒绝与 run 级停止控制。
 */
export default function ComputerEdgeBar({ apiBaseUrl, runId, canPause = false, className }: {
  apiBaseUrl: string;
  runId: string;
  canPause?: boolean;
  className?: string;
}) {
  const [paused, setPaused] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [request, setRequest] = useState<ComputerAccessRequest | null>(null);
  const [stopped, setStopped] = useState(false);
  const [stopMessage, setStopMessage] = useState('');
  useEffect(() => {
    let mounted = true;
    const refresh = () => getComputerAccessRequests(apiBaseUrl)
      .then(({ requests }) => {
        if (mounted) setRequest(requests.find((item) => item.run_id === runId) ?? null);
      })
      .catch((exc) => {
        if (mounted) setError(exc instanceof Error ? exc.message : String(exc));
      });
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 900);
    return () => { mounted = false; window.clearInterval(timer); };
  }, [apiBaseUrl, runId]);
  const pause = () => {
    if (busy || paused) return;
    setBusy(true);
    setError('');
    pauseComputer(apiBaseUrl, runId)
      .then(() => setPaused(true))
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  const decide = (approve: boolean) => {
    if (!request || busy) return;
    setBusy(true);
    setError('');
    resolveComputerAccess(apiBaseUrl, request.request_id, approve)
      .then(() => setRequest(null))
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  const stop = () => {
    if (busy || stopped) return;
    setBusy(true);
    setError('');
    stopComputerRun(apiBaseUrl, runId)
      .then((result) => {
        setStopped(true);
        setPaused(false);
        setRequest(null);
        setStopMessage(result.inflight_call_cancel_requested
          ? result.driver_stop_supported
            ? '驱动已收到停止指令；此 run 的授权已撤销'
            : '停止已锁存，等待当前系统调用返回；此 run 的授权已撤销'
          : '后续电脑操作已停止；此 run 的授权已撤销');
      })
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  return <div role="status" aria-label={request ? '等待电脑操控授权' : stopped ? '电脑操控停止已锁存' : paused ? '前台操作已暂停' : '前台操作进行中'}
    className={cn('flex h-7 items-center justify-center gap-2 bg-brand-soft px-3 text-[12px] text-fg shadow-[inset_0_-1px_0_0_var(--line)]', className)}>
    <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', paused || stopped ? 'bg-fg-3' : 'animate-pulse bg-brand')} />
    {request ? <>
      <ShieldAlert size={13} aria-hidden="true" className="shrink-0" />
      <span className="truncate">请求电脑操控权限：{request.reason}（{request.scope === 'window' ? `窗口 ${request.window_id}` : '整个桌面'}）</span>
      <button type="button" disabled={busy} onClick={() => decide(true)}
        className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-ok hover:bg-hover disabled:opacity-45">
        {busy ? <LoaderCircle size={12} className="spin" /> : <Check size={12} />}允许
      </button>
      <button type="button" disabled={busy} onClick={() => decide(false)}
        className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-danger hover:bg-hover disabled:opacity-45">
        <X size={12} />拒绝
      </button>
    </> : <span className="truncate">{stopped ? stopMessage : paused ? '已暂停 — Atlas 收到 computer.foreground_resumed 后继续' : '电脑操控进行中 — Windows 使用当前前台桌面'}</span>}
    {canPause && !paused && !stopped && <button type="button" disabled={busy} onClick={pause}
      className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-45">
      {busy ? <LoaderCircle size={12} className="spin" /> : <PauseCircle size={12} />}暂停操作
    </button>}
    {!stopped && <button type="button" disabled={busy} onClick={stop}
      className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-[11.5px] text-danger hover:bg-hover disabled:opacity-45">
      {busy && !request ? <LoaderCircle size={12} className="spin" /> : <Square size={11} />}停止
    </button>}
    {error && <span role="alert" className="shrink-0 truncate text-[11.5px] text-danger">操作失败：{error}</span>}
  </div>;
}
