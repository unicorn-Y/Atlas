import { useEffect, useState, type FormEvent } from 'react';
import { Check, CircleAlert, KeyRound, LoaderCircle, Trash2 } from 'lucide-react';
import {
  addVaultEntry, deleteVaultEntry, getBrowserSettings, listVaultEntries, normalizeEntries, saveBrowserSettings,
  type BrowserControlMode, type BrowserSettings, type VaultEntry, type VaultNewEntry,
} from '../../services/x2Api';
import { cn } from '../../ui/cn';
import { Button } from '../../ui/Button';
import { api } from '../../services/api';

/** 四种浏览器接管方式；copied-profile / cdp / extension 需要本机配合，standalone 开箱即用。 */
export const BROWSER_MODES: Array<{ value: BrowserControlMode; label: string; hint: string }> = [
  { value: 'auto', label: '自动选择', hint: '按扩展 > 已打开的 Chrome > 复制配置 > 独立浏览器的顺序连接。' },
  { value: 'standalone', label: '独立浏览器', hint: 'Atlas 开一个干净的内置浏览器，不碰你平时的登录状态。' },
  { value: 'copied-profile', label: '复制本机配置', hint: '复制日常浏览器的书签、扩展和设置在后台运行。注意：新版 Chrome/Edge 对 Cookie 做了应用绑定加密，副本里不会有网站登录状态；需要登录状态请用“连接正在使用的 Chrome”或“浏览器扩展”。' },
  { value: 'live_chrome', label: '连接正在使用的 Chrome', hint: '在 chrome://inspect/#remote-debugging 启用发现后接管当前会话，能直接用你已登录的网站。' },
  { value: 'cdp', label: '自定义 CDP 地址', hint: '连接手动配置的 Chromium DevTools 地址。' },
  { value: 'extension', label: '浏览器扩展', hint: '在你自己的浏览器里装 Atlas 扩展，由扩展代为操作。' },
];

/**
 * 凭据保险箱列表：只显示句柄信息（名称、用户名、网址），保存后永不回显密码。
 * 新增在下面的表单里，删除需点两次确认。
 */
export function VaultManager({ entries, busy, onAdd, onDelete, className }: {
  entries: VaultEntry[];
  busy: boolean;
  onAdd: (entry: VaultNewEntry) => Promise<boolean>;
  onDelete: (id: string) => void;
  className?: string;
}) {
  const [label, setLabel] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [url, setUrl] = useState('');
  const [adding, setAdding] = useState(false);
  const [armedId, setArmedId] = useState('');
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (adding || busy || !label.trim() || !password) return;
    setAdding(true);
    void onAdd({ label: label.trim(), username: username.trim() || undefined, password, url: url.trim() || undefined })
      .then((ok) => { if (ok) { setLabel(''); setUsername(''); setPassword(''); setUrl(''); } })
      .finally(() => setAdding(false));
  };
  return <div className={className}>
    <p className="m-0 mb-2 flex items-center gap-1.5 text-[13px] text-fg-2"><KeyRound size={14} className="shrink-0 text-brand" />网站凭据保险箱</p>
    <p className="m-0 mb-2 text-[12.5px] text-fg-3">登录某网站需要账号密码时，Atlas 从这里取。密码保存后不会再显示，列表里只有名称和用户名。</p>
    {entries.length
      ? <ul className="m-0 mb-3 grid list-none gap-1.5 p-0">
        {entries.map((entry) => <li key={entry.id} className="flex items-center gap-2.5 rounded-xl card-surface px-3 py-2 text-[13px]">
          <span className="min-w-0 flex-1">
            <span className="text-fg">{entry.label}</span>
            {entry.username && <span className="ml-2 text-[12px] text-fg-3">{entry.username}</span>}
            {entry.url && <small className="block truncate font-mono text-[11.5px] text-fg-3" title={entry.url}>{entry.url}</small>}
          </span>
          <button type="button" aria-label={`删除凭据 ${entry.label}`} disabled={busy}
            onClick={() => { if (armedId === entry.id) { setArmedId(''); onDelete(entry.id); } else setArmedId(entry.id); }}
            className={cn('inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] hover:bg-hover disabled:opacity-40',
              armedId === entry.id ? 'bg-danger-soft text-danger' : 'text-fg-3 hover:text-fg')}>
            <Trash2 size={13} />{armedId === entry.id ? '再点一次确认' : '删除'}
          </button>
        </li>)}
      </ul>
      : <p className="m-0 mb-3 text-[13px] text-fg-3">还没有存过网站凭据。</p>}
    <form onSubmit={submit} className="grid gap-2">
      <div className="flex flex-wrap gap-2">
        <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="名称，例如：公司 OA" aria-label="凭据名称" required
          className="h-8 min-w-40 flex-1 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
        <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="用户名（可选）" aria-label="用户名" autoComplete="off"
          className="h-8 min-w-40 flex-1 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      </div>
      <div className="flex flex-wrap gap-2">
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="密码" aria-label="密码" autoComplete="new-password" required
          className="h-8 min-w-40 flex-1 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
        <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="网址（可选）" aria-label="网址" autoComplete="off"
          className="h-8 min-w-40 flex-1 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
        <Button type="submit" variant="secondary" disabled={adding || busy || !label.trim() || !password}>
          {adding ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}添加
        </Button>
      </div>
    </form>
  </div>;
}

