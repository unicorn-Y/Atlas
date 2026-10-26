import { useEffect, useState } from 'react';
import { api } from '../../services/api';

type PortalEntry = { id: string; kind: 'agent' | 'capability'; name: string; description: string; call_entry: string };
type PortalConfig = { enabled: boolean; private_network: boolean; visible_entries: string[]; catalog: PortalEntry[]; bind_host: string; port: number };

export default function CapabilityPortalPanel({ apiBaseUrl, onToast }: { apiBaseUrl: string; onToast: (message: string) => void }) {
  const [config, setConfig] = useState<PortalConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => { void api<PortalConfig>(apiBaseUrl, '/api/portal/config').then(setConfig).catch((reason) => setError(reason instanceof Error ? reason.message : String(reason))); }, [apiBaseUrl]);
  const save = async () => {
    if (!config) return;
    setBusy(true); setError('');
    try { setConfig(await api<PortalConfig>(apiBaseUrl, '/api/portal/config', { method: 'PUT', json: config })); onToast('能力门户设置已保存在本机'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { setBusy(false); }
  };
  const toggleEntry = (id: string, checked: boolean) => setConfig((current) => current && ({ ...current, visible_entries: checked ? [...new Set([...current.visible_entries, id])] : current.visible_entries.filter((item) => item !== id) }));
  const portalUrl = `${apiBaseUrl.replace(/\/$/, '')}/portal`;
  return <article className="grid gap-3 rounded-xl border border-line p-4" aria-label="对外能力门户">
    <div><h3 className="m-0 text-[13.5px] font-medium text-heading">对外能力门户</h3><p className="mb-0 mt-1 text-[12px] leading-relaxed text-fg-3">只读页面列出你选择公开的 Agent、能力、调用入口和服务健康状态。默认关闭；启用后仅本机可访问。私有网络访问需要单独开启。</p></div>
    {!config ? <p className="m-0 text-[11px] text-fg-3">正在读取门户设置…</p> : <>
      <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={config.enabled} onChange={(event) => setConfig({ ...config, enabled: event.target.checked })} />启用只读门户</label>
      <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={config.private_network} disabled={!config.enabled} onChange={(event) => setConfig({ ...config, private_network: event.target.checked })} />允许私有网络设备访问（同一局域网/VPN）</label>
      <div className="grid gap-1 rounded-lg bg-sunken p-3">{config.catalog.map((entry) => <label key={entry.id} className="flex items-start gap-2 py-1 text-[11.5px]"><input type="checkbox" checked={config.visible_entries.includes(entry.id)} disabled={!config.enabled} onChange={(event) => toggleEntry(entry.id, event.target.checked)} /><span><strong>{entry.kind === 'agent' ? 'Agent' : '能力'} · {entry.name}</strong><small className="block text-fg-3">{entry.description} 调用入口：{entry.call_entry}</small></span></label>)}</div>
      <p className="m-0 text-[11px] text-fg-3">当前 Atlas 服务绑定地址：{config.bind_host}:{config.port}。门户只返回上方勾选的条目，不公开会话、模型凭据或配置内容。</p>
      <div className="flex flex-wrap gap-2"><button type="button" disabled={busy} onClick={() => void save()} className="rounded-lg bg-brand px-3 py-1.5 text-[11px] text-white disabled:opacity-50">{busy ? '保存中…' : '保存门户设置'}</button><a href={portalUrl} target="_blank" rel="noreferrer" className="rounded-lg border border-line px-3 py-1.5 text-[11px] hover:bg-hover">打开只读门户</a></div>
    </>}
    {error && <p role="alert" className="m-0 text-[11px] text-danger">门户设置错误：{error}</p>}
  </article>;
}
