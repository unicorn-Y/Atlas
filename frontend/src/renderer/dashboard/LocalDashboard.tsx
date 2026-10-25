import { useCallback, useEffect, useState } from 'react';

type Tab = 'overview' | 'sessions' | 'channels' | 'devices';
type RecordRow = Record<string, unknown>;
const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'overview', label: '运行状态' }, { id: 'sessions', label: '会话' },
  { id: 'channels', label: '渠道' }, { id: 'devices', label: '设备' },
];

const token = location.hash.slice(1) || sessionStorage.getItem('atlas.dashboard.token') || '';
if (token) sessionStorage.setItem('atlas.dashboard.token', token);
history.replaceState(null, '', location.pathname);

export default function LocalDashboard() {
  const [tab, setTab] = useState<Tab>('overview');
  const [data, setData] = useState<unknown>(null);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState('');
  const refresh = useCallback(async () => {
    if (!token) { setError('缺少控制台访问令牌，请运行 atlas dashboard start 并使用命令输出的网址。'); return; }
    const endpoint: Record<Tab, string> = {
      overview: '/api/dashboard/status', sessions: '/api/dashboard/sessions',
      channels: '/api/dashboard/channels', devices: '/api/dashboard/devices',
    };
    try {
      const response = await fetch(endpoint[tab], { headers: { 'X-Atlas-Dashboard-Token': token } });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(String(body.detail || `HTTP ${response.status}`));
      setData(body); setUpdated(new Date().toLocaleTimeString()); setError('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [tab]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 15_000); return () => window.clearInterval(timer); }, [refresh]);

  const rows = Array.isArray(data) ? data as RecordRow[] : [];
  const overview = data && !Array.isArray(data) ? data as RecordRow : {};
  return <main className="atlas-dashboard">
    <style>{`*{box-sizing:border-box}body{margin:0;background:#10141c;color:#e5e7eb;font:15px system-ui,Segoe UI,sans-serif}.atlas-dashboard{max-width:1050px;margin:0 auto;padding:24px 18px}header,.tabs{display:flex;align-items:center;gap:10px}header{justify-content:space-between}h1{font-size:23px;margin:0}button{border:1px solid #344052;background:#202938;color:inherit;border-radius:9px;padding:9px 13px;cursor:pointer}.tabs{margin:22px 0 12px}.tabs button[aria-selected=true]{background:#315fe8;border-color:#315fe8}.muted{color:#a4afbd}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.card,article{background:#181f2b;border:1px solid #2a3545;border-radius:12px;padding:14px}.card strong{font-size:22px;display:block;margin-top:5px}.list{display:grid;gap:9px}article{overflow-wrap:anywhere}article b{display:block;margin-bottom:5px}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0 0;color:#c4ceda;font:12px ui-monospace,Consolas,monospace}.error{color:#ff9999;margin:12px 0}@media(max-width:550px){.atlas-dashboard{padding:17px 12px}.tabs{overflow:auto}.tabs button{white-space:nowrap}}`}</style>
    <header><h1>Atlas · 本地控制台</h1><button onClick={() => void refresh()}>刷新</button></header>
    <p className="muted">{updated ? `已连接本机 Atlas · ${updated}` : '正在连接本机 Atlas…'}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <nav className="tabs" aria-label="控制台页面">{TABS.map((item) => <button key={item.id} aria-selected={tab === item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</nav>
    {tab === 'overview' ? <section className="grid">
      {[['服务状态', overview.status], ['运行中任务', overview.active_runs], ['等待中任务', overview.waiting_runs], ['已注册渠道', overview.channels], ['配对设备', overview.devices]].map(([label, value]) => <div className="card" key={String(label)}><span className="muted">{String(label)}</span><strong>{String(value ?? '—')}</strong></div>)}
      <pre className="card">{JSON.stringify(overview.components ?? {}, null, 2)}</pre>
    </section> : <section className="list">{rows.length ? rows.map((row, index) => <article key={String(row.id || row.device_id || row.name || index)}><b>{String(row.title || row.display_name || row.name || row.device_id || row.id || 'Atlas')}</b><pre>{JSON.stringify(row, null, 2)}</pre></article>) : <article>暂无记录</article>}</section>}
  </main>;
}
