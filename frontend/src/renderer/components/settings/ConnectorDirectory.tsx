import { useEffect, useState } from 'react';
import { PlugZap, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';

type Connector = { id: string; name: string; version: string; description: string; authorization: string; installed: boolean; configured: boolean; connected: boolean; account?: string | null; capabilities: string[] };

export default function ConnectorDirectory({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [items, setItems] = useState<Connector[]>([]);
  const [error, setError] = useState('');
  const refresh = () => void api<{ connectors: Connector[] }>(apiBaseUrl, '/api/connectors')
    .then((result) => { setItems(result.connectors); setError(''); })
    .catch((reason) => setError(reason instanceof Error ? reason.message : String(reason)));
  useEffect(() => { refresh(); }, [apiBaseUrl]);
  return <section aria-label="托管应用连接器目录" className="grid gap-3">
    <div className="flex items-center gap-2"><PlugZap size={16} className="text-brand" /><h3 className="m-0 text-[15px] font-semibold text-heading">托管应用连接器</h3>
      <button type="button" aria-label="刷新连接器状态" onClick={refresh} className="ml-auto rounded-md p-1.5 text-fg-3 hover:bg-hover"><RefreshCw size={14} /></button></div>
    <p className="m-0 text-[12px] text-fg-3">统一目录会显示安装、授权与连接状态。凭据仅保存在本机；连接器工具通过 Atlas 运行权限流程执行。</p>
    {error && <p role="alert" className="m-0 text-[12px] text-danger">读取连接器目录失败：{error}</p>}
    {items.map((item) => <article key={item.id} data-connector-id={item.id} className="rounded-xl border border-line p-3">
      <div className="flex items-center gap-2"><b className="text-[13px] text-heading">{item.name}</b><span className="text-[11px] text-fg-3">v{item.version}</span>
        <span className={`ml-auto text-[11px] ${item.connected ? 'text-ok' : 'text-fg-3'}`}>{item.connected ? `已连接${item.account ? ` · ${item.account}` : ''}` : item.configured ? '已配置，未连接' : '未授权'}</span></div>
      <p className="mb-1 mt-1 text-[12px] text-fg-3">{item.description}</p>
      <div className="flex flex-wrap gap-1">{item.capabilities.map((capability) => <code key={capability} className="rounded bg-sunken px-1.5 py-0.5 text-[10px] text-fg-2">{capability}</code>)}</div>
      <small className="mt-1 block text-[10.5px] text-fg-3">{item.installed ? '已安装' : '未安装'} · 授权方式：{item.authorization}</small>
    </article>)}
    {!items.length && !error && <p className="m-0 text-[12px] text-fg-3">正在读取连接器…</p>}
  </section>;
}
