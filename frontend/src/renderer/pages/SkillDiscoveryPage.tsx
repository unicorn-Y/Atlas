import { useEffect, useState, type FormEvent } from 'react';
import { Search, WandSparkles } from 'lucide-react';
import styles from '../App.module.css';
import { buildSkillDiscoveryUrl, canActivateLocalSkill } from './skillDiscoveryUrl';

type SkillResult = {
  name: string; version: string; description: string; capabilities: string[]; tools: string[];
  requirements: unknown; source: string; status: string; category?: string; tags?: string[];
  relevance_score: number; match_reasons: string[]; matched_fields: string[];
};

interface Props { apiBaseUrl: string }

export default function SkillDiscoveryPage({ apiBaseUrl }: Props) {
  const [query, setQuery] = useState('');
  const [capability, setCapability] = useState('');
  const [tool, setTool] = useState('');
  const [source, setSource] = useState('');
  const [results, setResults] = useState<SkillResult[]>([]);
  const [selected, setSelected] = useState<SkillResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [activation, setActivation] = useState('');

  const search = async (event?: FormEvent) => {
    event?.preventDefault();
    setLoading(true);
    setError('');
    setActivation('');
    try {
      const response = await fetch(buildSkillDiscoveryUrl(apiBaseUrl, { query, capability, tool, source }));
      if (!response.ok) throw new Error(`技能检索失败（HTTP ${response.status}）`);
      const data = await response.json() as { results: SkillResult[] };
      setResults(data.results);
      setSelected(data.results[0] ?? null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '技能检索暂不可用');
      setResults([]);
      setSelected(null);
    } finally { setLoading(false); }
  };

  useEffect(() => { void search(); }, [apiBaseUrl]);

  const activate = async (skill: SkillResult) => {
    setActivation('');
    try {
      const response = await fetch(`${apiBaseUrl}/api/skills/${encodeURIComponent(skill.name)}/activate`);
      if (!response.ok) throw new Error(`无法打开本地技能（HTTP ${response.status}）`);
      const data = await response.json() as { content: string; dependencies?: { missing?: string[] } };
      const missingItems = Object.entries(data.dependencies ?? {})
        .filter(([, satisfied]) => !satisfied)
        .map(([name]) => name);
      const missing = missingItems.length ? `\n\n缺少依赖：${missingItems.join(', ')}` : '';
      setActivation(`${data.content}${missing}`);
    } catch (cause) {
      setActivation(cause instanceof Error ? cause.message : '无法打开本地技能');
    }
  };

  return <section className={styles.skillCenter} aria-label="技能发现">
    <header className={styles.skillCenterHeader}><div><span>本地技能库</span><h1>技能发现</h1><p>按任务描述检索已注册技能。搜索只返回候选，不会自动激活。</p></div></header>
    <form className={styles.skillSearchForm} onSubmit={(event) => void search(event)}>
      <label className={styles.skillSearchBox}><Search size={17} /><input aria-label="任务或技能搜索" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="描述你要完成的任务…" /><button disabled={loading}>{loading ? '搜索中…' : '搜索技能'}</button></label>
      <div className={styles.skillFilters}>
        <label>能力<input aria-label="能力筛选" value={capability} onChange={(event) => setCapability(event.target.value)} placeholder="全部能力" /></label>
        <label>工具<input aria-label="工具筛选" value={tool} onChange={(event) => setTool(event.target.value)} placeholder="全部工具" /></label>
        <label>来源<input aria-label="来源筛选" value={source} onChange={(event) => setSource(event.target.value)} placeholder="全部来源" /></label>
      </div>
    </form>
    {error && <div className={styles.skillStateError} role="alert">{error}。你仍可继续正常聊天。</div>}
    {!error && !loading && !results.length && <div className={styles.skillStateEmpty} role="status">没有匹配的本地技能。可调整关键词或筛选条件。</div>}
    <div className={styles.skillDiscoveryGrid}>
      <div className={styles.skillDiscoveryResults} aria-label="技能检索结果">
        {results.map((item) => <button className={`${styles.skillDiscoveryCard} ${selected?.name === item.name && selected.version === item.version ? styles.skillDiscoverySelected : ''}`} key={`${item.name}@${item.version}`} onClick={() => { setSelected(item); setActivation(''); }}>
          <span><strong>{item.name}</strong><small>v{item.version} · {item.status}</small></span>
          <p>{item.description}</p><small>匹配分 {item.relevance_score} · {item.matched_fields.join('、') || '筛选匹配'}</small>
        </button>)}
      </div>
      {selected && <article className={styles.skillDiscoveryDetail} aria-label="技能详情">
        <div className={styles.skillDetailTitle}><div><small>{selected.source} · {selected.status}</small><h2>{selected.name}</h2></div><span>v{selected.version}</span></div>
        <p>{selected.description}</p>
        <div className={styles.skillDetailSection}><strong>匹配原因</strong>{selected.match_reasons.length ? <ul>{selected.match_reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul> : <small>该技能符合当前筛选条件。</small>}</div>
        <div className={styles.skillDetailSection}><strong>能力 / 工具</strong><p>{selected.capabilities.join(' · ') || '未声明能力'} / {selected.tools.join(' · ') || '未声明工具'}</p></div>
        <div className={styles.skillDetailSection}><strong>依赖 / Requirements</strong><pre>{JSON.stringify(selected.requirements ?? [], null, 2)}</pre></div>
        {canActivateLocalSkill(selected) && <button className={styles.skillActivateButton} onClick={() => void activate(selected)}><WandSparkles size={15} />打开本地技能</button>}
        {activation && <pre className={styles.skillActivationContent} role="status">{activation}</pre>}
      </article>}
    </div>
  </section>;
}
