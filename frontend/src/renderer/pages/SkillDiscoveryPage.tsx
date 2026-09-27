import { useEffect, useState, type FormEvent } from 'react';
import { Search, WandSparkles } from 'lucide-react';
import styles from '../App.module.css';
import { buildSkillDiscoveryUrl, canActivateLocalSkill } from './skillDiscoveryUrl';
import { approveSkillInstallation, formatCanonicalDependencies, lifecycleUpdateAction, localPackageReviewState, remoteSkillLabel, reviewGateState, type CanonicalDependency } from './skillAcquisitionReview';

type SkillResult = {
  name: string; version: string; description: string; capabilities: string[]; tools: string[];
  requirements: unknown; source: string; status: string; category?: string; tags?: string[];
  relevance_score: number; match_reasons: string[]; matched_fields: string[];
};
type RemoteSkill = { provider: string; external_id: string; name: string; description: string; source: string; source_type: string; source_url: string; install_url: string; remote_hash?: string | null; provider_computed_hash?: string | null; audit?: unknown; provider_integrity?: { provider_hash?: string | null; provider_computed_hash?: string | null; provider_mismatch?: boolean; fallback_reason?: string; github_source?: string; github_source_revision?: string; github_tree_sha?: string }; integrity_diagnostic?: { status?: string; message?: string; provider_hash?: string | null; provider_computed_hash?: string | null; github_source?: string; github_source_revision?: string; github_tree_sha?: string; github_source_error?: string }; installed: boolean; state: string };
type Review = { acquisition_id: string; record: RemoteSkill & { version: string; description: string }; files: Record<string, string>; validation: { result: string; dependencies: CanonicalDependency[] }; security: { result: 'PASS' | 'WARN' | 'BLOCK'; risks: string[]; note: string }; computed_sha256: string; already_installed: boolean; existing_local?: Record<string, unknown> | null; install_target: string; dependency_state?: { name: string; state: string }[]; file_diff?: { added: string[]; removed: string[]; changed: string[]; unchanged: string[] } };
type Lifecycle = { lifecycle: { state: string; trust_state: string; pin_policy: string; pinned_hash?: string | null; content_hash?: string | null; actual_hash?: string | null; drifted: boolean }; provenance: Record<string, unknown>; dependency_state: { name: string; state: string }[]; history: { event_id: string; action: string; skill_version: string; previous_hash?: string; resulting_hash?: string; timestamp: string; result: string; details?: Record<string, unknown> }[] };
type Dependency = { name: string; kind: string; requested?: string | null; detected: unknown; state: string; source: string; blocking_reason?: string | null };
type LocalPackageReview = { acquisition_id: string; record: { name: string; version: string; description: string; provider: string; source_url: string }; files: Record<string, string>; security: { result: string; risks: string[]; note: string }; computed_sha256: string; dependency_state: Dependency[]; already_installed: boolean; name_conflict: boolean; exact_version_conflict: boolean; same_name_existing: boolean; import_state: 'new_skill' | 'exact_version_conflict' | 'update_candidate'; existing_version?: string | null; install_target: string };
interface Props { apiBaseUrl: string }

