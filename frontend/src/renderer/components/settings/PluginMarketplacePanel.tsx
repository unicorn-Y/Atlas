import { useEffect, useState, type FormEvent } from 'react';
import { Plus, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';

type Marketplace = { name: string; type?: string; source?: string; path?: string };
type CatalogPlugin = { name: string; description?: string };
type Diagnostic = { name: string; valid: boolean; diagnostics: string[]; plugin_count?: number };

/** Real PluginRuntime marketplace management; remote catalog code is never executed by this panel. */
export default function PluginMarketplacePanel({ apiBaseUrl, onChanged }: { apiBaseUrl: string; onChanged: () => void }) {
  const [items, setItems] = useState<Marketplace[]>([]);
  const [plugins, setPlugins] = useState<Record<string, CatalogPlugin[]>>({});
  const [source, setSource] = useState('');
  const [name, setName] = useState('');
  const [message, setMessage] = useState('');
  const [diagnostics, setDiagnostics] = useState<Record<string, Diagnostic>>({});
  const [busy, setBusy] = useState(false);
  const [resetArmed, setResetArmed] = useState(false);
  const field = 'h-8 min-w-0 rounded-lg bg-sunken px-2.5 text-[12px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

  const load = async () => {
    setBusy(true);
    try {
      const result = await api<{ marketplaces: Marketplace[] }>(apiBaseUrl, '/api/plugin-marketplaces');
      setItems(result.marketplaces ?? []);
      const listed = await Promise.all((result.marketplaces ?? []).map(async (item) => {
        try {
          const response = await api<{ plugins: CatalogPlugin[] }>(apiBaseUrl, `/api/plugin-marketplaces/${encodeURIComponent(item.name)}/plugins`);
          return [item.name, response.plugins ?? []] as const;
        } catch { return [item.name, []] as const; }
      }));
      setPlugins(Object.fromEntries(listed));
      setMessage('');
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, [apiBaseUrl]);

  const add = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      await api(apiBaseUrl, '/api/plugin-marketplaces', { method: 'POST', json: { source: source.trim(), ...(name.trim() ? { name: name.trim() } : {}) } });
      setSource(''); setName(''); await load(); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); setBusy(false); }
  };
  const inspect = async (market: Marketplace) => {
    setBusy(true);
    try {
      const result = await api<Diagnostic>(apiBaseUrl, `/api/plugin-marketplaces/${encodeURIComponent(market.name)}/validate`, { method: 'POST' });
      setDiagnostics((current) => ({ ...current, [market.name]: result }));
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };
  const update = async (market: Marketplace) => {
    setBusy(true); setMessage('');
    try { await api(apiBaseUrl, `/api/plugin-marketplaces/${encodeURIComponent(market.name)}/update`, { method: 'POST' }); await load(); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); setBusy(false); }
  };
  const remove = async (market: Marketplace) => {
    setBusy(true); setMessage('');
    try { await api(apiBaseUrl, `/api/plugin-marketplaces/${encodeURIComponent(market.name)}`, { method: 'DELETE' }); await load(); onChanged(); }
    catch (error) { setMessage(error instanceof Error ? error.message : String(error)); setBusy(false); }
  };
  const install = async (market: Marketplace, plugin: CatalogPlugin) => {
    setBusy(true); setMessage('');
    try {
      await api(apiBaseUrl, `/api/plugin-marketplaces/${encodeURIComponent(market.name)}/install`, { method: 'POST', json: { plugin: plugin.name } });
      setMessage(`${plugin.name} 已安装。`); onChanged();
    } catch (error) { setMessage(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  };

  return <section className="grid gap-3 rounded-xl bg-sunken p-3 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="插件市场来源">
    <header><h3 className="text-[13px] font-semibold text-fg">插件市场</h3><p className="mt-1 text-[11.5px] text-fg-3">添加本地或 Git 市场，检查 marketplace.json、更新目录并安装条目。检查不会获取远程插件内容。</p></header>
    <form className="grid grid-cols-[minmax(0,1fr)_150px_auto] gap-2" onSubmit={(event) => void add(event)}>
      <input required aria-label="Marketplace 来源" value={source} onChange={(event) => setSource(event.target.value)} className={cn(field, 'font-mono')} placeholder="Git URL 或本地目录" />
      <input aria-label="Marketplace 名称（可选）" value={name} onChange={(event) => setName(event.target.value)} className={field} placeholder="名称（可选）" />
      <Button size="sm" type="submit" disabled={busy}><Plus />添加</Button>
    </form>
    {items.map((market) => <article key={market.name} className="grid gap-2 rounded-lg bg-panel p-3 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="min-w-0"><p className="text-[12px] font-medium text-fg">{market.name}</p><p className="truncate font-mono text-[10px] text-fg-3" title={market.source}>{market.type} · {market.source}</p></div><div className="flex gap-1"><Button size="sm" variant="ghost" disabled={busy} onClick={() => void inspect(market)}><RefreshCw />检查</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void update(market)}>更新</Button><Button size="sm" variant="danger" disabled={busy} onClick={() => void remove(market)}><Trash2 />注销</Button></div></div>
      {diagnostics[market.name] && <div role="status" className="grid gap-1 text-[11px] text-fg-2">{diagnostics[market.name].diagnostics.map((line, index) => <p key={index}>{line}</p>)}</div>}
      <div className="grid gap-1">{(plugins[market.name] ?? []).map((plugin) => <div key={plugin.name} className="flex items-center justify-between gap-2 border-t border-line pt-1.5"><span className="min-w-0 truncate text-[11px] text-fg-2">{plugin.name}{plugin.description ? ` · ${plugin.description}` : ''}</span><Button size="sm" disabled={busy} onClick={() => void install(market, plugin)}>安装</Button></div>)}</div>
    </article>)}
    {!items.length && <p className="text-[11px] text-fg-3">尚未添加插件市场来源。</p>}
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2"><p className="text-[11px] text-fg-3">插件自定义配置不可用：当前 PluginRuntime 不读取配置 schema 或为插件提供配置值接口。</p><Button size="sm" variant={resetArmed ? 'danger' : 'ghost'} disabled={busy} onClick={() => {
      if (!resetArmed) { setResetArmed(true); return; }
      setBusy(true);
      void api(apiBaseUrl, '/api/plugins/reset', { method: 'POST', json: { scope: 'user' } }).then(() => { setResetArmed(false); onChanged(); setMessage('用户级启停覆盖已清除，已恢复各插件 manifest 默认启用状态。'); }).catch((error) => setMessage(error instanceof Error ? error.message : String(error))).finally(() => setBusy(false));
    }}><RotateCcw />{resetArmed ? '再次点击恢复用户默认设置' : '恢复用户默认设置'}</Button></div>
    {message && <p role="status" className="whitespace-pre-wrap text-[11px] text-danger">{message}</p>}
  </section>;
}
