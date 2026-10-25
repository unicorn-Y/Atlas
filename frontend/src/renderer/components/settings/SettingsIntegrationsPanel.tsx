import { ExternalLink, GitPullRequest, MessageCircle, Timer, XCircle } from 'lucide-react';
import RemoteAccessPanel from './RemoteAccessPanel';
import { useEffect, useState } from 'react';
import { api } from '../../services/api';

function Entry({ icon: Icon, title, description, action, onClick, disabled = false }: {
  icon: typeof GitPullRequest;
  title: string;
  description: string;
  action: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return <article className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line p-4">
    <div className="flex min-w-[240px] flex-1 items-start gap-3">
      <Icon size={17} className="mt-0.5 shrink-0 text-fg-3" />
      <div className="grid gap-1">
        <h3 className="m-0 text-[13.5px] font-medium text-heading">{title}</h3>
        <p className="m-0 text-[12px] leading-relaxed text-fg-3">{description}</p>
      </div>
    </div>
    <button type="button" disabled={disabled} onClick={onClick}
      className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line px-2.5 text-[12px] text-fg-2 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50">
      {disabled ? <XCircle size={14} /> : <ExternalLink size={14} />}{action}
    </button>
  </article>;
}

export default function SettingsIntegrationsPanel({ onOpenCode, onOpenChannels, onOpenAutomation, apiBaseUrl, onToast, onImportCloudDocument }: {
  apiBaseUrl: string;
  onToast: (text: string) => void;
  onOpenCode: () => void;
  onOpenChannels: () => void;
  onOpenAutomation: () => void;
  onImportCloudDocument: (name: string, content: string) => Promise<void> | void;
}) {
  const [clientId, setClientId] = useState('');
  const [google, setGoogle] = useState<{ configured: boolean; client_id: string; connected: boolean; account: string; authorizing: boolean; auth_error: string }>({ configured: false, client_id: '', connected: false, account: '', authorizing: false, auth_error: '' });
  const [source, setSource] = useState<'drive' | 'gmail'>('drive');
  const [query, setQuery] = useState('');
  const [items, setItems] = useState<Array<{ id: string; name: string; mimeType?: string; modifiedTime?: string; webViewLink?: string; snippet?: string; from?: string; date?: string }>>([]);
  const [busy, setBusy] = useState(false);
  const refreshGoogle = () => void api<typeof google>(apiBaseUrl, '/api/cloud-documents/google/status').then((status) => { setGoogle(status); if (status.client_id) setClientId(status.client_id); }).catch(() => undefined);
  useEffect(() => { refreshGoogle(); }, [apiBaseUrl]);
  useEffect(() => {
    if (!google.connected) { setItems([]); return; }
    let alive = true;
    void api<{ items: typeof items }>(apiBaseUrl, `/api/cloud-documents/google/items?source=${source}&q=${encodeURIComponent(query)}`)
      .then((result) => { if (alive) setItems(result.items); })
      .catch((error) => { if (alive) { setItems([]); onToast(`读取 Google ${source === 'drive' ? 'Drive' : 'Gmail'} 失败：${error instanceof Error ? error.message : String(error)}`); } });
    return () => { alive = false; };
  }, [apiBaseUrl, google.connected, source, query]);
  const saveClient = async () => {
    await api(apiBaseUrl, '/api/cloud-documents/google/client', { method: 'PUT', json: { client_id: clientId } });
    refreshGoogle(); onToast('Google OAuth Client ID 已保存在本机设置中');
  };
  const connectGoogle = async () => {
    setBusy(true);
    try {
      if (clientId) await saveClient();
      const result = await api<{ authorization_url: string }>(apiBaseUrl, '/api/cloud-documents/google/authorize', { method: 'POST' });
      const opened = await window.atlasDesktop?.openExternal?.(result.authorization_url);
      if (!opened) throw new Error('无法打开系统浏览器');
      onToast('已在浏览器打开 Google 登录；完成授权后此处会自动连接');
      let attempts = 0;
      const timer = window.setInterval(() => {
        attempts += 1;
        void api<typeof google>(apiBaseUrl, '/api/cloud-documents/google/status').then((status) => {
          setGoogle(status);
          if ((!status.authorizing && (status.connected || status.auth_error)) || attempts >= 150) window.clearInterval(timer);
          if (!status.authorizing && status.auth_error) onToast(status.auth_error);
          else if (status.connected && !status.authorizing) onToast(`Google 已连接${status.account ? `：${status.account}` : ''}`);
        });
      }, 2000);
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const disconnectGoogle = async () => {
    await api(apiBaseUrl, '/api/cloud-documents/google', { method: 'DELETE' });
    setGoogle((value) => ({ ...value, connected: false, account: '' })); setItems([]); onToast('已删除本机 Google OAuth token');
  };
  const importItem = async (item: (typeof items)[number]) => {
    try {
      const document = await api<{ name: string; content: string; source_url: string }>(apiBaseUrl, `/api/cloud-documents/google/import/${source}/${encodeURIComponent(item.id)}`);
      await onImportCloudDocument(`${document.name}\n来源：${document.source_url}`, document.content);
    } catch (error) { onToast(`导入云端内容失败：${error instanceof Error ? error.message : String(error)}`); }
  };
  return <section className="grid max-w-[820px] gap-3 text-fg-2" aria-label="任务与外部集成入口">
    <p className="m-0 mb-1 text-[12.5px] leading-relaxed text-fg-3">
      这里汇总 Atlas 当前可用的入口。GitHub PR 使用本机工作区和已安装的 gh CLI；Slack 作为本机 Gateway 渠道运行；自动化由本机调度器执行。
    </p>
    <RemoteAccessPanel apiBaseUrl={apiBaseUrl} onToast={onToast} />
    <article className="grid gap-3 rounded-xl border border-line p-4">
      <div><h3 className="m-0 text-[13.5px] font-medium text-heading">Google Drive 与 Gmail（只读）</h3><p className="mb-0 mt-1 text-[12px] text-fg-3">登录后搜索文件或邮件，并由你逐条选择导入当前对话。OAuth refresh token 加密范围仅为本机数据目录；应用申请 Drive readonly 与 Gmail readonly 权限。</p></div>
      {!google.connected ? <><p className="m-0 text-[11px] leading-relaxed text-fg-3">首次使用：在 Google Cloud Console 启用 Drive API 与 Gmail API，创建 OAuth 客户端 ID（桌面应用），将 Client ID 粘贴到此处，并确保测试用户包含你的 Google 账号。Atlas 使用 PKCE loopback 登录，不需要输入或保存 client secret。</p><div className="flex flex-wrap gap-2"><input aria-label="Google OAuth Client ID" value={clientId} onChange={(event) => setClientId(event.target.value)} placeholder="Google 桌面应用 OAuth Client ID" className="min-w-[280px] flex-1 rounded-lg border border-line bg-sunken px-3 py-2 text-[12px] text-fg" /><button type="button" disabled={busy || google.authorizing || !clientId.trim()} onClick={() => void connectGoogle()} className="rounded-lg bg-brand px-3 py-2 text-[12px] font-medium text-white disabled:opacity-50">{busy ? '正在打开登录…' : google.authorizing ? '等待浏览器授权…' : '保存并登录 Google'}</button></div></>
        : <><div className="flex flex-wrap items-center gap-2"><span className="flex-1 text-[12px] text-fg-2">已连接{google.account ? `：${google.account}` : ''}</span><button type="button" onClick={() => void disconnectGoogle()} className="rounded-lg border border-line px-3 py-1.5 text-[11px] hover:bg-hover">断开并删除 token</button></div>
          <div className="flex gap-2"><select aria-label="Google 内容来源" value={source} onChange={(event) => setSource(event.target.value as 'drive' | 'gmail')} className="rounded-lg border border-line bg-sunken px-2 text-[12px] text-fg"><option value="drive">Drive</option><option value="gmail">Gmail</option></select><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={source === 'drive' ? '搜索 Drive 文件名' : '搜索 Gmail 邮件'} className="min-w-0 flex-1 rounded-lg border border-line bg-sunken px-3 py-2 text-[12px] text-fg" /></div>
          <div className="max-h-56 space-y-1 overflow-auto">{items.map((item) => <div key={item.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-hover"><div className="min-w-0 flex-1"><div className="truncate text-[12px] text-fg">{item.name}</div><div className="truncate text-[10px] text-fg-3">{item.from || item.modifiedTime || item.snippet || item.mimeType}</div></div><button type="button" onClick={() => void importItem(item)} className="shrink-0 rounded-md bg-brand-soft px-2.5 py-1.5 text-[11px] text-fg hover:bg-brand/20">导入本轮</button></div>)}{items.length === 0 && <p className="py-3 text-center text-[11px] text-fg-3">没有匹配内容</p>}</div></>}
    </article>
    <Entry icon={GitPullRequest} title="GitHub Pull Request" description="查看工作区变更、创建 PR 并在 Atlas Code 页面跟进。需要本机 git/gh 登录状态。" action="打开 Code" onClick={onOpenCode} />
    <Entry icon={MessageCircle} title="Slack Gateway" description="配置 Slack Socket Mode 机器人凭据，连接本机 Atlas Gateway。可用性取决于可选依赖和凭据。" action="配置渠道" onClick={onOpenChannels} />
    <Entry icon={Timer} title="本机计划任务" description="创建定时、间隔、Webhook 或事件触发自动化；任务在这台机器的 Atlas 实例运行。" action="打开自动化" onClick={onOpenAutomation} />
    <Entry icon={XCircle} title="云端托管任务" description="当前版本没有 Atlas 云执行服务；请使用本机 Automations。Linear issue 集成可在本页下方配置。" action="当前不可用" disabled />
  </section>;
}
