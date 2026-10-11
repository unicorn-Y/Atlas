/**
 * Extension catalog backed by Atlas PluginRuntime and Skill Market state.
 * Pi package references: https://github.com/badlogic/pi-mono/blob/e37cdc420669e48b4df4bbce0fb2617fc3c71328/packages/coding-agent/docs/packages.md
 * Cline Marketplace reference: https://github.com/cline/marketplace
 */
import { useEffect, useMemo, useState } from 'react';
import { ExternalLink, PackageSearch, RefreshCw, RotateCcw, ToggleLeft, ToggleRight } from 'lucide-react';
import { api } from '../../services/api';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import type { ExtensionPackageSource, PackageResourceKind } from './ExtensionPackagesPanel';

type CatalogKind = PackageResourceKind | 'all';
type Resource = {
  id: string;
  name: string;
  description: string;
  kind: PackageResourceKind;
  source: string;
  scope: string;
  state: string;
  details?: string;
  toggle?: 'plugin' | 'skill' | 'source';
  enabled?: boolean;
  toggleDisabled?: boolean;
};
type PackageSource = ExtensionPackageSource & {
  runtime_supported?: boolean;
  runtime_source_name?: string | null;
  runtime_enabled?: boolean;
  runtime_source_managed?: boolean;
};
type SkillMarketSource = { name: string; enabled: boolean; kind: string };
type SkillInstall = Record<string, unknown> & { name?: string; scope?: string; status?: string; source?: string; origin_kind?: string };
const kindLabels: Record<PackageResourceKind, string> = { extension: '扩展', skill: '技能', prompt: '提示词', theme: '主题' };
const clineMarketplace = 'https://github.com/cline/marketplace';
const projectScopeReason = '项目级扩展加载不可用：PluginRuntime 与 Skill Market source registry 由当前进程共享，尚无按会话工作区隔离的加载接口。';

