import { useEffect, useState, type FormEvent } from 'react';
import { Check, CircleAlert, KeyRound, LoaderCircle, Trash2 } from 'lucide-react';
import {
  addVaultEntry, deleteVaultEntry, getBrowserSettings, listVaultEntries, normalizeEntries, saveBrowserSettings,
  type BrowserControlMode, type BrowserSettings, type VaultEntry, type VaultNewEntry,
} from '../../services/x2Api';
import { cn } from '../../ui/cn';
import { Button } from '../../ui/Button';

/** 四种浏览器接管方式；copied-profile / cdp / extension 需要本机配合，standalone 开箱即用。 */
export const BROWSER_MODES: Array<{ value: BrowserControlMode; label: string; hint: string }> = [
  { value: 'standalone', label: '独立浏览器', hint: 'Atlas 开一个干净的内置浏览器，不碰你平时的登录状态。' },
  { value: 'copied-profile', label: '复制本机配置', hint: '复制日常浏览器的 Cookie 与登录状态，已登录的网站直接可用。' },
  { value: 'cdp', label: '连接已打开的浏览器（CDP）', hint: '通过调试端口接管你手动打开的 Chrome / Edge。' },
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
  useEffect(() => {
    let stale = false;
    // 设置读取失败不阻塞：保留默认值，只在保险箱列表上给出中文错误。
    getBrowserSettings(apiBaseUrl)
      .then((body) => { if (!stale) setSettings({ mode: body.mode ?? 'standalone', cdp_url: body.cdp_url ?? '', proxy: body.proxy ?? '' }); })
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
        <input type="radio" name="browser-mode" className="mt-1" checked={mode === option.value} onChange={() => patch({ mode: option.value })} />
        <span className="min-w-0"><span className="text-fg">{option.label}</span><small className="block text-[12px] text-fg-3">{option.hint}</small></span>
      </label>)}
    </fieldset>
    {mode === 'cdp' && <label className="mt-2 block text-[13px] text-fg-2">CDP 调试地址
      <input value={settings.cdp_url ?? ''} onChange={(event) => patch({ cdp_url: event.target.value })} placeholder="例如 http://127.0.0.1:9222" aria-label="CDP 调试地址"
        className="mt-1 block h-8 w-full rounded-[9px] bg-sunken px-3 font-mono text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
      <small className="mt-1 block text-[12px] text-fg-3">先用 --remote-debugging-port=9222 启动 Chrome / Edge，再把地址填到这里。</small>
    </label>}
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