async function skillCenterHeaders(): Promise<Record<string, string>> {
  const token = await window.atlasDesktop?.getSkillCenterToken();
  if (!token) throw new Error('可信 Skill Center 会话不可用');
  return { 'Content-Type': 'application/json', 'X-Atlas-Skill-Center-Token': token };
}

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
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null);
  const [dependencies, setDependencies] = useState<Dependency[]>([]);
  const [dependenciesReady, setDependenciesReady] = useState(false);
  const [dependencyLoadError, setDependencyLoadError] = useState(false);
  const [dependencyPlan, setDependencyPlan] = useState<Record<string, unknown> | null>(null);
  const [packageReview, setPackageReview] = useState<LocalPackageReview | null>(null);
  const [packageBusy, setPackageBusy] = useState(false);

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

  useEffect(() => {
    setLifecycle(null);
    if (!selected) return;
    void fetch(`${apiBaseUrl}/api/skills/lifecycle/${encodeURIComponent(selected.name)}/${encodeURIComponent(selected.version)}`)
      .then(async (response) => response.ok ? response.json() as Promise<Lifecycle> : null)
      .then((value) => setLifecycle(value))
      .catch(() => setLifecycle(null));
  }, [apiBaseUrl, selected?.name, selected?.version]);

  useEffect(() => {
    setDependencies([]);
    setDependenciesReady(false);
    setDependencyLoadError(false);
    if (!selected) return;
    void fetch(`${apiBaseUrl}/api/skills/${encodeURIComponent(selected.name)}/dependencies`)
      .then(async (response) => {
        if (!response.ok) throw new Error('dependency preflight unavailable');
        return await response.json() as { dependencies: Dependency[] };
      })
      .then((value) => {
        setDependencies(value.dependencies ?? []);
        setDependenciesReady(true);
      })
      .catch(() => {
        setDependencies([]);
        setDependencyLoadError(true);
      });
  }, [apiBaseUrl, selected?.name, selected?.version]);

  const lifecycleAction = async (action: 'remove' | 'trust' | 'pin' | 'unpin' | 'rollback', extra: Record<string, unknown> = {}) => {
    if (!selected) return;
    const reason = window.prompt(`确认 ${action} 操作的审计原因`, `在 Skill Center 明确确认 ${action}`);
    if (!reason?.trim()) return;
    if (!window.confirm(`确认对 ${selected.name}@${selected.version} 执行 ${action}？`)) return;
    try {
      const headers = await skillCenterHeaders();
      const decision = await fetch(`${apiBaseUrl}/api/skills/lifecycle/decision`, {
        method: 'POST', headers,
        body: JSON.stringify({ action: action === 'trust' ? 'trust' : action, name: selected.name,
          version: selected.version, reason, ...extra }),
      });
      const decisionResult = await decision.json() as { decision_id?: string; detail?: string };
      if (!decision.ok || !decisionResult.decision_id) throw new Error(decisionResult.detail ?? '生命周期决策绑定失败');
      const approval = await fetch(`${apiBaseUrl}/api/skills/lifecycle/approve`, {
        method: 'POST', headers,
        body: JSON.stringify({ decision_id: decisionResult.decision_id }),
      });
      const auth = await approval.json() as { approval_token?: string; detail?: string };
      if (!approval.ok || !auth.approval_token) throw new Error(auth.detail ?? '生命周期批准失败');
      const endpoint = action === 'remove' ? 'remove' : action === 'rollback' ? 'rollback' : action === 'trust' ? 'trust' : 'pin';
      const response = await fetch(`${apiBaseUrl}/api/skills/lifecycle/${endpoint}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: selected.name, version: selected.version,
          approval_token: auth.approval_token, ...extra }),
      });
      const result = await response.json() as { detail?: string; status?: string };
      if (!response.ok) throw new Error(result.detail ?? `${action} 失败`);
      setInstallState(`生命周期操作完成：${result.status ?? action}`);
      await search();
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : `${action} 失败`); }
  };

  const updateReviewed = async (warningsConfirmed = false) => {
    if (!review || !review.existing_local || review.security.result === 'BLOCK') return;
    if (review.security.result === 'WARN' && !warningsConfirmed) { setConfirmWarnings(true); return; }
    const existing = review.existing_local as { name: string; version: string };
    const action = lifecycleUpdateAction(existing.version, review.record.version);
    const reason = window.prompt('确认更新的审计原因', `审查并批准更新到 ${review.record.version}`);
    if (!reason?.trim()) return;
    setInstalling(true);
    try {
      const headers = await skillCenterHeaders();
      const decision = await fetch(`${apiBaseUrl}/api/skills/lifecycle/decision`, {
        method: 'POST', headers,
        body: JSON.stringify({ action, name: existing.name, version: existing.version,
          acquisition_id: review.acquisition_id, reason,
          warnings_confirmed: warningsConfirmed }),
      });
      const decisionResult = await decision.json() as { decision_id?: string; detail?: string };
      if (!decision.ok || !decisionResult.decision_id) throw new Error(decisionResult.detail ?? '更新决策绑定失败');
      const approval = await fetch(`${apiBaseUrl}/api/skills/lifecycle/approve`, {
        method: 'POST', headers,
        body: JSON.stringify({ decision_id: decisionResult.decision_id }),
      });
      const auth = await approval.json() as { approval_token?: string; detail?: string };
      if (!approval.ok || !auth.approval_token) throw new Error(auth.detail ?? '更新批准失败');
      const response = await fetch(`${apiBaseUrl}/api/skills/lifecycle/update`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ acquisition_id: review.acquisition_id, version: existing.version,
          approval_token: auth.approval_token }),
      });
      const result = await response.json() as { detail?: string; version?: string };
      if (!response.ok) throw new Error(result.detail ?? '更新失败');
      setReview(null); setConfirmWarnings(false);
      setInstallState(`已更新到 ${result.version}，更新前版本已生成回滚快照。`);
      await search();
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : '更新失败'); }
    finally { setInstalling(false); }
  };

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
    if (review.existing_local
      && (review.existing_local.provenance as Record<string, unknown> | undefined)?.external_id === review.record.external_id) {
      await updateReviewed(warningsConfirmed);
      return;
    }
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

  const inspectPackage = async (file?: File) => {
    if (!file) return;
    setPackageBusy(true); setPackageReview(null); setInstallState('正在本地检查 Skill package…');
    try {
      const response = await fetch(`${apiBaseUrl}/api/skill-packages/inspect`, {
        method: 'POST', headers: { 'Content-Type': 'application/octet-stream', 'X-Atlas-Package-Name': file.name },
        body: await file.arrayBuffer(),
      });
      const data = await response.json() as LocalPackageReview & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? 'package 检查失败');
      setPackageReview(data); setInstallState('');
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : 'package 检查失败'); }
    finally { setPackageBusy(false); }
  };

  const importReviewedPackage = async () => {
    if (!packageReview || packageReview.exact_version_conflict || packageReview.security.result === 'BLOCK') return;
    setPackageBusy(true);
    try {
      const headers = await skillCenterHeaders();
      const confirmed = packageReview.security.result !== 'WARN' || confirmWarnings;
      const isUpdate = packageReview.import_state === 'update_candidate';
      const currentVersion = packageReview.existing_version;
      if (isUpdate && !currentVersion) throw new Error('已安装版本信息不可用，无法创建更新审查');
      const action = isUpdate && currentVersion
        ? lifecycleUpdateAction(currentVersion, packageReview.record.version) : 'install';
      const decision = await fetch(`${apiBaseUrl}/api/skills/lifecycle/decision`, {
        method: 'POST', headers,
        body: JSON.stringify({ action, name: packageReview.record.name,
          version: isUpdate ? currentVersion : packageReview.record.version,
          acquisition_id: packageReview.acquisition_id,
          reason: isUpdate ? '在 Skill Center 审查本地 package 更新/降级候选' : '在 Skill Center 审查本地 package 并批准导入',
          warnings_confirmed: confirmed }),
      });
      const choice = await decision.json() as { decision_id?: string; detail?: string };
      if (!decision.ok || !choice.decision_id) throw new Error(choice.detail ?? '导入决策创建失败');
      const approval = await fetch(`${apiBaseUrl}/api/skills/lifecycle/approve`, {
        method: 'POST', headers, body: JSON.stringify({ decision_id: choice.decision_id }),
      });
      const auth = await approval.json() as { approval_token?: string; detail?: string };
      if (!approval.ok || !auth.approval_token) throw new Error(auth.detail ?? '导入审批失败');
      const response = await fetch(`${apiBaseUrl}/api/skills/lifecycle/${isUpdate ? 'update' : 'install'}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ acquisition_id: packageReview.acquisition_id,
          ...(isUpdate ? { version: currentVersion } : {}),
          approval_token: auth.approval_token, warnings_confirmed: confirmed }),
      });
      const result = await response.json() as { detail?: string; name?: string };
      if (!response.ok) throw new Error(result.detail ?? 'package 导入失败');
      setPackageReview(null); setConfirmWarnings(false);
      setInstallState(`${isUpdate ? '已更新' : '已导入'} ${result.name ?? packageReview.record.name}，lifecycle 审批已记录。`);
      await search();
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : 'package 导入失败'); }
    finally { setPackageBusy(false); }
  };

  const prepareDependencies = async () => {
    if (!selected) return;
    setDependencyPlan(null);
    try {
      const headers = await skillCenterHeaders();
      const response = await fetch(`${apiBaseUrl}/api/skills/${encodeURIComponent(selected.name)}/dependencies/prepare`, {
        method: 'POST', headers, body: JSON.stringify({}),
      });
      const data = await response.json() as Record<string, unknown> & { detail?: string };
      if (!response.ok) throw new Error(data.detail ?? '依赖准备计划失败');
      setDependencyPlan(data);
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : '依赖准备计划失败'); }
  };

  const approveDependencyPlan = async () => {
    if (!selected || !dependencyPlan) return;
    try {
      const headers = await skillCenterHeaders();
      const decision = await fetch(`${apiBaseUrl}/api/skills/lifecycle/decision`, {
        method: 'POST', headers,
        body: JSON.stringify({ action: 'dependency-install', name: selected.name,
          version: selected.version, dependency_plan_id: dependencyPlan.plan_id,
          reason: '在 Skill Center 审查并批准依赖准备计划' }),
      });
      const choice = await decision.json() as { decision_id?: string; detail?: string };
      if (!decision.ok || !choice.decision_id) throw new Error(choice.detail ?? '依赖决策创建失败');
      const approval = await fetch(`${apiBaseUrl}/api/skills/lifecycle/approve`, {
        method: 'POST', headers, body: JSON.stringify({ decision_id: choice.decision_id }),
      });
      const auth = await approval.json() as { approval_token?: string; detail?: string };
      if (!approval.ok || !auth.approval_token) throw new Error(auth.detail ?? '依赖审批失败');
      const response = await fetch(`${apiBaseUrl}/api/skills/dependencies/install`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dependency_plan_id: dependencyPlan.plan_id, approval_token: auth.approval_token }),
      });
      const result = await response.json() as { detail?: string; status?: string; results?: { name: string; status: string }[] };
      if (!response.ok) throw new Error(result.detail ?? '依赖安装失败');
      setInstallState(`依赖处理结果：${result.results?.map((item) => `${item.name} ${item.status}`).join('，') ?? result.status}`);
      setDependencyPlan(null);
      const refreshed = await fetch(`${apiBaseUrl}/api/skills/${encodeURIComponent(selected.name)}/dependencies`);
      if (refreshed.ok) setDependencies(((await refreshed.json()) as { dependencies: Dependency[] }).dependencies);
    } catch (cause) { setInstallState(cause instanceof Error ? cause.message : '依赖安装失败'); }
  };

  return <section className={styles.skillCenter} aria-label="技能发现">
    <header className={styles.skillCenterHeader}><div><span>Skill Catalog</span><h1>技能发现</h1><p>本地搜索保持离线可用。远程技能需审查并明确批准后才会安装。</p></div></header>
    <fieldset className={styles.skillGithubSource}><legend>导入本地 Skill package</legend><label>受控 ZIP package<input aria-label="导入 Skill package" type="file" accept=".zip,application/zip" disabled={packageBusy} onChange={(event) => void inspectPackage(event.target.files?.[0])} /></label><p>导入前校验清单、路径、符号链接、哈希与安全扫描；安装经过现有 lifecycle 审批。</p></fieldset>
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
        <div className={styles.skillDetailSection} aria-label="依赖预检">
          <strong>依赖预检</strong>
          {!dependenciesReady && <p role={dependencyLoadError ? 'alert' : 'status'}>
            {dependencyLoadError ? '依赖预检读取失败，暂不允许激活。' : '正在读取依赖状态…'}
          </p>}
          {dependenciesReady && (dependencies.length ? <ul>{dependencies.map((item) => <li key={`${item.kind}:${item.name}`}>
            <strong>{item.kind}: {item.name}</strong> · {item.state}{item.requested ? ` · ${item.requested}` : ''}
            <small> · {item.source}{item.blocking_reason ? ` · ${item.blocking_reason}` : ''}</small>
          </li>)}</ul> : <p>无声明依赖。</p>)}
          {dependenciesReady && dependencies.some((item) => item.state !== 'satisfied') &&
            <button type="button" onClick={() => void prepareDependencies()}>生成依赖准备计划</button>}
          {dependencyPlan && <div role="dialog" aria-label="依赖准备计划">
            <h3>依赖准备计划</h3><pre>{JSON.stringify(dependencyPlan.items, null, 2)}</pre>
            <p>仅受支持的 Python package adapter 会执行，其他依赖保持阻塞。执行需要 Skill Center lifecycle 审批。</p>
            <button type="button" onClick={() => setDependencyPlan(null)}>取消</button>
            <button type="button" onClick={() => void approveDependencyPlan()}>审查并批准计划</button>
          </div>}
        </div>
        {lifecycle && <div className={styles.skillDetailSection} aria-label="生命周期状态">
          <strong>生命周期 / Trust / Pin</strong>
          <p>状态：{lifecycle.lifecycle.state} · Trust：{lifecycle.lifecycle.trust_state} · Pin：{lifecycle.lifecycle.pin_policy}</p>
          <p>记录哈希：{lifecycle.lifecycle.content_hash ?? '未知'} · 实际哈希：{lifecycle.lifecycle.actual_hash ?? '不可读取'}</p>
          {lifecycle.lifecycle.drifted && <p role="alert">检测到文件漂移；更新、回滚和移除已阻止。</p>}
          <p>来源：{String(lifecycle.provenance.source_url ?? lifecycle.provenance.provider ?? '本地来源')}</p>
          <p>依赖状态：{lifecycle.dependency_state.map((item) => `${item.name}: ${item.state}`).join(' · ') || '无声明依赖'}</p>
          <div>
            {lifecycle.lifecycle.trust_state === 'unreviewed' && <button type="button" onClick={() => void lifecycleAction('trust', { trust_state: 'trusted' })}>审查并信任</button>}
            {lifecycle.lifecycle.trust_state === 'trusted' && <button type="button" onClick={() => void lifecycleAction('trust', { trust_state: 'revoked' })}>撤销信任</button>}
            {lifecycle.lifecycle.pin_policy === 'unpinned' ? <><button type="button" onClick={() => void lifecycleAction('pin', { policy: 'exact' })}>固定版本</button><button type="button" onClick={() => void lifecycleAction('pin', { policy: 'hash' })}>固定哈希</button></> : <button type="button" onClick={() => void lifecycleAction('unpin', { policy: 'unpinned' })}>解除固定</button>}
            <button type="button" disabled={lifecycle.lifecycle.drifted} onClick={() => void lifecycleAction('remove')}>移除 Skill</button>
          </div>
          <strong>生命周期历史</strong>
          <ul>{lifecycle.history.map((event) => <li key={event.event_id}>{event.timestamp} · {event.action} · {event.skill_version} · {event.result}{Boolean(event.details?.snapshot) && <button type="button" onClick={() => void lifecycleAction('rollback', { event_id: event.event_id })}>回滚到 {String(event.details?.snapshot_version ?? event.skill_version)} ({String(event.details?.snapshot_hash ?? '').slice(0, 12)})</button>}</li>)}</ul>
        </div>}
        {dependenciesReady && dependencies.some((item) => item.state !== 'satisfied') && <p role="alert">依赖状态包含阻塞项；缺失、不兼容或未知的依赖必须先解决，技能不会启动。</p>}
        {canActivateLocalSkill(selected, lifecycle?.lifecycle) && <button className={styles.skillActivateButton} disabled={!dependenciesReady || dependencies.some((item) => item.state !== 'satisfied')} onClick={() => void activate(selected)}><WandSparkles size={15} />打开本地技能</button>}
        {activation && <pre className={styles.skillActivationContent} role="status">{activation}</pre>}
      </article>}
    </div>
    {installState && <div role="status">{installState}</div>}
    {review?.existing_local && (review.existing_local.provenance as Record<string, unknown> | undefined)?.external_id === review.record.external_id && <section role="dialog" aria-modal="true" aria-label="更新审查">
      <h2>更新审查：{review.record.name}</h2>
      <p>当前版本 {String(review.existing_local.version)} · 当前哈希 {String((review.existing_local.provenance as Record<string, unknown> | undefined)?.computed_sha256 ?? '未知')}</p>
      <p>候选版本 {review.record.version} · 候选来源 {review.record.source_url} · 候选哈希 {review.computed_sha256}</p>
      <p>依赖状态：{review.dependency_state?.map((item) => `${item.name}: ${item.state}`).join(' · ') || '无声明依赖'} · 风险：{review.security.risks.join(', ') || '未发现已知风险模式'}</p>
      <p>文件变化：新增 {review.file_diff?.added.join(', ') || '无'} · 修改 {review.file_diff?.changed.join(', ') || '无'} · 移除 {review.file_diff?.removed.join(', ') || '无'}</p>
      <button type="button" disabled={installing || review.security.result === 'BLOCK'} onClick={() => void updateReviewed()}>{review.security.result === 'BLOCK' ? '已阻止更新' : '我已审查并批准更新'}</button>
      {review.security.result === 'WARN' && <button type="button" disabled={installing} onClick={() => void updateReviewed(true)}>二次确认风险并更新</button>}
      <button type="button" onClick={() => setReview(null)}>取消更新</button>
    </section>}
    {review && <section role="dialog" aria-modal="true" aria-label="安装前安全审查"><h2>安装前审查：{review.record.name}</h2><p>版本 {review.record.version} · {review.record.provider} · {review.record.source_url}</p><p>{review.record.description}</p>{review.record.integrity_diagnostic?.message && <p role="alert">完整性诊断：{review.record.integrity_diagnostic.message}{review.record.integrity_diagnostic.github_source_revision ? ` GitHub revision ${review.record.integrity_diagnostic.github_source_revision}.` : ''}{review.record.integrity_diagnostic.github_tree_sha ? ` Tree ${review.record.integrity_diagnostic.github_tree_sha}.` : ''}{review.record.integrity_diagnostic.github_source_error ? ` ${review.record.integrity_diagnostic.github_source_error}` : ''}</p>}<p>Provider 参考哈希：{review.record.provider_integrity?.provider_computed_hash ?? review.record.integrity_diagnostic?.provider_computed_hash ?? review.record.provider_computed_hash ?? '不可用'}</p><p>安全检查：{review.security.result} · {review.security.risks.join(', ') || '未发现已知风险模式'}</p><p>{review.security.note}</p><p>审计：{JSON.stringify(review.record.audit ?? '无可用审计')}</p><p>远程哈希：{review.record.remote_hash ?? '未提供'}</p><p>本地 SHA-256：{review.computed_sha256}</p><p>验证：{review.validation.result} · 声明依赖：{formatCanonicalDependencies(review.validation.dependencies) || '无'}</p><p>已安装：{review.already_installed ? '是' : '否'} · 目标：{review.install_target}</p>{review.already_installed && <section aria-label="已安装版本冲突"><h3>本地版本与来源</h3><pre>{JSON.stringify({ existing: review.existing_local, incoming: { source: review.record.source_url, hash: review.computed_sha256 } }, null, 2)}</pre></section>}<h3>文件树与内容预览</h3><ul>{Object.keys(review.files).map((file) => <li key={file}>{file}</li>)}</ul>{Object.entries(review.files).map(([file, content]) => <details key={file}><summary>{file}</summary><pre>{content}</pre></details>)}<button type="button" onClick={() => { setReview(null); setConfirmWarnings(false); }}>取消</button><button type="button" disabled={installing || review.security.result === 'BLOCK' || review.already_installed} onClick={() => void installReviewed()}>{review.security.result === 'BLOCK' ? '已阻止安装' : '我已审查并批准安装'}</button></section>}
    {confirmWarnings && review && <section role="dialog" aria-modal="true" aria-label="确认风险后安装"><h2>此 Skill 包含风险提示</h2><p>{review.security.risks.join('、')}</p><p>风险扫描只提供证据，不能证明内容绝对安全。确认后将安装到 {review.install_target}。</p><button type="button" onClick={() => setConfirmWarnings(false)}>返回审查</button><button type="button" disabled={installing} onClick={() => void installReviewed(true)}>我理解风险，仍然安装</button></section>}
    {packageReview && <section role="dialog" aria-modal="true" aria-label="本地 Skill package 审查"><h2>本地 package 审查：{packageReview.record.name}</h2><p>版本 {packageReview.record.version} · 来源 {packageReview.record.source_url}</p><p>{packageReview.record.description}</p><p>内容 SHA-256：{packageReview.computed_sha256}</p><p>安全检查：{packageReview.security.result} · {packageReview.security.risks.join(', ') || '无已知风险'}</p><p>{packageReview.security.note}</p><p>依赖：{packageReview.dependency_state.map((item) => `${item.kind}:${item.name} ${item.state}`).join(' · ') || '无'}</p><pre>{Object.keys(packageReview.files).join('\n')}</pre>{packageReview.import_state !== 'new_skill' && <p role={packageReview.exact_version_conflict ? 'alert' : 'status'}>{packageReview.import_state === 'update_candidate' ? `当前 ${packageReview.record.name}@${packageReview.existing_version} → 候选 ${packageReview.record.version}。` : ''}{localPackageReviewState(packageReview.import_state).message}</p>}{packageReview.security.result === 'WARN' && <label><input type="checkbox" checked={confirmWarnings} onChange={(event) => setConfirmWarnings(event.target.checked)} />我已审查并理解风险</label>}<button type="button" onClick={() => setPackageReview(null)}>取消</button><button type="button" disabled={packageBusy || !localPackageReviewState(packageReview.import_state).canProceed || packageReview.security.result === 'BLOCK' || (packageReview.security.result === 'WARN' && !confirmWarnings)} onClick={() => void importReviewedPackage()}>{localPackageReviewState(packageReview.import_state).action}</button></section>}
  </section>;
}
