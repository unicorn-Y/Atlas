import { useEffect, useState, type FormEvent } from 'react';
import { Search, WandSparkles } from 'lucide-react';
import styles from '../App.module.css';
import { buildSkillDiscoveryUrl, canActivateLocalSkill } from './skillDiscoveryUrl';
import { approveSkillInstallation, remoteSkillLabel, reviewGateState } from './skillAcquisitionReview';

type SkillResult = {
  name: string; version: string; description: string; capabilities: string[]; tools: string[];
  requirements: unknown; source: string; status: string; category?: string; tags?: string[];
  relevance_score: number; match_reasons: string[]; matched_fields: string[];
};
type RemoteSkill = { provider: string; external_id: string; name: string; description: string; source: string; source_type: string; source_url: string; install_url: string; remote_hash?: string | null; provider_computed_hash?: string | null; audit?: unknown; provider_integrity?: { provider_hash?: string | null; provider_computed_hash?: string | null; provider_mismatch?: boolean; fallback_reason?: string; github_source?: string; github_source_revision?: string; github_tree_sha?: string }; integrity_diagnostic?: { status?: string; message?: string; provider_hash?: string | null; provider_computed_hash?: string | null; github_source?: string; github_source_revision?: string; github_tree_sha?: string; github_source_error?: string }; installed: boolean; state: string };
type Review = { acquisition_id: string; record: RemoteSkill & { version: string; description: string }; files: Record<string, string>; validation: { result: string; dependencies: string[] }; security: { result: 'PASS' | 'WARN' | 'BLOCK'; risks: string[]; note: string }; computed_sha256: string; already_installed: boolean; existing_local?: Record<string, unknown> | null; install_target: string };
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
  const [mode, setMode] = useState<'local' | 'external' | 'all'>('local');
  const [remoteResults, setRemoteResults] = useState<RemoteSkill[]>([]);
  const [catalogStatus, setCatalogStatus] = useState('');
  const [review, setReview] = useState<Review | null>(null);
  const [confirmWarnings, setConfirmWarnings] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [installState, setInstallState] = useState('');
  const [githubSource, setGithubSource] = useState('');
  const [githubPath, setGithubPath] = useState('');

  const search = async (event?: FormEvent, requestedMode = mode) => {
    event?.preventDefault();
    setLoading(true);
    setError('');
    setActivation('');
    try {
      if (requestedMode !== 'external') {
        try {
          const response = await fetch(buildSkillDiscoveryUrl(apiBaseUrl, { query, capability, tool, source }));
          if (!response.ok) throw new Error(`技能检索失败（HTTP ${response.status}）`);
          const data = await response.json() as { results: SkillResult[] };
          setResults(data.results); setSelected(data.results[0] ?? null);
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : '本地技能检索暂不可用');
          setResults([]); setSelected(null);
        }
      } else { setResults([]); setSelected(null); }
      if (requestedMode !== 'local') {
        try {
          const response = await fetch(`${apiBaseUrl}/api/skill-catalog/search?q=${encodeURIComponent(query.trim() || 'skills')}`);
          const data = await response.json() as { results: RemoteSkill[]; status: string };
          setRemoteResults(data.results ?? []); setCatalogStatus(data.status === 'available' ? '外部目录在线' : 'external-catalog-unavailable');
        } catch {
          setRemoteResults([]); setCatalogStatus('external-catalog-unavailable');
        }
      } else { setRemoteResults([]); setCatalogStatus(''); }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '技能检索暂不可用');
      setResults([]);
      setSelected(null);
    } finally { setLoading(false); }
  };

  useEffect(() => { void search(); }, [apiBaseUrl]);

  const inspectRemote = async (skill: RemoteSkill) => {
    setReview(null); setInstallState('正在获取不可信内容并执行预检…');
    try {
      const response = await fetch(`${apiBaseUrl}/api/skill-catalog/inspect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: skill.provider, external_id: skill.external_id }) });
      const data = await response.json() as Review;
      if (!response.ok) throw new Error((data as unknown as { detail?: string }).detail ?? '预览获取失败');
      setReview(data); setInstallState('');
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : '预览获取失败'); }
  };

  const inspectGithub = async () => {
    setReview(null); setInstallState('正在解析公开 GitHub 来源…');
    try {
      const response = await fetch(`${apiBaseUrl}/api/skill-catalog/inspect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider: 'github', source_url: githubSource, skill_path: githubPath }) });
      const data = await response.json() as Review;
      if (!response.ok) throw new Error((data as unknown as { detail?: string }).detail ?? 'GitHub Skill 获取失败');
      setReview(data); setInstallState('');
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : 'GitHub Skill 获取失败'); }
  };

  const installReviewed = async (warningsConfirmed = false) => {
    if (!review) return;
    const gate = reviewGateState(review.security.result, review.already_installed);
    if (!gate.canInstall) return;
    if (gate.requiresWarningConfirmation && !warningsConfirmed) { setConfirmWarnings(true); return; }
    setInstalling(true); setInstallState('正在记录明确批准并安全安装…');
    try {
      const response = await approveSkillInstallation(apiBaseUrl, review.acquisition_id, warningsConfirmed);
      const data = await response.json() as { detail?: string; name?: string };
      if (!response.ok) throw new Error(data.detail ?? '安装失败');
      setInstallState(`已安装 ${data.name}，本地索引已刷新。`); setReview(null); setConfirmWarnings(false); await search();
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : '安装失败'); }
    finally { setInstalling(false); }
  };

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
    <header className={styles.skillCenterHeader}><div><span>Skill Catalog</span><h1>技能发现</h1><p>本地搜索保持离线可用。远程技能需审查并明确批准后才会安装。</p></div></header>
    <nav className={styles.skillCatalogTabs} aria-label="技能来源">{(['local', 'external', 'all'] as const).map((item) => <button type="button" key={item} aria-pressed={mode === item} onClick={() => { setMode(item); void search(undefined, item); }}>{item === 'local' ? 'Local' : item === 'external' ? 'External Catalog' : 'All'}</button>)}</nav>
    {mode !== 'local' && <fieldset className={styles.skillGithubSource}><legend>直接检查公开 GitHub Skill</legend><label>Repository URL<input aria-label="公开 GitHub 仓库" value={githubSource} onChange={(event) => setGithubSource(event.target.value)} placeholder="https://github.com/owner/repo" /></label><label>Skill path<input aria-label="GitHub Skill 路径" value={githubPath} onChange={(event) => setGithubPath(event.target.value)} placeholder="skills/example-skill" /></label><button type="button" disabled={!githubSource} onClick={() => void inspectGithub()}>检查 GitHub 来源</button></fieldset>}
    <form className={styles.skillSearchForm} onSubmit={(event) => void search(event)}>
      <label className={styles.skillSearchBox}><Search size={17} /><input aria-label="任务或技能搜索" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="描述你要完成的任务…" /><button disabled={loading}>{loading ? '搜索中…' : '搜索技能'}</button></label>
      <div className={styles.skillFilters}>
        <label>能力<input aria-label="能力筛选" value={capability} onChange={(event) => setCapability(event.target.value)} placeholder="全部能力" /></label>
        <label>工具<input aria-label="工具筛选" value={tool} onChange={(event) => setTool(event.target.value)} placeholder="全部工具" /></label>
        <label>来源<input aria-label="来源筛选" value={source} onChange={(event) => setSource(event.target.value)} placeholder="全部来源" /></label>
      </div>
    </form>
    {error && <div className={styles.skillStateError} role="alert">{error}。你仍可继续正常聊天。</div>}
    {mode !== 'local' && <div role="status">External catalog: {catalogStatus || '等待搜索'}</div>}
    {!error && !loading && !results.length && <div className={styles.skillStateEmpty} role="status">没有匹配的本地技能。可调整关键词或筛选条件。</div>}
    <div className={styles.skillDiscoveryGrid}>
      <div className={styles.skillDiscoveryResults} aria-label="技能检索结果">
        {results.map((item) => <button className={`${styles.skillDiscoveryCard} ${selected?.name === item.name && selected.version === item.version ? styles.skillDiscoverySelected : ''}`} key={`${item.name}@${item.version}`} onClick={() => { setSelected(item); setActivation(''); }}>
          <span><strong>{item.name}</strong><small>v{item.version} · {item.status}</small></span>
          <p>{item.description}</p><small>匹配分 {item.relevance_score} · {item.matched_fields.join('、') || '筛选匹配'}</small>
        </button>)}
      </div>
      {mode !== 'local' && <div className={styles.skillRemoteResults} aria-label="外部未安装技能">{remoteResults.map((item) => <article className={styles.skillRemoteCard} key={`${item.provider}:${item.external_id}`}><strong>{item.name}</strong><small>{item.provider} · {remoteSkillLabel(item.installed)}</small><p>{item.source}</p><a href={item.source_url} target="_blank" rel="noreferrer">来源仓库</a><button type="button" onClick={() => void inspectRemote(item)}>{item.installed ? '查看版本冲突' : '检查与预览'}</button></article>)}</div>}
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
    {installState && <div role="status">{installState}</div>}
    {review && <section role="dialog" aria-modal="true" aria-label="安装前安全审查"><h2>安装前审查：{review.record.name}</h2><p>版本 {review.record.version} · {review.record.provider} · {review.record.source_url}</p><p>{review.record.description}</p>{review.record.integrity_diagnostic?.message && <p role="alert">完整性诊断：{review.record.integrity_diagnostic.message}{review.record.integrity_diagnostic.github_source_revision ? ` GitHub revision ${review.record.integrity_diagnostic.github_source_revision}.` : ''}{review.record.integrity_diagnostic.github_tree_sha ? ` Tree ${review.record.integrity_diagnostic.github_tree_sha}.` : ''}{review.record.integrity_diagnostic.github_source_error ? ` ${review.record.integrity_diagnostic.github_source_error}` : ''}</p>}<p>Provider 参考哈希：{review.record.provider_integrity?.provider_computed_hash ?? review.record.integrity_diagnostic?.provider_computed_hash ?? review.record.provider_computed_hash ?? '不可用'}</p><p>安全检查：{review.security.result} · {review.security.risks.join(', ') || '未发现已知风险模式'}</p><p>{review.security.note}</p><p>审计：{JSON.stringify(review.record.audit ?? '无可用审计')}</p><p>远程哈希：{review.record.remote_hash ?? '未提供'}</p><p>本地 SHA-256：{review.computed_sha256}</p><p>验证：{review.validation.result} · 声明依赖：{review.validation.dependencies.join(', ') || '无'}</p><p>已安装：{review.already_installed ? '是' : '否'} · 目标：{review.install_target}</p>{review.already_installed && <section aria-label="已安装版本冲突"><h3>本地版本与来源</h3><pre>{JSON.stringify({ existing: review.existing_local, incoming: { source: review.record.source_url, hash: review.computed_sha256 } }, null, 2)}</pre></section>}<h3>文件树与内容预览</h3><ul>{Object.keys(review.files).map((file) => <li key={file}>{file}</li>)}</ul>{Object.entries(review.files).map(([file, content]) => <details key={file}><summary>{file}</summary><pre>{content}</pre></details>)}<button type="button" onClick={() => { setReview(null); setConfirmWarnings(false); }}>取消</button><button type="button" disabled={installing || review.security.result === 'BLOCK' || review.already_installed} onClick={() => void installReviewed()}>{review.security.result === 'BLOCK' ? '已阻止安装' : '我已审查并批准安装'}</button></section>}
    {confirmWarnings && review && <section role="dialog" aria-modal="true" aria-label="确认风险后安装"><h2>此 Skill 包含风险提示</h2><p>{review.security.risks.join('、')}</p><p>风险扫描只提供证据，不能证明内容绝对安全。确认后将安装到 {review.install_target}。</p><button type="button" onClick={() => setConfirmWarnings(false)}>返回审查</button><button type="button" disabled={installing} onClick={() => void installReviewed(true)}>我理解风险，仍然安装</button></section>}
  </section>;
}
