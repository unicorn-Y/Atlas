import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { LoaderCircle, RefreshCw, Search, X } from 'lucide-react';
import {
  listInstalledSkills, searchMarket, setSkillEnabled, SOURCE_KIND_LABEL,
  uninstallMarketSkill, type InstalledSkillRecord, type MarketSearchHit, type MarketTap,
  getSkillUsageOverview, removeSkillFromAgent,
} from '../services/skillsMarketApi';
import SkillCard from '../components/skills/SkillCard';
import SkillDetail from '../components/skills/SkillDetail';
import InstalledSkillCard from '../components/skills/InstalledSkillCard';
import UpdatesTab from '../components/skills/UpdatesTab';
import SourcesManager from '../components/skills/SourcesManager';
import SkillDiscoveryPage from './SkillDiscoveryPage';
import { useAtlasStore } from '../store/useAtlasStore';

export type SkillsTabId = 'market' | 'installed' | 'updates' | 'discovery' | 'doctor';

const TABS: Array<{ id: SkillsTabId; label: string }> = [
  { id: 'market', label: '市场' },
  { id: 'installed', label: '已安装' },
  { id: 'updates', label: '更新' },
  { id: 'discovery', label: '安全发现' },
  { id: 'doctor', label: '使用体检' },
];

const isTab = (value: unknown): value is SkillsTabId => value === 'market' || value === 'installed' || value === 'updates' || value === 'discovery' || value === 'doctor';