/** 设置 → 浏览器：接管方式、CDP 地址、代理与凭据保险箱（GET/POST /api/browser/settings、/api/browser/vault/*）。 */
export default function BrowserSettingsSection({ apiBaseUrl, initialSettings, className }: {
  apiBaseUrl: string;
  /** 后端读取生效前的初始值（也便于宿主/测试直接给定模式）。 */
  initialSettings?: BrowserSettings;
  className?: string;
}) {
  const [settings, setSettings] = useState<BrowserSettings>(initialSettings ?? { mode: 'standalone', cdp_url: '', proxy: '' });
  const [entries, setEntries] = useState<VaultEntry[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [extension, setExtension] = useState<BrowserSettings['extension']>();
  const [connectionCheck, setConnectionCheck] = useState('');
  useEffect(() => {
    let stale = false;
    // 设置读取失败不阻塞：保留默认值，只在保险箱列表上给出中文错误。
    getBrowserSettings(apiBaseUrl)
      .then((body) => { if (!stale) { setSettings({ ...body, mode: body.mode ?? 'auto', cdp_url: body.cdp_url ?? '', proxy: body.proxy ?? '' }); setExtension(body.extension); } })
      .catch(() => undefined);
    listVaultEntries(apiBaseUrl)
      .then((body) => { if (!stale) { setEntries(normalizeEntries(body)); setError(''); } })
      .catch((exc) => { if (!stale) { setEntries([]); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [apiBaseUrl, reloadKey]);
  const patch = (next: Partial<BrowserSettings>) => { setSettings((current) => ({ ...current, ...next })); setSaved(false); };
  const save = () => {
    if (busy) return;
    setBusy(true);
    setError('');
    saveBrowserSettings(apiBaseUrl, settings)
      .then(() => setSaved(true))
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  const add = (entry: VaultNewEntry) => addVaultEntry(apiBaseUrl, entry)
    .then((created) => { setEntries((current) => [...current ?? [], created]); return true; })
    .catch((exc) => { setError(exc instanceof Error ? exc.message : String(exc)); return false; });
  const remove = (id: string) => {
    setBusy(true);
    deleteVaultEntry(apiBaseUrl, id)
      .then(() => setEntries((current) => (current ?? []).filter((entry) => entry.id !== id)))
      .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))
      .finally(() => setBusy(false));
  };
  const mode = settings.mode ?? 'standalone';
  const checkConnection = () => {
    setConnectionCheck('正在检测 Chrome…');
    api<{ connected: boolean; error?: string }>(apiBaseUrl, '/api/browser/connection-check', { method: 'POST', json: {} })
      .then((result) => setConnectionCheck(result.connected ? '已发现正在运行的 Chrome。保存选择后浏览器工具会连接该会话。' : (result.error || '未发现调试连接。')))
      .catch((exc) => setConnectionCheck(exc instanceof Error ? exc.message : String(exc)));
  };
  const refreshExtension = () => getBrowserSettings(apiBaseUrl).then((body) => setExtension(body.extension)).catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)));
  return <section aria-label="浏览器" className={className}>
    <div className="flex items-center gap-2">
      <h3 className="m-0 text-[15px] font-semibold text-heading">浏览器</h3>
      <span className="flex-1" />
      <button aria-label="重新加载浏览器设置" onClick={() => setReloadKey((value) => value + 1)} disabled={busy}
        className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-40">
        <LoaderCircle size={13} className={cn(busy && 'spin')} />重新加载
      </button>
    </div>
    <p className="m-0 mt-1 mb-3 text-[13px] text-fg-3">Atlas 替你操作网页时用哪种浏览器，以及要不要走代理。凭据存在本机，密码保存后不再显示。</p>
    {entries === null && !error && <p className="m-0 text-[13px] text-fg-3">正在读取浏览器设置…</p>}
    {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">读取失败：{error}</p>}
    <fieldset className="m-0 grid list-none gap-1.5 border-0 p-0">
      <legend className="sr-only">浏览器接管方式</legend>
      {BROWSER_MODES.map((option) => <label key={option.value} className="flex cursor-pointer items-start gap-2.5 rounded-xl px-2 py-1.5 text-[13px] hover:bg-hover">
        <input type="radio" name="browser-mode" className="mt-1" checked={mode === option.value} onChange={() => patch({ mode: option.value, ...(option.value !== 'standalone' ? { incognito: false } : {}) })} />
        <span className="min-w-0"><span className="text-fg">{option.label}</span><small className="block text-[12px] text-fg-3">{option.hint}</small></span>
      </label>)}
    </fieldset>
    <label className="mt-2 flex cursor-pointer items-start gap-2 rounded-xl card-surface p-3 text-[12.5px] text-fg-2">
      <input type="checkbox" checked={!!settings.incognito} onChange={(event) => patch({ incognito: event.target.checked, ...(event.target.checked ? { mode: 'standalone' } : {}) })} />
      <span>隐私浏览：使用 Atlas 独立浏览器的无痕窗口，不读取或保存任何浏览器登录状态。</span>
    </label>
    {mode === 'cdp' && <label className="mt-2 block text-[13px] text-fg-2">CDP 调试地址
      <input value={settings.cdp_url ?? ''} onChange={(event) => patch({ cdp_url: event.target.value })} placeholder="例如 http://127.0.0.1:9222" aria-label="CDP 调试地址"
        className="mt-1 block h-8 w-full rounded-[9px] bg-sunken px-3 font-mono text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <small className="mt-1 block text-[12px] text-fg-3">先用 --remote-debugging-port=9222 启动 Chrome / Edge，再把地址填到这里。</small>
    </label>}
    {mode === 'live_chrome' && <div className="mt-2 rounded-xl card-surface p-3 text-[12.5px] text-fg-2">
      <p className="m-0 mb-2">在用户自己的 Chrome 打开 <code>chrome://inspect/#remote-debugging</code>，启用远程调试发现，然后点击检测。Atlas 读取 DevToolsActivePort，不会修改 Chrome 配置文件。</p>
      <Button variant="secondary" onClick={checkConnection}>检测连接</Button>{connectionCheck && <p role="status" className="m-0 mt-2">{connectionCheck}</p>}
    </div>}
    {mode === 'copied-profile' && <div className="mt-2 grid gap-2 sm:grid-cols-3">
      <label className="text-[12.5px] text-fg-2">浏览器<select aria-label="复制配置浏览器" value={settings.profile_browser ?? 'chrome'} onChange={(event) => patch({ profile_browser: event.target.value as 'chrome' | 'edge' })} className="mt-1 h-8 w-full rounded-lg bg-sunken px-2 text-fg"><option value="chrome">Chrome</option><option value="edge">Edge</option></select></label>
      <label className="text-[12.5px] text-fg-2">Profile 名称<input aria-label="Profile 名称" value={settings.profile ?? 'Default'} onChange={(event) => patch({ profile: event.target.value })} className="mt-1 h-8 w-full rounded-lg bg-sunken px-2 text-fg" /></label>
      <label className="text-[12.5px] text-fg-2">同步间隔（分钟）<input aria-label="配置同步间隔" type="number" min={1} max={1440} value={settings.profile_sync_interval_minutes ?? 30} onChange={(event) => patch({ profile_sync_interval_minutes: Number(event.target.value) })} className="mt-1 h-8 w-full rounded-lg bg-sunken px-2 text-fg" /></label>
    </div>}
    {mode === 'extension' && <div className="mt-2 rounded-xl card-surface p-3 text-[12.5px] text-fg-2">
      <p className="m-0 mb-2">1. 打开 Chrome 扩展管理页并启用“开发者模式”。<br />2. 选择“加载已解压的扩展程序”，打开下方目录。<br />3. 点击 Atlas 扩展，输入配对码，然后选择标签页并接管。</p>
      <p className="m-0 mb-2">扩展目录：<code className="break-all">{extension?.extension_path ?? 'browser-extension'}</code></p>
      <p className="m-0 mb-2">本机配对码：<code className="text-[15px] font-semibold">{extension?.pairing_code ?? '加载中…'}</code>　{extension?.connected ? <span className="text-ok">已连接</span> : <span className="text-fg-3">未连接</span>}</p>
      <div className="flex flex-wrap gap-2"><Button variant="secondary" onClick={() => void navigator.clipboard.writeText(extension?.extension_path ?? 'browser-extension')}>复制扩展目录</Button><Button variant="secondary" onClick={() => extension?.extension_path && void window.atlasDesktop?.openPath(extension.extension_path)}>打开扩展目录</Button><Button variant="secondary" onClick={refreshExtension}>刷新配对状态</Button></div>
    </div>}
    <label className="mt-2 block text-[13px] text-fg-2">代理（可选）
      <input value={settings.proxy ?? ''} onChange={(event) => patch({ proxy: event.target.value })} placeholder="例如 http://127.0.0.1:7890" aria-label="代理"
        className="mt-1 block h-8 w-full rounded-[9px] bg-sunken px-3 font-mono text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
    </label>
    <div className="mt-3 flex items-center gap-3">
      <Button variant="primary" onClick={save} disabled={busy}>{busy ? <LoaderCircle size={14} className="spin" /> : <Check size={14} />}保存设置</Button>
      {saved && <span role="status" className="text-[12.5px] text-ok">已保存</span>}
      {error && <span role="alert" className="flex items-center gap-1 text-[12.5px] text-danger"><CircleAlert size={13} />{error}</span>}
    </div>
    <div className="mt-4 border-t border-line pt-3">
      <VaultManager entries={entries ?? []} busy={busy} onAdd={add} onDelete={remove} />
    </div>
  </section>;
}
