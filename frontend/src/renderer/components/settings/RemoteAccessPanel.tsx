import { useEffect, useState } from 'react';
import QRCode from 'qrcode';
import { api } from '../../services/api';

type Grant = { session_id: string; url: string; expires_at: number; host: string };
type Status = { active_sessions: number; latest_expiry: number | null; host: string };

export default function RemoteAccessPanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (text: string) => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [grant, setGrant] = useState<Grant | null>(null);
  const [qr, setQr] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [host, setHost] = useState('');
  const load = async () => { const value = await api<Status>(apiBaseUrl, '/api/remote/status'); setStatus(value); setHost(value.host); };
  useEffect(() => { void load().catch((exc) => setError(exc instanceof Error ? exc.message : String(exc))); }, [apiBaseUrl]);
  const start = async () => {
    setBusy(true); setError('');
    try {
      const value = await api<Grant>(apiBaseUrl, '/api/remote/access', { method: 'POST', json: { host: host.trim() || undefined, ttl_seconds: 8 * 60 * 60 } });
      setGrant(value); setQr(await QRCode.toDataURL(value.url, { width: 220, margin: 1 })); await load(); onToast('远程会话已开启，二维码有效 8 小时');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const stop = async () => {
    setBusy(true); setError('');
    try { await api(apiBaseUrl, '/api/remote/stop', { method: 'POST', json: grant ? { session_id: grant.session_id } : {} }); setGrant(null); setQr(''); await load(); onToast('远程会话凭据已撤销'); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const copy = async () => { if (grant) { await navigator.clipboard.writeText(grant.url); onToast('远程会话链接已复制'); } };
  return <section className="grid gap-3 rounded-xl border border-line p-4" aria-label="本机远程会话">
    <div><h3 className="m-0 text-[13.5px] font-medium text-heading">本机远程会话</h3><p className="mt-1 mb-0 text-[12px] text-fg-3">在同一局域网的手机浏览器查看并继续 Atlas 会话，处理待审批操作。临时链接有效 8 小时，密钥只在链接片段中传递。</p></div>
    {error && <p role="alert" className="m-0 text-[12px] text-danger">连接失败：{error}。检查 Atlas 服务与网络后重试。</p>}
    <div className="flex flex-wrap gap-2"><label className="grid min-w-[220px] flex-1 gap-1 text-[11px]">手机可访问的本机地址<input value={host} onChange={(event) => setHost(event.target.value)} className="h-8 rounded-lg border border-line bg-surface px-2 text-[12px] text-fg" placeholder="例如 192.168.1.20" /></label><div className="flex items-end gap-2"><button type="button" onClick={() => void load().catch((exc) => setError(String(exc)))} className="h-8 rounded-lg border border-line px-3 text-[12px]">重试连接</button><button type="button" disabled={busy} onClick={() => void start()} className="h-8 rounded-lg bg-brand px-3 text-[12px] text-white">{busy ? '正在连接…' : '开启远程会话'}</button><button type="button" disabled={busy || !status?.active_sessions} onClick={() => void stop()} className="h-8 rounded-lg border border-line px-3 text-[12px]">停止访问</button></div></div>
    {status && <p className="m-0 text-[11px] text-fg-3">{status.active_sessions ? `远程入口在线 · ${status.active_sessions} 个临时凭据` : '远程入口已停止'}{status.latest_expiry ? ` · 最近凭据到期 ${new Date(status.latest_expiry * 1000).toLocaleString()}` : ''}</p>}
    {grant && <div className="flex flex-wrap items-center gap-3 rounded-lg bg-sunken p-3">{qr && <img src={qr} alt="手机扫描以打开 Atlas Remote" width={160} height={160} className="rounded bg-white p-1" />}<div className="grid min-w-0 flex-1 gap-2"><span className="break-all text-[11px] text-fg-2">{grant.url}</span><button type="button" onClick={() => void copy()} className="h-8 w-fit rounded-lg border border-line px-3 text-[11px]">复制链接</button><small className="text-fg-3">凭据到期：{new Date(grant.expires_at * 1000).toLocaleString()}</small></div></div>}
  </section>;
}