/** 侧栏「技能」入口的主页面：市场 / 已安装 / 更新 三个标签页。 */
export default function SkillsMarketPage({ apiBaseUrl, onToast, onTryInConversation, initialTab = 'market' }: {
  apiBaseUrl: string;
  onToast?: (message: string) => void;
  onTryInConversation?: (name: string) => void;
  initialTab?: SkillsTabId;
}) {
  const activeSkills = useAtlasStore((state) => state.activeSkills);
  const [tab, setTab] = useState<SkillsTabId>(() => (isTab(initialTab) ? initialTab : 'market'));
  const [taps, setTaps] = useState<MarketTap[]>([]);
  const [query, setQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [hits, setHits] = useState<MarketSearchHit[]>([]);
  const [selected, setSelected] = useState<MarketSearchHit | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketError, setMarketError] = useState('');
  const [installed, setInstalled] = useState<InstalledSkillRecord[]>([]);
  const [installedLoading, setInstalledLoading] = useState(false);
  const [installedError, setInstalledError] = useState('');
  const [busyName, setBusyName] = useState('');
  const [usageRows, setUsageRows] = useState<Awaited<ReturnType<typeof getSkillUsageOverview>>['skills']>([]);
  const [usageError, setUsageError] = useState('');
  const [usageFilter, setUsageFilter] = useState<'all' | 'unused' | 'stale'>('all');
  const loadUsage = useCallback(async () => {
    try { setUsageError(''); setUsageRows((await getSkillUsageOverview(apiBaseUrl)).skills); }
    catch (error) { setUsageError(error instanceof Error ? error.message : '技能使用数据读取失败'); }
  }, [apiBaseUrl]);

  const loadMarket = useCallback(async (q: string, source: string) => {
    setMarketLoading(true);
    setMarketError('');
    try {
      setHits(await searchMarket(apiBaseUrl, { q, source }));
    } catch (cause) {
      setMarketError(cause instanceof Error ? cause.message : '技能市场暂时打不开，请稍后重试。');
      setHits([]);
    } finally { setMarketLoading(false); }
  }, [apiBaseUrl]);

  const loadInstalled = useCallback(async () => {
    setInstalledLoading(true);
    setInstalledError('');
    try {
      setInstalled(await listInstalledSkills(apiBaseUrl));
    } catch (cause) {
      setInstalledError(cause instanceof Error ? cause.message : '已安装技能读取失败，可以稍后重试。');
    } finally { setInstalledLoading(false); }
  }, [apiBaseUrl]);

  useEffect(() => { void loadInstalled(); }, [loadInstalled]);
  // 挂载时先拉一份默认市场列表；之后的搜索都由表单提交 / 切换来源触发。
  useEffect(() => { void loadMarket('', ''); }, [loadMarket]);

  const submitSearch = (event: FormEvent) => { event.preventDefault(); void loadMarket(query, sourceFilter); };
  const refreshAll = async () => { await Promise.all([loadMarket(query, sourceFilter), loadInstalled()]); onToast?.('技能列表已刷新'); };

  const changeFilter = (next: string) => { setSourceFilter(next); void loadMarket(query, next); };

  const toggleInstalled = async (name: string, enabled: boolean) => {
    setBusyName(name);
    try {
      // 后端尚未实现时会返回 false：开关照常生效，并温和提示，不阻塞界面。
      const applied = await setSkillEnabled(apiBaseUrl, name, enabled);
      setInstalled((current) => current.map((item) => item.name === name ? { ...item, enabled } : item));
      if (!applied) onToast?.('当前后端版本还不支持启用开关，先记住你的选择');
      else onToast?.(enabled ? `已启用 ${name}` : `已停用 ${name}`);
    } catch (cause) {
      onToast?.(cause instanceof Error ? cause.message : '开关没有设置成功，请稍后再试。');
    } finally { setBusyName(''); }
  };

  const uninstall = async (name: string) => {
    setBusyName(name);
    try {
      await uninstallMarketSkill(apiBaseUrl, name);
      setInstalled((current) => current.filter((item) => item.name !== name));
      onToast?.(`已卸载 ${name}`);
      void loadMarket(query, sourceFilter);
    } catch (cause) {
      onToast?.(cause instanceof Error ? cause.message : `${name} 卸载失败，请稍后再试。`);
    } finally { setBusyName(''); }
  };

  const applyDiscoveredSkill = (name: string) => {
    if (activeSkills.includes(name)) {
      useAtlasStore.getState().removeSkill(name);
      onToast?.(`已从后续对话移除技能 ${name}`);
      return;
    }
    if (onTryInConversation) {
      onTryInConversation(name);
      return;
    }
    useAtlasStore.getState().applySkill(name);
    onToast?.(`已将 ${name} 应用到后续对话`);
  };

  const installedNameSet = new Set(installed.map((item) => item.name));
  const shownInstalled = installed.filter((item) => !query.trim() || `${item.name} ${item.description ?? ''}`.toLowerCase().includes(query.trim().toLowerCase()));

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div>
        <h1>技能市场</h1>
        <p>从市场找技能、管理已经装好的技能，有新版本时在这里更新。安装前可以看到 SKILL.md 和文件清单。</p>
      </div>
      <div className="btns">
        <button className="btn ghost" onClick={() => void refreshAll()} disabled={marketLoading || installedLoading}>
          {(marketLoading || installedLoading) ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}刷新
        </button>
      </div>
    </header>

    <div className="filterbar">
      <div className="seg" role="tablist" aria-label="技能页签">
        {TABS.map((item) => <button key={item.id} aria-pressed={tab === item.id}
          onClick={() => setTab(item.id)}>
          {item.label}{item.id === 'installed' && installed.length ? ` ${installed.length}` : ''}
        </button>)}
      </div>
      {tab === 'market' && <>
        <form className="field" onSubmit={submitSearch} role="search">
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索市场里的技能，例如：代码审查、周报" aria-label="搜索市场技能" />
        </form>
        <select className="input h-10" aria-label="按来源筛选"
          value={sourceFilter} onChange={(event) => changeFilter(event.target.value)}>
          <option value="">全部来源</option>
          {taps.map((tap) => <option key={tap.id} value={tap.kind}>{SOURCE_KIND_LABEL[tap.kind]}</option>)}
        </select>
      </>}
      {tab === 'installed' && <label className="field"><Search size={16} />
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="过滤已安装的技能" aria-label="过滤已安装技能" />
      </label>}
    </div>

    {marketError && tab === 'market' && <div role="alert" className="error-note">
      <span className="min-w-0 flex-1">{marketError}</span>
      <button className="btn ghost" onClick={() => void loadMarket(query, sourceFilter)}>重试</button>
      <button className="iconbtn" aria-label="关闭错误提示" onClick={() => setMarketError('')}><X size={15} /></button>
    </div>}
    {installedError && tab === 'installed' && <div role="alert" className="error-note">
      <span className="min-w-0 flex-1">{installedError}</span>
      <button className="btn ghost" onClick={() => void loadInstalled()}>重试</button>
      <button className="iconbtn" aria-label="关闭错误提示" onClick={() => setInstalledError('')}><X size={15} /></button>
    </div>}

    {tab === 'market' && <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(300px,380px)]">
      <section aria-label="市场搜索结果" aria-busy={marketLoading}>
        {marketLoading && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3" role="status">正在搜索技能市场…</div>}
        {!marketLoading && !hits.length && !marketError && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3" role="status">
          没有找到匹配的技能。换个关键词，或在下面的「技能来源」里添加更多来源再试。
        </div>}
        <div className="grid gap-2.5 sm:grid-cols-2">
          {hits.map((hit) => {
            const known = installedNameSet.has(hit.name);
            const decorated = known || hit.installed ? { ...hit, installed: true } : hit;
            return <SkillCard key={`${decorated.source}:${decorated.id}`} hit={decorated}
              selected={selected?.source === decorated.source && selected?.id === decorated.id}
              onSelect={(item) => setSelected(item)} />;
          })}
        </div>
      </section>
      {selected
        ? <SkillDetail apiBaseUrl={apiBaseUrl} hit={selected} onClose={() => setSelected(null)}
          onInstalled={() => { void loadInstalled(); void loadMarket(query, sourceFilter); onToast?.(`${selected.name} 安装完成`); }} />
        : <aside aria-label="技能详情" className="card-surface hidden rounded-2xl p-4 text-[12.5px] leading-relaxed text-fg-3 lg:block">
          在左边点一个技能，这里会显示它的介绍、SKILL.md 预览和文件清单，然后可以选择装到用户目录还是当前项目。
        </aside>}
      <div className="lg:col-span-2"><SourcesManager apiBaseUrl={apiBaseUrl} onTapsChange={setTaps} /></div>
    </div>}

    {tab === 'installed' && <section aria-label="已安装技能">
      {installedLoading && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3" role="status">正在读取已安装的技能…</div>}
      {!installedLoading && !shownInstalled.length && !installedError && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3" role="status">
        {installed.length ? '没有匹配的技能，换个过滤词试试。' : '这里还是空的。去「市场」标签页找一个技能装上，或把技能包放进技能目录。'}
      </div>}
      {!installedLoading && shownInstalled.map((skill) => <InstalledSkillCard key={skill.name} skill={skill} busy={busyName === skill.name}
        onToggle={(enabled) => void toggleInstalled(skill.name, enabled)}
        onUninstall={() => void uninstall(skill.name)}
        onTryInConversation={onTryInConversation} />)}
    </section>}

    {tab === 'updates' && <UpdatesTab apiBaseUrl={apiBaseUrl} onDone={onToast} />}
    {tab === 'doctor' && <section aria-label="技能使用体检" className="grid gap-3">
      <div className="flex flex-wrap items-center gap-2"><p className="m-0 flex-1 text-[12.5px] text-fg-3">按 Agent 查看使用次数、最后使用时间和 SKILL.md 上下文估算。</p>
        <select className="input h-9" aria-label="技能使用筛选" value={usageFilter} onChange={(event) => setUsageFilter(event.target.value as typeof usageFilter)}><option value="all">全部</option><option value="unused">从未使用</option><option value="stale">久未使用（30 天）</option></select>
        <button className="btn ghost" onClick={() => void loadUsage()}>检查使用情况</button></div>
      {usageError && <div role="alert" className="error-note">{usageError}</div>}
      {usageRows.filter((row) => usageFilter === 'all' || (usageFilter === 'unused' ? row.total_use_count === 0 : !row.last_used_at || Date.now() - Date.parse(row.last_used_at) > 30 * 86400000)).map((row) => <article key={row.skill_name} className="card-surface rounded-xl p-4">
        <div className="flex flex-wrap items-center gap-3"><b className="text-heading">{row.skill_name}</b><span className="text-[12px] text-fg-3">使用 {row.total_use_count} 次 · 约 {row.estimated_tokens} tokens</span><span className="text-[12px] text-fg-3">最后使用：{row.last_used_at ? new Date(row.last_used_at).toLocaleString() : '从未使用'}</span></div>
        <div className="mt-2 grid gap-1 text-[12px] text-fg-2">{row.agents.map((agent) => <div key={agent.agent_id} className="flex items-center gap-2"><span className="flex-1">{agent.agent_id} · {agent.use_count} 次 · {agent.last_used_at ? new Date(agent.last_used_at).toLocaleString() : '未记录'}</span><button className="btn ghost" onClick={async () => { await removeSkillFromAgent(apiBaseUrl, agent.agent_id, row.skill_name); await loadUsage(); onToast?.(`已从 ${agent.agent_id} 移除 ${row.skill_name}`); }}>从 Agent 移除</button></div>)}</div>
      </article>)}
      {!usageRows.length && !usageError && <div className="card-surface rounded-xl p-4 text-[12.5px] text-fg-3">点击“检查使用情况”加载技能体检数据。</div>}
    </section>}
    {tab === 'discovery' && <section aria-label="技能安全发现与信任审查">
      <div className="mb-3 rounded-xl border border-line bg-sunken px-3 py-2 text-[12.5px] leading-relaxed text-fg-2">
        外部来源的技能会先经过内容与依赖审查；风险项需要明确确认，信任、固定版本和回滚操作会留下审计记录。
      </div>
      <SkillDiscoveryPage apiBaseUrl={apiBaseUrl} activeSkills={activeSkills} onApplySkill={applyDiscoveredSkill} />
    </section>}
  </div></div>;
}
