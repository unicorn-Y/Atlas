import { useEffect, useState } from 'react';
import { api } from '../../services/api';
import type { Artifact } from '../../../types/artifact';

type Site = { id: string; title: string; version: number; published_version?: number | null; share_url?: string; local_url?: string; pages?: string[]; source_path: string };
type Hosting = { adapter: string; target_root: string; public_base_url: string; terms_title: string; terms_text: string; terms_url: string; terms_version: string };

function siteUrl(base: string, path: string) { return `${base.replace(/\/$/, '')}${path}`; }

export default function ArtifactSitesPanel({ apiBaseUrl, workspace, artifact, onPreview, onToast }: {
  apiBaseUrl: string; workspace: string; artifact?: Artifact; onPreview: (url: string) => void; onToast: (message: string) => void;
}) {
  const [sites, setSites] = useState<Site[]>([]);
  const [hosting, setHosting] = useState<Hosting>({ adapter: 'filesystem', target_root: '', public_base_url: '', terms_title: '静态站点托管条款', terms_text: '', terms_url: '', terms_version: '' });
  const [busy, setBusy] = useState(false);
  const [pageSite, setPageSite] = useState('');
  const [pageSlug, setPageSlug] = useState('');
  const [pageTitle, setPageTitle] = useState('');
  const [pageContent, setPageContent] = useState('');
  const [publishSite, setPublishSite] = useState<Site | null>(null);
  const [termsRead, setTermsRead] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const refresh = async () => {
    const value = await api<{ sites: Site[]; hosting: Hosting }>(apiBaseUrl, '/api/artifact-sites');
    setSites(value.sites ?? []); setHosting(value.hosting);
  };
  useEffect(() => { void refresh().catch((error) => onToast(`读取站点失败：${String(error)}`)); }, [apiBaseUrl]);

  const run = async (action: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    try { await action(); }
    catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const createSite = () => run(async () => {
    if (!artifact?.path || !workspace) return;
    const value = await api<{ site: Site; local_url: string }>(apiBaseUrl, '/api/artifact-sites', {
      method: 'POST', json: { workspace, source_path: artifact.path, title: artifact.name },
    });
    await refresh(); onToast(`已建立本地站点 ID ${value.site.id}，版本 ${value.site.version}`);
  });
  const updateVersion = (site: Site) => run(async () => {
    if (!artifact?.path || !workspace) return;
    await api(apiBaseUrl, `/api/artifact-sites/${site.id}/versions`, { method: 'POST', json: { workspace, source_path: artifact.path } });
    await refresh(); onToast(`已更新「${site.title}」；分享路径保持不变`);
  });
  const saveHosting = () => run(async () => {
    const next = await api<Hosting>(apiBaseUrl, '/api/artifact-sites/hosting', { method: 'PUT', json: hosting });
    setHosting(next); setSettingsOpen(false); onToast('静态站点托管目标已保存；未上传任何文件');
  });
  const addPage = (site: Site) => run(async () => {
    const value = await api<{ site: Site; local_url: string }>(apiBaseUrl, `/api/artifact-sites/${site.id}/pages`, {
      method: 'POST', json: { slug: pageSlug, title: pageTitle, content: pageContent },
    });
    setPageSite(''); setPageSlug(''); setPageTitle(''); setPageContent(''); await refresh();
    onToast(`子页面已加入版本 ${value.site.version}`);
  });
  const publish = () => publishSite && run(async () => {
    const value = await api<{ share_url: string }>(apiBaseUrl, `/api/artifact-sites/${publishSite.id}/publish`, {
      method: 'POST', json: { confirmed: termsRead, terms_version: hosting.terms_version },
    });
    await refresh(); setPublishSite(null); setTermsRead(false); onToast(`站点已发布：${value.share_url}`);
  });
  const webArtifact = Boolean(artifact?.path && /\.(html?|svg)$/i.test(artifact.path));

  return <section aria-label="网页产物站点" className="mt-4 grid gap-3 rounded-xl border border-line p-3.5">
    <header className="flex items-center gap-2"><b className="flex-1 text-[13px] text-fg">网页产物站点</b><button type="button" onClick={() => void refresh().catch((error) => onToast(String(error)))} className="text-[11.5px] text-brand">刷新</button></header>
    <p className="m-0 text-[11.5px] leading-5 text-fg-3">先建立本机版本并可随时重开。外部部署默认关闭；配置静态托管目标、查看条款并确认后才会复制发布。</p>
    {webArtifact && <button type="button" disabled={busy || !workspace} onClick={createSite} className="rounded-lg border border-line px-3 py-2 text-left text-[12px] text-fg disabled:opacity-45">建立此产物的本地站点{!workspace && '（先为会话选择工作目录）'}</button>}
    {sites.length > 0 ? <div className="grid gap-2">{sites.map((site) => <article key={site.id} className="rounded-lg bg-sunken p-3">
      <div className="flex items-start gap-2"><div className="min-w-0 flex-1"><b className="block truncate text-[12.5px] text-fg">{site.title}</b><small className="block break-all text-[10.5px] text-fg-3">ID {site.id} · 本地版本 v{site.version.toString().padStart(4, '0')}{site.published_version ? ` · 已发布 v${site.published_version.toString().padStart(4, '0')}` : ' · 仅本地'}</small></div></div>
      {site.published_version && site.published_version !== site.version && <p className="mb-0 mt-1 text-[11px] text-warn">本地有较新版本；原分享 URL 仍指向已发布版本。</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" onClick={() => onPreview(siteUrl(apiBaseUrl, `/api/artifact-sites/${site.id}/`))} className="rounded-md border border-line px-2 py-1 text-[11px] text-fg">本地打开</button>
        {artifact?.path && <button type="button" disabled={busy || !workspace} onClick={() => updateVersion(site)} className="rounded-md border border-line px-2 py-1 text-[11px] text-fg disabled:opacity-45">用当前产物更新</button>}
        <button type="button" onClick={() => { setPageSite(pageSite === site.id ? '' : site.id); setPageSlug(''); setPageTitle(''); setPageContent(''); }} className="rounded-md border border-line px-2 py-1 text-[11px] text-fg">添加子页面</button>
        <button type="button" disabled={busy || !hosting.target_root || !hosting.public_base_url || !hosting.terms_text.trim()} onClick={() => { setPublishSite(site); setTermsRead(false); }} className="rounded-md border border-line px-2 py-1 text-[11px] text-fg disabled:opacity-45">预览条款并发布</button>
        {site.share_url && <button type="button" onClick={() => onPreview(site.share_url!)} className="rounded-md border border-line px-2 py-1 text-[11px] text-brand">打开分享链接</button>}
      </div>
      {pageSite === site.id && <div className="mt-3 grid gap-2 border-t border-line pt-3">
        <input aria-label="子页面路径" value={pageSlug} onChange={(event) => setPageSlug(event.target.value)} placeholder="页面路径，如 overview" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" />
        <input aria-label="子页面标题" value={pageTitle} onChange={(event) => setPageTitle(event.target.value)} placeholder="页面标题" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" />
        <textarea aria-label="子页面内容" value={pageContent} onChange={(event) => setPageContent(event.target.value)} rows={4} placeholder="纯文本内容" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" />
        <button type="button" disabled={busy || !pageSlug.trim() || !pageTitle.trim()} onClick={() => addPage(site)} className="justify-self-start rounded-md bg-brand px-3 py-1.5 text-[11.5px] text-white disabled:opacity-45">保存为新版本</button>
      </div>}
    </article>)}</div> : <p className="m-0 text-[11.5px] text-fg-3">还没有站点。选择 HTML/SVG 产物后可建立本地站点。</p>}
    <details open={settingsOpen} onToggle={(event) => setSettingsOpen(event.currentTarget.open)} className="border-t border-line pt-2">
      <summary className="cursor-pointer text-[11.5px] text-fg-2">静态托管适配器：文件系统目录（默认未配置，不会上传）</summary>
      <div className="mt-2 grid gap-2">
        <label className="grid gap-1 text-[11px] text-fg-3">托管目标目录<input aria-label="静态站点托管目录" value={hosting.target_root} onChange={(event) => setHosting({ ...hosting, target_root: event.target.value })} placeholder="例如服务器的静态文件根目录" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" /></label>
        <label className="grid gap-1 text-[11px] text-fg-3">公开基础 URL<input aria-label="公开基础 URL" value={hosting.public_base_url} onChange={(event) => setHosting({ ...hosting, public_base_url: event.target.value })} placeholder="https://example.com/sites" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" /></label>
        <label className="grid gap-1 text-[11px] text-fg-3">条款标题<input aria-label="托管条款标题" value={hosting.terms_title} onChange={(event) => setHosting({ ...hosting, terms_title: event.target.value })} className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" /></label>
        <label className="grid gap-1 text-[11px] text-fg-3">查看条款<textarea aria-label="托管条款内容" value={hosting.terms_text} onChange={(event) => setHosting({ ...hosting, terms_text: event.target.value })} rows={3} placeholder="粘贴静态托管服务的条款摘要或完整内容" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" /></label>
        <label className="grid gap-1 text-[11px] text-fg-3">条款链接<input aria-label="托管条款链接" value={hosting.terms_url} onChange={(event) => setHosting({ ...hosting, terms_url: event.target.value })} placeholder="https://host.example/terms" className="rounded-md border border-line bg-surface px-2 py-1.5 text-[12px] text-fg" /></label>
        <p className="m-0 text-[10.5px] leading-4 text-fg-3">适配器只把站点文件复制到你选定的本地目录；需由你配置的静态文件服务器提供 URL。Atlas 不保存托管凭据，也不会自动创建该目录以外的远程资源。</p>
        <button type="button" disabled={busy} onClick={saveHosting} className="justify-self-start rounded-md border border-line px-3 py-1.5 text-[11.5px] text-fg">保存托管目标</button>
      </div>
    </details>
    {publishSite && <div role="dialog" aria-modal="true" aria-label="发布条款确认" className="fixed inset-0 z-[180] grid place-items-center bg-black/35 p-4">
      <section className="grid max-h-[80vh] w-full max-w-xl gap-3 overflow-auto rounded-2xl border border-line bg-panel p-5 shadow-2xl">
        <h3 className="m-0 text-[15px] font-semibold text-fg">发布「{publishSite.title}」</h3>
        <p className="m-0 text-[12px] text-fg-2">目标：{hosting.target_root}<br />稳定分享 URL：{hosting.public_base_url.replace(/\/$/, '')}/{publishSite.id}/</p>
        <div className="whitespace-pre-wrap rounded-lg bg-sunken p-3 text-[12px] leading-5 text-fg-2"><b>{hosting.terms_title}</b><br />{hosting.terms_text}</div>
        {hosting.terms_url && <a href={hosting.terms_url} target="_blank" rel="noreferrer" className="text-[12px] text-brand">打开托管服务条款</a>}
        <label className="flex items-start gap-2 text-[12px] text-fg-2"><input type="checkbox" checked={termsRead} onChange={(event) => setTermsRead(event.target.checked)} />我已查看上述条款，并确认将当前站点版本复制到配置的托管目录。</label>
        <div className="flex justify-end gap-2"><button type="button" onClick={() => setPublishSite(null)} className="rounded-lg border border-line px-3 py-1.5 text-[12px] text-fg">取消</button><button type="button" disabled={!termsRead || busy} onClick={publish} className="rounded-lg bg-brand px-3 py-1.5 text-[12px] text-white disabled:opacity-45">确认并发布</button></div>
      </section>
    </div>}
  </section>;
}
