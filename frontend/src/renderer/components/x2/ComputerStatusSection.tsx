import { useEffect, useState } from 'react';
import { LoaderCircle, MonitorCheck, RefreshCw } from 'lucide-react';
import { getComputerStatus, type ComputerDiagnostic } from '../../services/x2Api';
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

/** 设置 → 电脑操控：这台电脑上的操控能力是否就绪、用的哪个驱动、有什么诊断项（GET /api/computer/status）。 */
export default function ComputerStatusSection({ apiBaseUrl, className }: { apiBaseUrl: string; className?: string }) {
  const [ready, setReady] = useState<boolean | null>(null);
  const [driver, setDriver] = useState('');
  const [detail, setDetail] = useState('');
  const [diagnostics, setDiagnostics] = useState<ComputerDiagnostic[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    let stale = false;
    setLoading(true);
    getComputerStatus(apiBaseUrl)
      .then((status) => {
        if (stale) return;
        setReady(status.ready);
        setDriver(status.driver ?? '');
        setDetail(status.detail ?? '');
        setDiagnostics(status.diagnostics ?? []);
        setError('');
      })
      .catch((exc) => { if (!stale) { setReady(null); setError(exc instanceof Error ? exc.message : String(exc)); } })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [apiBaseUrl, reloadKey]);
  return <section aria-label="电脑操控" className={className}>
    <div className="flex items-center gap-2">
      <h3 className="m-0 text-[15px] font-semibold text-heading">电脑操控</h3>
      <span className="flex-1" />
      <button aria-label="重新探测电脑操控" disabled={loading} onClick={() => setReloadKey((value) => value + 1)}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-40">
        {loading ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={13} />}重新探测
      </button>
    </div>
    <p className="m-0 mt-1 mb-3 text-[13px] text-fg-3">让 Atlas 能看屏幕、动鼠标和键盘的能力。前台窗口里的操作会先问你，鼠标一动就会暂停。</p>
    {error ? <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">探测失败：{error}</p>
      : ready === null ? <p className="m-0 text-[13px] text-fg-3">正在探测…</p>
      : <div aria-live="polite">
        <p className="m-0 mb-2 flex items-center gap-2 text-[13px]">
          <MonitorCheck size={15} className={cn('shrink-0', ready ? 'text-ok' : 'text-fg-3')} />
          <span className={ready ? 'text-ok' : 'text-fg-2'}>{ready ? '电脑操控已就绪' : '电脑操控未就绪'}</span>
          {driver && <span className="text-[12px] text-fg-3">驱动：{driver}</span>}
        </p>
        {!ready && detail && <p className="m-0 mb-2 text-[12.5px] text-fg-3">{detail}</p>}
        <ComputerDiagnostics items={diagnostics} />
      </div>}
  </section>;
}