/** Catalog rows show real lifecycle state. Safe skill catalogs use the existing Skill Market; plugin toggles call PluginRuntime. */
export default function ExtensionCatalogPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [resources, setResources] = useState<Resource[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [kind, setKind] = useState<CatalogKind>('all');
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [lastLoaded, setLastLoaded] = useState('');
  const [resetArmed, setResetArmed] = useState(false);

  const load = async () => {
    setBusy(true);
    const [pluginsResult, skillsResult, installedResult, skillSourcesResult, sourcesResult] = await Promise.allSettled([
      api<{ plugins: Record<string, unknown>[] }>(apiBaseUrl, '/api/plugins'),
      api<{ skills: Record<string, unknown>[] }>(apiBaseUrl, '/api/skills'),
      api<{ skills: SkillInstall[] }>(apiBaseUrl, '/api/skills/market/installed'),
      api<{ sources: SkillMarketSource[] }>(apiBaseUrl, '/api/skills/market/sources'),
      api<{ sources: PackageSource[]; scope_capabilities?: { project?: { available: boolean; reason: string } } }>(apiBaseUrl, '/api/extension-packages'),
    ]);
    const rows: Resource[] = [];
    const nextErrors: string[] = [];
    const installedByName = new Map<string, SkillInstall[]>();
    if (installedResult.status === 'fulfilled') {
      for (const item of installedResult.value.skills ?? []) {
        const name = String(item.name ?? '');
        if (name) installedByName.set(name, [...(installedByName.get(name) ?? []), item]);
      }
    } else nextErrors.push(`已安装技能状态：${installedResult.reason instanceof Error ? installedResult.reason.message : String(installedResult.reason)}`);
    const runtimeSkillSources = skillSourcesResult.status === 'fulfilled'
      ? new Map(skillSourcesResult.value.sources.map((item) => [item.name, item]))
      : new Map<string, SkillMarketSource>();
    if (skillSourcesResult.status === 'rejected') nextErrors.push(`技能来源运行状态：${skillSourcesResult.reason instanceof Error ? skillSourcesResult.reason.message : String(skillSourcesResult.reason)}`);

    if (pluginsResult.status === 'fulfilled') {
      for (const item of pluginsResult.value.plugins ?? []) {
        const name = String(item.name ?? item.id ?? rows.length);
        const enabled = item.enabled !== false;
        rows.push({
          id: `plugin:${name}`, name: String(item.display_name ?? name), description: String(item.description ?? ''),
          kind: 'extension', source: String(item.source ?? item.path ?? 'Atlas PluginRuntime'),
          scope: '用户 · PluginRuntime 进程级加载', state: String(item.loaded ? '已加载' : enabled ? '已启用' : '已停用'),
          details: item.version ? `版本 ${String(item.version)}${item.manifest ? ` · ${String(item.manifest)}` : ''}` : String(item.manifest ?? ''),
          toggle: 'plugin', enabled,
        });
      }
    } else nextErrors.push(`扩展目录：${pluginsResult.reason instanceof Error ? pluginsResult.reason.message : String(pluginsResult.reason)}`);

    if (skillsResult.status === 'fulfilled') {
      for (const item of skillsResult.value.skills ?? []) {
        const name = String(item.name ?? item.id ?? rows.length);
        const installs = installedByName.get(name) ?? [];
        const isUnambiguousUserMarketSkill = installs.length === 1 && installs[0].scope === 'user';
        const install = installs.length === 1 ? installs[0] : undefined;
        const status = String(install?.status ?? item.status ?? 'available');
        rows.push({
          id: `skill:${name}`, name, description: String(item.description ?? ''), kind: 'skill',
          source: String(item.source ?? item.origin_kind ?? install?.source ?? 'Atlas SkillManager'),
          scope: install?.scope === 'project' ? '项目 · SkillMarket 使用配置的默认工作区' : '用户 · SkillManager',
          state: status === 'active' ? '已启用' : status === 'disabled' ? '已停用' : status,
          details: installs.length > 1 ? '同名技能有多个安装范围；为避免误改，目录不开启合并状态的切换。' : String(install?.origin_kind ?? ''),
          toggle: isUnambiguousUserMarketSkill ? 'skill' : undefined,
          enabled: status !== 'disabled',
          toggleDisabled: Boolean(install?.scope === 'project'),
        });
      }
    } else nextErrors.push(`技能目录：${skillsResult.reason instanceof Error ? skillsResult.reason.message : String(skillsResult.reason)}`);

    if (sourcesResult.status === 'fulfilled') {
      for (const source of sourcesResult.value.sources ?? []) {
        for (const resourceKind of source.resource_kinds ?? []) {
          const runtimeSource = source.runtime_source_name ? runtimeSkillSources.get(source.runtime_source_name) : undefined;
          const runtimeSupportedKind = source.runtime_supported && resourceKind === 'skill';
          const metadata = Object.entries(source.registry_metadata ?? {}).map(([key, value]) => `${key}: ${String(value)}`).join(' · ');
          const details = [source.diagnostics?.join(' · '), metadata].filter(Boolean).join(' · ');
          rows.push({
            id: `source:${source.id}:${resourceKind}`, name: source.name,
            description: runtimeSupportedKind
              ? '已接入 Atlas Skill Market；启用状态控制该来源是否参与技能检索。'
              : '该来源已登记，但没有安全可用的加载器。',
            kind: resourceKind, source: `${source.source_type}: ${source.source}`, scope: source.scope,
            state: runtimeSupportedKind ? (runtimeSource?.enabled === false ? '来源已停用' : '来源已启用') : source.validation_state,
            details,
            toggle: runtimeSupportedKind ? 'source' : undefined,
            enabled: runtimeSource?.enabled ?? source.runtime_enabled ?? false,
          });
        }
      }
    } else nextErrors.push(`包来源目录：${sourcesResult.reason instanceof Error ? sourcesResult.reason.message : String(sourcesResult.reason)}`);
    setResources(rows); setErrors(nextErrors); setLastLoaded(new Date().toLocaleTimeString()); setBusy(false);
  };
  useEffect(() => { void load(); }, [apiBaseUrl]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return resources.filter((item) => (kind === 'all' || item.kind === kind)
      && (!query || `${item.name} ${item.description} ${item.source} ${item.state}`.toLowerCase().includes(query)));
  }, [resources, kind, search]);
  const control = 'h-8 rounded-lg bg-sunken px-2.5 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';

  const toggle = async (item: Resource) => {
    if (!item.toggle || item.enabled === undefined) return;
    setBusy(true);
    try {
      if (item.toggle === 'plugin') {
        const name = item.id.slice('plugin:'.length);
        await api(apiBaseUrl, `/api/plugins/${encodeURIComponent(name)}/enabled`, { method: 'POST', json: { enabled: !item.enabled } });
      } else if (item.toggle === 'skill') {
        const name = item.id.slice('skill:'.length);
        await api(apiBaseUrl, `/api/skills/market/${encodeURIComponent(name)}/enabled`, { method: 'PATCH', json: { enabled: !item.enabled } });
      } else {
        const sourceId = item.id.slice('source:'.length, item.id.lastIndexOf(':'));
        await api(apiBaseUrl, `/api/extension-packages/${encodeURIComponent(sourceId)}/enabled`, { method: 'POST', json: { enabled: !item.enabled } });
      }
      await load();
    } catch (error) {
      setErrors((current) => [...current, error instanceof Error ? error.message : String(error)]);
      setBusy(false);
    }
  };

  const resetDefaults = async () => {
    if (!resetArmed) { setResetArmed(true); return; }
    setBusy(true);
    try {
      await api(apiBaseUrl, '/api/extension-packages/reset', { method: 'POST', json: { scope: 'user' } });
      setResetArmed(false);
      await load();
    } catch (error) {
      setErrors((current) => [...current, error instanceof Error ? error.message : String(error)]);
      setBusy(false);
    }
  };

  return <section className="grid gap-4" aria-label="扩展目录">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-[15px] font-semibold text-fg">扩展目录</h2><p className="mt-1 text-[12.5px] text-fg-3">扩展开关调用现有 PluginRuntime；技能开关与来源状态调用 Atlas Skill Market。</p></div><div className="flex gap-2"><Button size="sm" variant={resetArmed ? 'danger' : 'ghost'} disabled={busy} onClick={() => void resetDefaults()}><RotateCcw />{resetArmed ? '再次点击恢复默认来源' : '恢复默认来源'}</Button><Button size="sm" disabled={busy} onClick={() => void load()}><RefreshCw className={busy ? 'animate-spin' : ''} />刷新</Button></div></header>

    <section className="grid gap-2 rounded-xl bg-sunken p-3 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><PackageSearch size={17} className="text-brand" /><div><p className="text-[12.5px] font-medium text-fg">Cline Marketplace</p><p className="text-[11px] text-fg-3">GitHub catalog reference · 不可直接作为 Atlas 插件加载源</p></div></div><a href={clineMarketplace} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 text-[12px] text-brand hover:underline">查看目录仓库<ExternalLink size={13} /></a></div>
      <p className="text-[11.5px] leading-relaxed text-fg-3">项目作用域当前不可选。Atlas 插件加载与扩展注册表是进程级共享；若将项目开关写成有效状态，会影响其他工作区。技能市场已安装到项目目录的技能显示其实际安装范围，但现有运行时只使用配置的默认工作区。</p>
    </section>

    <div className="flex flex-wrap gap-2"><select aria-label="资源类型筛选" value={kind} onChange={(event) => setKind(event.target.value as CatalogKind)} className={control}><option value="all">所有类型</option>{Object.entries(kindLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select><input aria-label="搜索目录" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称、说明或来源" className={cn(control, 'min-w-60 flex-1')} /><span className="self-center text-[11px] text-fg-3">{filtered.length} 项{lastLoaded && ` · ${lastLoaded} 更新`}</span></div>

    {errors.length > 0 && <div role="status" className="grid gap-1 rounded-lg bg-danger-soft p-2.5 text-[11.5px] text-danger">{errors.map((error, index) => <p key={`${index}-${error}`}>{error}</p>)}</div>}
    {filtered.length ? <div className="grid gap-2">{filtered.map((item) => <article key={item.id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 rounded-xl bg-sunken p-3 shadow-[inset_0_0_0_1px_var(--line)]">
      <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><h3 className="truncate text-[13px] font-medium text-fg">{item.name}</h3><span className="rounded-md bg-sunken px-1.5 py-0.5 text-[10px] text-fg-3">{kindLabels[item.kind]}</span><span className="text-[10px] text-fg-3">{item.scope} · {item.state}</span></div><p className="mt-1 text-[11.5px] text-fg-3">{item.description || '—'}</p><p className="mt-1 truncate font-mono text-[10.5px] text-fg-3" title={item.source}>{item.source}</p>{item.details && <p className="mt-1 text-[10.5px] leading-relaxed text-fg-3">{item.details}</p>}</div>
      {item.toggle ? <Button size="sm" variant={item.enabled ? 'primary' : 'ghost'} disabled={busy || item.toggleDisabled} title={item.toggleDisabled ? projectScopeReason : undefined} onClick={() => void toggle(item)}>{item.enabled ? <ToggleRight /> : <ToggleLeft />}{item.toggleDisabled ? '项目范围不可切换' : item.enabled ? '停用' : '启用'}</Button> : <span className="self-center text-[10px] uppercase tracking-wide text-fg-3">{item.id.startsWith('source:') ? 'metadata' : 'local'}</span>}
    </article>)}</div> : <div className="grid min-h-32 place-items-center rounded-xl border border-dashed border-line text-[12px] text-fg-3">{busy ? '正在读取目录…' : '没有符合筛选条件的资源。'}</div>}
  </section>;
}
