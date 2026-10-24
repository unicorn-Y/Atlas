import { useEffect, useState } from 'react';
import { LoaderCircle, MonitorCheck, RefreshCw } from 'lucide-react';
import { getComputerStatus, type ComputerDiagnostic, type ComputerDriver } from '../../services/x2Api';
import { cn } from '../../ui/cn';

/** 逐项诊断：就绪绿点 / 未就绪灰点，附一句说明。 */
export function ComputerDiagnostics({ items }: { items: ComputerDiagnostic[] }) {
  if (!items.length) return null;
  return <ul className="m-0 grid list-none gap-1.5 p-0">
    {items.map((item, index) => <li key={`${item.name ?? index}`} className="flex items-start gap-2.5 rounded-xl card-surface px-3 py-2 text-[13px]">
      <span aria-label={item.ok ? '正常' : '异常'} className={cn('mt-[7px] size-2 shrink-0 rounded-full', item.ok ? 'bg-ok' : item.ok === false ? 'bg-danger' : 'bg-fg-3')} />
      <span className="min-w-0 flex-1"><span className="text-fg">{item.name ?? '检查项'}</span>
        {item.detail && <small className="block text-[12px] text-fg-3">{item.detail}</small>}</span>
    </li>)}
  </ul>;
}

export function ComputerDriverLabel({ driver }: { driver?: ComputerDriver }) {
  if (!driver) return null;
  const label = typeof driver === 'string' ? driver : `${driver.version ?? '未知版本'} (${driver.platform})`;
  return <span className="text-[12px] text-fg-3">驱动：{label}</span>;
}

/** 设置 → 电脑操控：这台电脑上的操控能力是否就绪、用的哪个驱动、有什么诊断项（GET /api/computer/status）。 */
export default function ComputerStatusSection({ apiBaseUrl, className }: { apiBaseUrl: string; className?: string }) {
  const [ready, setReady] = useState<boolean | null>(null);
  const [driver, setDriver] = useState<ComputerDriver>();
  const [detail, setDetail] = useState('');
  const [diagnostics, setDiagnostics] = useState<ComputerDiagnostic[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [systemAccess, setSystemAccess] = useState<{ platform: string; screen: string; accessibility: string; supported: boolean } | null>(null);
  const [retryMessage, setRetryMessage] = useState('');
  useEffect(() => {
    let stale = false;
    setLoading(true);
    void window.atlasDesktop?.getSystemAccessStatus?.().then((value) => { if (!stale) setSystemAccess(value); }).catch(() => undefined);
    getComputerStatus(apiBaseUrl)
      .then((status) => {
        if (stale) return;
        setReady(status.ready);
        setDriver(status.driver);
        setDetail(status.detail ?? '');
        setDiagnostics(status.diagnostics ?? []);
        setError('');
      })
      .catch((exc) => { if (!stale) { setReady(null); setError(exc instanceof Error ? exc.message : String(exc)); } })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [apiBaseUrl, reloadKey]);
  const requestAccess = async () => {
    const value = await window.atlasDesktop?.requestSystemAccess?.();
    if (value) setSystemAccess(value);
  };
  return <section aria-label="电脑操控" className={className}>
    <div className="flex items-center gap-2">
      <h3 className="m-0 text-[15px] font-semibold text-heading">电脑操控</h3>
      <span className="flex-1" />
      <button aria-label="重新探测电脑操控" disabled={loading} onClick={() => setReloadKey((value) => value + 1)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-40">
        {loading ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}重新探测
      </button>
      {window.atlasDesktop?.retrySessionScreenshot && <button type="button" onClick={() => { setRetryMessage(''); void window.atlasDesktop?.retrySessionScreenshot?.().then((result) => setRetryMessage(result.started ? '已请求重试；成功后截图会添加到当前会话输入框。' : result.reason ?? '暂时无法重试。')).catch((error) => setRetryMessage(error instanceof Error ? error.message : String(error))); }} className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg"><RefreshCw size={13} />重新捕获截图</button>}
    </div>
    {retryMessage && <p className="my-1 text-[12px] text-fg-3" role="status">{retryMessage}</p>}
    <p className="m-0 mt-1 mb-3 text-[13px] text-fg-3">让 Atlas 能看屏幕、动鼠标和键盘的能力。前台窗口里的操作会先问你，鼠标一动就会暂停。</p>
    {systemAccess?.supported && <div className="mb-3 rounded-xl bg-sunken px-3 py-2.5 text-[12.5px]" aria-label="系统权限状态">
      <strong className="block text-fg">系统权限（macOS）</strong>
      <span className="block text-fg-2">屏幕录制：{systemAccess.screen === 'granted' ? '已允许' : systemAccess.screen === 'denied' || systemAccess.screen === 'restricted' ? '系统拒绝' : systemAccess.screen === 'not-determined' ? '尚未决定' : systemAccess.screen}</span>
      <span className="block text-fg-2">辅助功能：{systemAccess.accessibility === 'granted' ? '已允许' : '尚未允许'}</span>
      {systemAccess.screen !== 'granted' || systemAccess.accessibility !== 'granted' ? <><p className="my-1 text-fg-3">首次截图需要屏幕录制；电脑操控需要辅助功能。打开系统设置 → 隐私与安全性 → 屏幕录制 / 辅助功能，勾选 Atlas 后重试。</p>
        <div className="flex gap-3"><button type="button" className="text-brand" onClick={() => void requestAccess().catch(() => undefined)}>请求/重新检查授权</button><button type="button" className="text-brand" onClick={() => void window.atlasDesktop?.openSystemPrivacySettings?.('screen')}>屏幕录制设置</button><button type="button" className="text-brand" onClick={() => void window.atlasDesktop?.openSystemPrivacySettings?.('accessibility')}>辅助功能设置</button></div></> : <p className="my-1 text-ok">所需系统权限已就绪。</p>}
    </div>}
    {error ? <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">探测失败：{error}</p>
      : ready === null ? <p className="m-0 text-[13px] text-fg-3">正在探测…</p>
      : <div aria-live="polite">
        <p className="m-0 mb-2 flex items-center gap-2 text-[13px]">
          <MonitorCheck size={15} className={cn('shrink-0', ready ? 'text-ok' : 'text-fg-3')} />
          <span className={ready ? 'text-ok' : 'text-fg-2'}>{ready ? '电脑操控已就绪' : '电脑操控未就绪'}</span>
          <ComputerDriverLabel driver={driver} />
        </p>
        {!ready && detail && <p className="m-0 mb-2 text-[12.5px] text-fg-3">{detail}</p>}
        <ComputerDiagnostics items={diagnostics} />
      </div>}
  </section>;
}
