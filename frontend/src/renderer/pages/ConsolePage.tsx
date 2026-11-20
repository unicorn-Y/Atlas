import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { LoaderCircle, RefreshCw } from 'lucide-react';
import styles from '../App.module.css';

interface Project {
  project_id: string;
  name: string;
  workspace_path: string;
  status: string;
  current_goal: string;
  current_state: string;
}

interface RecallHit {
  conversation_title: string;
  snippet: string;
  created_at: string;
}

export function ProjectsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recall, setRecall] = useState<Record<string, RecallHit[]>>({});
  const [recallQuery, setRecallQuery] = useState<Record<string, string>>({});
  const [form, setForm] = useState({ name: '', workspace_path: '', current_goal: '' });

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/projects`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setProjects((await response.json()).projects);
      setError(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim()) return;
    setBusy(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/projects`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      setForm({ name: '', workspace_path: '', current_goal: '' });
      await refresh();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  const doRecall = async (projectId: string) => {
    const query = recallQuery[projectId]?.trim();
    if (!query) return;
    const response = await fetch(`${apiBaseUrl}/api/projects/${projectId}/recall?query=${encodeURIComponent(query)}`);
    if (response.ok) {
      const body = await response.json();
      setRecall((prev) => ({ ...prev, [projectId]: body.results }));
    }
  };

  return <section className={styles.settingsCard} aria-label="项目管理">
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <h2>项目</h2>
      <button className={styles.quietButton} onClick={() => void refresh()} disabled={busy}>
        <RefreshCw size={14} /> 刷新
      </button>
    </header>
    {error && <p role="alert">{error}</p>}
    <form className={styles.settingsForm} onSubmit={(event) => void create(event)}>
      <input placeholder="项目名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      <input placeholder="工作区路径（可选）" value={form.workspace_path} onChange={(e) => setForm({ ...form, workspace_path: e.target.value })} />
      <input placeholder="当前目标（可选）" value={form.current_goal} onChange={(e) => setForm({ ...form, current_goal: e.target.value })} />
      <button className={styles.settingsAction} disabled={busy || !form.name.trim()}>创建项目</button>
    </form>
    {projects.length === 0 && !busy && <p>还没有项目。创建一个，挂在项目下的对话会自动获得项目上下文。</p>}
    <ul style={{ listStyle: 'none', padding: 0, display: 'grid', gap: 12 }}>
      {projects.map((project) => (
        <li key={project.project_id} style={{ border: '1px solid #e8e2d9', borderRadius: 10, padding: 12 }}>
          <strong>{project.name}</strong> <small>({project.status})</small>
          {project.current_goal && <div>目标：{project.current_goal}</div>}
          {project.current_state && <div>状态：{project.current_state}</div>}
          {project.workspace_path && <div><small>{project.workspace_path}</small></div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input
              style={{ flex: 1 }}
              placeholder="在这个项目的历史会话里找…"
              value={recallQuery[project.project_id] ?? ''}
              onChange={(e) => setRecallQuery({ ...recallQuery, [project.project_id]: e.target.value })}
            />
            <button className={styles.quietButton} onClick={() => void doRecall(project.project_id)}>召回</button>
            <button
              className={styles.quietButton}
              onClick={async () => { await fetch(`${apiBaseUrl}/api/projects/${project.project_id}`, { method: 'DELETE' }); await refresh(); }}
            >删除</button>
          </div>
          {(recall[project.project_id] ?? []).map((hit, index) => (
            <div key={index} style={{ marginTop: 6, fontSize: 13, color: '#6b6257' }}>
              「{hit.conversation_title}」{hit.snippet.slice(0, 140)}
            </div>
          ))}
        </li>
      ))}
    </ul>
  </section>;
}

interface HubTask {
  id: string;
  name: string;
  action: string;
  trigger_type: string;
  trigger_args: Record<string, unknown>;
  run_count: number;
}

function HubPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [status, setStatus] = useState<{ running?: boolean; scheduler_running?: boolean; task_count?: number } | null>(null);
  const [tasks, setTasks] = useState<HubTask[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ id: '', name: '', message: '', hours: '24' });

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const statusResponse = await fetch(`${apiBaseUrl}/api/hub/status`);
      setStatus(statusResponse.ok ? await statusResponse.json() : { running: false });
      if (statusResponse.ok) {
        const tasksResponse = await fetch(`${apiBaseUrl}/api/hub/tasks`);
        if (tasksResponse.ok) setTasks((await tasksResponse.json()).tasks);
      }
      setError(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const act = async (input: RequestInfo, init?: RequestInit) => {
    setBusy(true);
    try {
      const response = await fetch(input, init);
      if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);
      await refresh();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    await act(`${apiBaseUrl}/api/hub/tasks`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: form.id.trim(), name: form.name.trim() || form.id.trim(),
        message: form.message, trigger_type: 'interval',
        trigger_args: { hours: Number(form.hours) || 24 },
      }),
    });
    setForm({ id: '', name: '', message: '', hours: '24' });
  };

  return <section className={styles.settingsCard} aria-label="后台 Hub">
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <h2>后台 Hub</h2>
      <div style={{ display: 'flex', gap: 8 }}>
        <button className={styles.quietButton} onClick={() => void act(`${apiBaseUrl}/api/hub/start`, { method: 'POST' })} disabled={busy}>启动</button>
        <button className={styles.quietButton} onClick={() => void act(`${apiBaseUrl}/api/hub/stop`, { method: 'POST' })} disabled={busy}>停止</button>
        <button className={styles.quietButton} onClick={() => void refresh()} disabled={busy}><RefreshCw size={14} /> 刷新</button>
      </div>
    </header>
    {error && <p role="alert">{error}</p>}
    <p>
      {status === null ? '检查中…' : status.running
        ? `运行中 · 调度器${status.scheduler_running ? '已启动' : '未启动'} · ${status.task_count ?? 0} 个任务`
        : '未运行（关闭桌面后后台任务也需要 Hub 才能继续）'}
    </p>
    <form className={styles.settingsForm} onSubmit={(event) => void create(event)}>
      <input placeholder="任务 id（英文）" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} />
      <input placeholder="显示名称" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      <input placeholder="要 Agent 做的事（如：总结今天的提交）" value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
      <input placeholder="间隔（小时）" value={form.hours} onChange={(e) => setForm({ ...form, hours: e.target.value })} style={{ maxWidth: 110 }} />
      <button className={styles.settingsAction} disabled={busy || !form.id.trim() || !form.message.trim()}>添加后台任务</button>
    </form>
    <ul style={{ listStyle: 'none', padding: 0 }}>
      {tasks.map((task) => (
        <li key={task.id} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0' }}>
          <span style={{ flex: 1 }}>{task.name} <small>({task.trigger_type} · 已跑 {task.run_count} 次)</small></span>
          <button className={styles.quietButton} onClick={() => void act(`${apiBaseUrl}/api/hub/tasks/${task.id}/run`, { method: 'POST' })} disabled={busy}>立即运行</button>
          <button className={styles.quietButton} onClick={() => void act(`${apiBaseUrl}/api/hub/tasks/${task.id}`, { method: 'DELETE' })} disabled={busy}>删除</button>
        </li>
      ))}
    </ul>
  </section>;
}

// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/settings/PluginsSection.tsx (Apache-2.0)
// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/settings/PluginStoreListView.tsx (Apache-2.0)
// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/settings/PluginStoreDetailView.tsx (Apache-2.0)
// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/settings/PluginStoreSourcesDialog.tsx (Apache-2.0)
interface Plugin {
  name: string;
  display_name?: string;
  version: string;
  description?: string;
  author?: string | Record<string, unknown>;
  homepage?: string;
  repository?: string;
  license?: string;
  keywords?: string[];
  metadata?: Record<string, unknown>;
  manifest?: string | null;
  path?: string;
  source?: string;
  marketplace?: string | null;
  enabled: boolean;
  loaded: boolean;
  update_available?: boolean;
  update_error?: string;
  skills?: string[];
  commands?: string[];
  agents?: string[];
  hooks?: number;
  mcp_servers?: string[];
  compatibility?: PluginCompatibility | null;
  capability_groups?: PluginCapabilityGroup[];
}

interface PluginCompatibility {
  name: string;
  version: string;
  runtime_version: string;
  peers: Record<string, string>;
  exempted: boolean;
}

interface PluginCapabilityItem {
  kind: string;
  name: string;
  description: string;
  source: string;
  source_type: string;
  loaded: boolean;
  execution: 'runtime' | 'metadata-only';
  requested_tools: string[];
  network_access: string;
  approval: string;
}

interface PluginCapabilityGroup {
  kind: string;
  label: string;
  count: number;
  items: PluginCapabilityItem[];
}

interface PluginMarketplace {
  name?: string;
  type?: string;
  source?: string;
  path?: string;
}

interface MarketplacePluginEntry {
  name?: string;
  displayName?: string;
  description?: string;
  version?: string;
  author?: string | Record<string, unknown>;
  category?: string;
  keywords?: string[];
  source?: string | Record<string, unknown>;
  homepage?: string;
  repository?: string;
  license?: string;
}

interface ReloadReport { loaded?: string[]; skipped?: Array<{ name?: string; reason?: string }>; errors?: Record<string, string> }
interface PluginValidation {
  valid: boolean; source: string; plugin?: { name?: string; version?: string; commands?: string[]; mcp_servers?: string[] } | null;
  diagnostics: Array<{ severity: 'error' | 'warning'; code: string; message: string; path?: string }>;
  summary: { errors: number; warnings: number }; policy?: { status: string; message?: string };
}

/** One line of plain Chinese about what a plugin reload did. */
const reportText = (report: ReloadReport | undefined) => {
  if (!report) return null;
  const parts: string[] = [];
  const loaded = report.loaded?.length ?? 0;
  const skipped = report.skipped?.length ?? 0;
  if (loaded) parts.push(`重新加载了 ${loaded} 个插件`);
  if (skipped) parts.push(`${skipped} 个没有加载`);
  const errors = Object.entries(report.errors ?? {});
  if (errors.length) parts.push(`出问题：${errors.map(([name, detail]) => `${name}（${detail}）`).join('、')}`);
  return parts.length ? parts.join('；') : null;
};

const SOURCE_LABEL: Record<string, string> = { local: '本地', git: 'git', marketplace: '市场', builtin: '内置' };

export function PluginsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [marketplaces, setMarketplaces] = useState<PluginMarketplace[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [marketplaceError, setMarketplaceError] = useState<string | null>(null);
  const [marketplaceStatuses, setMarketplaceStatuses] = useState<Record<string, string>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [source, setSource] = useState('');
  const [sourceRef, setSourceRef] = useState('');
  const [marketSource, setMarketSource] = useState('');
  const [marketSourceRef, setMarketSourceRef] = useState('');
  const [pluginQuery, setPluginQuery] = useState('');
  const [pluginStatus, setPluginStatus] = useState<'all' | 'enabled' | 'disabled' | 'updates' | 'loaded'>('all');
  const [marketplaceQuery, setMarketplaceQuery] = useState('');
  const [marketPluginQuery, setMarketPluginQuery] = useState('');
  const [confirmRemove, setConfirmRemove] = useState('');
  const [browsing, setBrowsing] = useState<{ name: string; entries: MarketplacePluginEntry[] } | null>(null);
  const [pluginValidation, setPluginValidation] = useState<{ result: PluginValidation; action: 'install' | 'enable'; pluginName?: string } | null>(null);
  const [compatibilityRisk, setCompatibilityRisk] = useState<Record<string, boolean>>({});
  const [installRequestId, setInstallRequestId] = useState<string | null>(() => {
    try { return localStorage.getItem('atlas.plugin.install.requestId'); } catch { return null; }
  });
  const [installOperation, setInstallOperation] = useState<{
    requestId: string; status: string; approvalRequired?: string[]; error?: string;
  } | null>(null);
  const [installStartPending, setInstallStartPending] = useState(false);

  const authorText = (author: Plugin['author']): string => {
    if (typeof author === 'string') return author;
    if (!author || typeof author !== 'object') return '';
    const name = author.name;
    return typeof name === 'string' ? name : JSON.stringify(author) ?? '[作者信息]';
  };
  const valueText = (value: unknown): string => {
    if (typeof value === 'string') return value;
    if (value === undefined || value === null) return '';
    return JSON.stringify(value) ?? String(value);
  };
  const safeExternalUrl = (value?: string): string | null => {
    if (!value) return null;
    try {
      const url = new URL(value);
      return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null;
    } catch {
      return null;
    }
  };

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const [pluginsResponse, marketResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/api/plugins`),
        fetch(`${apiBaseUrl}/api/plugin-marketplaces`).catch(() => null),
      ]);
      if (!pluginsResponse.ok) throw new Error(`HTTP ${pluginsResponse.status}`);
      const pluginBody = await pluginsResponse.json();
      setPlugins(Array.isArray(pluginBody.plugins) ? pluginBody.plugins : []);
      if (marketResponse?.ok) {
        const marketBody = await marketResponse.json();
        setMarketplaces(Array.isArray(marketBody.marketplaces) ? marketBody.marketplaces : []);
        setMarketplaceError(null);
      } else {
        setMarketplaceError(marketResponse ? `HTTP ${marketResponse.status}` : '无法连接插件市场接口');
      }
      setError(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  /** Shared wrapper for every button action; shows the reload report in plain Chinese. */
  const act = async (input: RequestInfo, init?: RequestInit, done?: string | ((body: Record<string, unknown>) => string)): Promise<boolean> => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(input, init);
      if (!response.ok) throw new Error(await response.json().then((body) => body?.detail).catch(() => `HTTP ${response.status}`));
      const body = await response.json().catch(() => ({})) as Record<string, unknown>;
      const detail = reportText(body.report as ReloadReport | undefined);
      const doneMessage = typeof done === 'function' ? done(body) : done;
      setNotice([doneMessage, detail].filter(Boolean).join('。') || '已完成');
      setConfirmRemove('');
      await refresh();
      return true;
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
      return false;
    } finally {
      setBusy(false);
    }
  };
  const post = (path: string, body?: unknown, done?: string | ((body: Record<string, unknown>) => string)) => act(`${apiBaseUrl}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }, done);
  useEffect(() => {
    if (!installRequestId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const response = await fetch(`${apiBaseUrl}/api/plugins/install/${encodeURIComponent(installRequestId)}?wait_ms=1000`);
        if (!response.ok) throw new Error(`安装状态查询失败（HTTP ${response.status}）`);
        const body = await response.json() as { requestId: string; status: string; approvalRequired?: string[]; error?: string };
        if (!active) return;
        if (body.status === 'unknown' && installStartPending) {
          timer = setTimeout(() => { void poll(); }, 250);
          return;
        }
        setInstallOperation(body);
        if (['completed', 'failed', 'cancelled', 'unknown', 'too_late'].includes(body.status)) {
          try {
            localStorage.removeItem('atlas.plugin.install.requestId');
            localStorage.removeItem('atlas.plugin.install.pending');
          } catch { /* local storage may be unavailable */ }
          if (body.status === 'completed') {
            setNotice(`插件安装完成 · ${body.requestId}`);
            await refresh();
          } else if (body.status === 'failed') setError(`插件安装失败：${body.error ?? '未知错误'}`);
          else if (body.status === 'unknown') setNotice('找不到该安装任务；没有将未知状态视为成功');
          else if (body.status === 'cancelled') setNotice('安装已取消，暂存目录已清理');
          setInstallRequestId(null);
          return;
        }
        timer = setTimeout(() => { void poll(); }, 500);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : String(cause));
        timer = setTimeout(() => { void poll(); }, 1500);
      }
    };
    void poll();
    return () => { active = false; if (timer) clearTimeout(timer); };
  }, [apiBaseUrl, installRequestId, installStartPending, refresh]);

  const validatePluginSource = async (target: string, action: 'install' | 'enable', pluginName?: string) => {
    setBusy(true); setError(null); setPluginValidation(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/plugins/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: target }) });
      const result = await response.json() as PluginValidation;
      if (!response.ok) throw new Error(typeof (result as unknown as { detail?: unknown }).detail === 'string' ? String((result as unknown as { detail: string }).detail) : `校验失败（HTTP ${response.status}）`);
      setPluginValidation({ result, action, pluginName });
    } catch (cause) { setError(`插件校验请求失败：${cause instanceof Error ? cause.message : String(cause)}`); }
    finally { setBusy(false); }
  };
  const startPluginInstall = async (sourceValue: string, refValue?: string, sourceType?: 'local' | 'npm' | 'git' | 'marketplace', marketplace?: string, pluginName?: string) => {
    setBusy(true); setError(null); setNotice(null);
    const requestId = crypto.randomUUID();
    try {
      localStorage.setItem('atlas.plugin.install.requestId', requestId);
      localStorage.setItem('atlas.plugin.install.pending', JSON.stringify({ requestId, source: sourceValue, ref: refValue, sourceType, marketplace, plugin: pluginName }));
    } catch { /* continue with the in-memory request ID */ }
    setInstallOperation({ requestId, status: 'queued' });
    setInstallStartPending(true);
    setInstallRequestId(requestId);
    try {
      const endpoint = marketplace
        ? `${apiBaseUrl}/api/plugin-marketplaces/${encodeURIComponent(marketplace)}/install`
        : `${apiBaseUrl}/api/plugins/install`;
      const requestBody = marketplace ? { plugin: pluginName, requestId } : { source: sourceValue, ref: refValue, sourceType, requestId };
      const response = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      const body = await response.json() as { requestId?: string; status?: string; detail?: unknown };
      if (!response.ok || !body.requestId) throw new Error(typeof body.detail === 'string' ? body.detail : `无法启动安装任务（HTTP ${response.status}）`);
      setInstallStartPending(false);
      setInstallOperation({ requestId: body.requestId, status: body.status ?? 'queued' });
      if (!marketplace) { setSource(''); setSourceRef(''); setPluginValidation(null); }
      setNotice(`安装任务已启动 · ${body.requestId}`);
    } catch (cause) {
      setInstallStartPending(false);
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(false); }
  };
  const installValidatedPlugin = async () => {
    if (!pluginValidation?.result.valid || pluginValidation.action !== 'install') return;
    await startPluginInstall(source.trim(), sourceRef.trim() || undefined, 'local');
  };
  const installSourceType = (value: string): 'npm' | 'git' | null => {
    const text = value.trim();
    if (text.startsWith('npm:') || /^@[a-z0-9._-]+\/[a-z0-9._-]+(?:@[^\s]+)?$/i.test(text) || /^[a-z0-9._-]+(?:@[^\s]+)?$/i.test(text)) return 'npm';
    if (/^(https?:\/\/|ssh:\/\/|git\+|git@)/i.test(text) || /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(text)) return 'git';
    return null;
  };
  const cancelInstall = async () => {
    if (!installRequestId) return;
    const response = await fetch(`${apiBaseUrl}/api/plugins/install/${encodeURIComponent(installRequestId)}/cancel`, { method: 'POST' });
    const body = await response.json() as { status?: string };
    if (!response.ok) { setError(`取消请求失败（HTTP ${response.status}）`); return; }
    setNotice(body.status === 'too_late' ? '安装已进入不可取消阶段' : body.status === 'cancelled' ? '安装已取消并清理' : '正在结束安装进程并清理暂存文件…');
  };
  const approveInstallScript = async (packageName: string) => {
    const response = await fetch(`${apiBaseUrl}/api/plugins/script-approvals`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ packageName, days: 30, requestId: installRequestId }),
    });
    if (!response.ok) { setError(`脚本审批失败（HTTP ${response.status}）`); return; }
    setNotice(`已允许 ${packageName} 执行构建脚本，授权 30 天`);
  };
  const enableValidatedPlugin = async () => {
    if (!pluginValidation?.result.valid || pluginValidation.action !== 'enable' || !pluginValidation.pluginName) return;
    const name = pluginValidation.pluginName;
    if (await post(`/api/plugins/${encodeURIComponent(name)}/enabled`, { enabled: true }, `已启用 ${name}`)) setPluginValidation(null);
  };
  const compatibilityKey = (plugin: Plugin) => `${plugin.name}@${plugin.version}@${plugin.compatibility?.runtime_version ?? ''}`;

  const browse = async (name: string) => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/plugin-marketplaces/${encodeURIComponent(name)}/plugins`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.json();
      setBrowsing({ name, entries: body.plugins ?? [] });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const normalizedPluginQuery = pluginQuery.trim().toLocaleLowerCase();
  const visiblePlugins = plugins.filter((plugin) => {
    if (pluginStatus === 'enabled' && !plugin.enabled) return false;
    if (pluginStatus === 'disabled' && plugin.enabled) return false;
    if (pluginStatus === 'updates' && !plugin.update_available) return false;
    if (pluginStatus === 'loaded' && !plugin.loaded) return false;
    if (!normalizedPluginQuery) return true;
    const text = [
      plugin.name, plugin.display_name, plugin.description, authorText(plugin.author),
      plugin.version, plugin.source, plugin.marketplace, plugin.path, plugin.manifest,
      plugin.repository, plugin.homepage, plugin.license, ...(plugin.keywords ?? []),
      ...(plugin.skills ?? []), ...(plugin.commands ?? []), ...(plugin.agents ?? []),
      ...(plugin.mcp_servers ?? []), valueText(plugin.metadata),
    ].filter(Boolean).join(' ').toLocaleLowerCase();
    return text.includes(normalizedPluginQuery);
  });
  const visibleMarketplaces = marketplaces.filter((market) => {
    const query = marketplaceQuery.trim().toLocaleLowerCase();
    return !query || [market.name, market.source, market.path, market.type].filter(Boolean)
      .join(' ').toLocaleLowerCase().includes(query);
  });
  const visibleMarketEntries = (browsing?.entries ?? []).filter((entry) => {
    const query = marketPluginQuery.trim().toLocaleLowerCase();
    const text = [entry.name, entry.displayName, entry.description, entry.version,
      authorText(entry.author), entry.category, ...(entry.keywords ?? []),
      valueText(entry.source), entry.homepage, entry.repository, entry.license]
      .filter(Boolean).join(' ').toLocaleLowerCase();
    return !query || text.includes(query);
  });

  return <section className={styles.settingsCard} aria-label="插件管理">
    <header className={styles.settingsCardHeading}>
      <h2>插件</h2>
      <button className={styles.quietButton} onClick={() => void act(`${apiBaseUrl}/api/plugins/check-updates`, { method: 'POST' }, (body) => {
        const updates = body.updates && typeof body.updates === 'object' ? Object.values(body.updates as Record<string, unknown>).filter((value) => value === true).length : 0;
        const failed = Array.isArray(body.plugins) ? body.plugins.filter((plugin) => Boolean((plugin as Plugin)?.update_error)).length : 0;
        return failed ? `${failed} 个 Git 来源检查失败；已重试 2 次，请查看插件错误详情` : `插件更新检查完成；${updates} 个插件有更新`;
      })} disabled={busy}>检查 Git 来源更新</button>
      <button className={styles.quietButton} onClick={() => void refresh()} disabled={busy}><RefreshCw size={14} className={busy ? styles.settingsSpinner : undefined} /> 刷新</button>
    </header>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {notice && <p role="status" style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--fg-2)' }}>{notice}</p>}
    {installOperation && <section aria-label="插件安装任务" className="rounded-lg border border-[var(--line)] p-3" role="status">
      <strong>安装任务 · {installOperation.status}</strong>
      <p style={{ margin: '4px 0', fontSize: 12.5 }}>请求 ID：{installOperation.requestId}</p>
      {installStartPending && <p>正在校验来源并创建安装任务…</p>}
      {installOperation.status === 'awaiting_approval' && <div>
        <p style={{ margin: '4px 0', fontSize: 12.5 }}>pnpm 报告以下依赖的构建脚本被阻断。仅批准后才会对这些包运行 rebuild；授权有效 30 天。</p>
        <ul style={{ margin: '6px 0', paddingLeft: 20 }}>{(installOperation.approvalRequired ?? []).map((name) => <li key={name}>
          <code>{name}</code>{' '}<button className={styles.quietButton} onClick={() => void approveInstallScript(name)}>允许此包脚本（30 天）</button>
        </li>)}</ul>
      </div>}
      {installRequestId && <button className={styles.quietButton} disabled={installStartPending} onClick={() => void cancelInstall()}>取消安装</button>}
    </section>}
    <form className={styles.settingsForm} onSubmit={async (event) => {
      event.preventDefault();
      if (!source.trim()) return;
      const sourceType = installSourceType(source.trim());
      if (sourceType) await startPluginInstall(source.trim(), sourceRef.trim() || undefined, sourceType);
      else await validatePluginSource(source.trim(), 'install');
    }}>
      <label>从哪里安装
        <input aria-label="插件来源" placeholder="本地目录路径、git 地址，或 用户名/仓库" value={source} onChange={(e) => setSource(e.target.value)} />
      </label>
      <label>分支或标签（可选）
        <input aria-label="插件分支或标签" placeholder="默认使用仓库默认分支" value={sourceRef} onChange={(e) => setSourceRef(e.target.value)} />
      </label>
      <p style={{ margin: 0, fontSize: 12.5 }}>支持 Claude Code 的 .claude-plugin/plugin.json、根目录 plugin.json 插件包、git 地址或「用户名/仓库」。Codex 专属 .codex-plugin/plugin.json 回退清单尚不支持；填 marketplace 仓库会注册为插件市场。</p>
      <button className={styles.settingsAction} disabled={busy || !source.trim()}>{busy ? '正在校验…' : '校验清单'}</button>
    </form>
    {pluginValidation && <section aria-label="插件清单校验报告" className="rounded-lg border border-[var(--line)] p-3">
      <strong>{pluginValidation.result.valid ? '校验通过' : '校验未通过'} · {pluginValidation.result.plugin?.name ?? pluginValidation.result.source}</strong>
      <p style={{ margin: '4px 0', fontSize: 12.5 }}>错误 {pluginValidation.result.summary.errors} 项 · 警告 {pluginValidation.result.summary.warnings} 项</p>
      {pluginValidation.result.diagnostics.length > 0 && <ul style={{ margin: '6px 0', paddingLeft: 20, fontSize: 12.5 }}>
        {pluginValidation.result.diagnostics.map((item, index) => <li key={`${item.code}:${index}`} role={item.severity === 'error' ? 'alert' : 'status'}><b>{item.severity === 'error' ? '错误' : '建议'} · {item.code}</b>：{item.message}{item.path ? ` (${item.path})` : ''}</li>)}
      </ul>}
      {pluginValidation.result.policy?.message && <p style={{ margin: '4px 0', fontSize: 12, color: 'var(--fg-3)' }}>{pluginValidation.result.policy.message}</p>}
      <div style={{ display: 'flex', gap: 8 }}>
        {pluginValidation.result.valid && pluginValidation.action === 'install' && <button className={styles.settingsAction} disabled={busy} onClick={() => void installValidatedPlugin()}>校验通过，继续安装</button>}
        {pluginValidation.result.valid && pluginValidation.action === 'enable' && <button className={styles.settingsAction} disabled={busy} onClick={() => void enableValidatedPlugin()}>校验通过，确认启用</button>}
        <button className={styles.quietButton} onClick={() => setPluginValidation(null)}>关闭报告</button>
      </div>
    </section>}
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'end', margin: '10px 0' }}>
      <label style={{ flex: '1 1 220px' }}>搜索插件
        <input aria-label="搜索已安装插件" placeholder="名称、说明、作者、来源或组件" value={pluginQuery} onChange={(e) => setPluginQuery(e.target.value)} />
      </label>
      <label>状态
        <select aria-label="按插件状态筛选" value={pluginStatus} onChange={(e) => setPluginStatus(e.target.value as typeof pluginStatus)}>
          <option value="all">全部（{plugins.length}）</option>
          <option value="enabled">已启用</option>
          <option value="disabled">已停用</option>
          <option value="updates">有更新</option>
          <option value="loaded">已加载</option>
        </select>
      </label>
    </div>
    {plugins.length === 0 && !busy && <p>还没有插件。可安装插件目录或 git 来源，也可以从已添加的市场安装。</p>}
    {plugins.length > 0 && visiblePlugins.length === 0 && <p>没有符合当前搜索和状态筛选的插件。</p>}
    <ul>
      {visiblePlugins.map((plugin) => (
        <li key={plugin.name}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ flex: '1 1 240px', minWidth: 0 }}>
              <strong>{plugin.display_name || plugin.name}</strong> <small>v{plugin.version} · {SOURCE_LABEL[plugin.source ?? ''] ?? plugin.source ?? '本地'}{plugin.marketplace ? ` · ${plugin.marketplace}` : ''} · {plugin.enabled ? '已启用' : '已停用'} · {plugin.loaded ? '已加载' : '未加载'}{plugin.update_available ? ' · 有更新' : ''}</small>
              {plugin.description && <div><small>{plugin.description}</small></div>}
              {plugin.compatibility && <div role={plugin.compatibility.exempted ? 'status' : 'alert'} style={{ marginTop: 6, color: plugin.compatibility.exempted ? 'var(--warning)' : 'var(--danger)' }}>
                <small>Atlas {plugin.compatibility.runtime_version} 与此插件声明的 peer 范围不兼容：{Object.entries(plugin.compatibility.peers).map(([peer, range]) => `${peer} ${range}`).join('，')}。豁免只适用于 {plugin.name}@{plugin.version} 和此 Atlas 版本。</small>
                {plugin.compatibility.exempted
                  ? <button className={styles.quietButton} onClick={() => void act(`${apiBaseUrl}/api/plugins/${encodeURIComponent(plugin.name)}/compatibility-exemption`, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pluginVersion: plugin.version, runtimeVersion: plugin.compatibility?.runtime_version }) }, `已撤销 ${plugin.name}@${plugin.version} 的兼容性豁免`)} disabled={busy}>撤销精确版本豁免</button>
                  : <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                    <label><input type="checkbox" checked={compatibilityRisk[compatibilityKey(plugin)] === true} onChange={(event) => setCompatibilityRisk((old) => ({ ...old, [compatibilityKey(plugin)]: event.target.checked }))} /> 我了解该插件声明的 Atlas peer 范围不匹配，并接受继续加载风险。</label>
                    <button className={styles.settingsAction} disabled={busy || compatibilityRisk[compatibilityKey(plugin)] !== true} onClick={() => void post(`/api/plugins/${encodeURIComponent(plugin.name)}/compatibility-exemption`, { pluginVersion: plugin.version, runtimeVersion: plugin.compatibility?.runtime_version, acceptRisk: true }, `已为 ${plugin.name}@${plugin.version} 明确接受风险并豁免`)}>明确接受风险并豁免</button>
                  </div>}
              </div>}
              {plugin.update_error && <div role="alert" style={{ color: 'var(--danger)' }}><small>{plugin.update_error}</small></div>}
              <div><small>技能 {plugin.skills?.length ?? 0} · 命令 {plugin.commands?.length ?? 0} · Agent {plugin.agents?.length ?? 0} · Hook {plugin.hooks ?? 0} · MCP {plugin.mcp_servers?.length ?? 0}</small></div>
            </span>
            <button className={styles.quietButton} onClick={() => plugin.enabled
              ? void post(`/api/plugins/${encodeURIComponent(plugin.name)}/enabled`, { enabled: false })
              : void validatePluginSource(plugin.path ?? '', 'enable', plugin.name)} disabled={busy}>
              {plugin.enabled ? '停用' : '启用'}
            </button>
            <button className={styles.quietButton} onClick={() => void post(`/api/plugins/${encodeURIComponent(plugin.name)}/update`)} disabled={busy}>更新</button>
            <button className={styles.quietButton} title="改了插件文件后点这里，不用重启应用"
              onClick={() => void post(`/api/plugins/${encodeURIComponent(plugin.name)}/reload`, {}, `已重载 ${plugin.name}`)} disabled={busy}>重载</button>
            <button className={styles.quietButton} style={confirmRemove === plugin.name ? { color: 'var(--danger)' } : undefined}
              onClick={() => {
                if (confirmRemove !== plugin.name) { setConfirmRemove(plugin.name); return; }
                void act(`${apiBaseUrl}/api/plugins/${encodeURIComponent(plugin.name)}`, { method: 'DELETE' }, `已卸载 ${plugin.name}`);
              }} disabled={busy}>
              {confirmRemove === plugin.name ? '确认卸载' : '卸载'}
            </button>
          </div>
          <details style={{ margin: '6px 0 0' }}>
            <summary style={{ cursor: 'pointer', fontSize: 12.5 }}>查看详情与已注册组件</summary>
            <div style={{ display: 'grid', gap: 4, padding: '8px 0 0', fontSize: 12.5 }}>
              {authorText(plugin.author) && <div>作者：{authorText(plugin.author)}</div>}
              {plugin.homepage && <div>主页：{safeExternalUrl(plugin.homepage) ? <a href={safeExternalUrl(plugin.homepage) ?? undefined} target="_blank" rel="noreferrer">{plugin.homepage}</a> : <code>{plugin.homepage}</code>}</div>}
              {plugin.repository && <div>仓库：{plugin.repository}</div>}
              {plugin.license && <div>许可证：{plugin.license}</div>}
              {plugin.path && <div>安装路径：<code>{plugin.path}</code></div>}
              {plugin.manifest && <div>清单：<code>{plugin.manifest}</code></div>}
              {plugin.keywords?.length ? <div>关键词：{plugin.keywords.join('、')}</div> : null}
              {plugin.skills?.length ? <div>技能：{plugin.skills.join('、')}</div> : null}
              {plugin.commands?.length ? <div>命令：{plugin.commands.join('、')}</div> : null}
              {plugin.agents?.length ? <div>Agent：{plugin.agents.join('、')}</div> : null}
              {plugin.mcp_servers?.length ? <div>MCP：{plugin.mcp_servers.join('、')}</div> : null}
              <section aria-label="插件能力分组" style={{ display: 'grid', gap: 10, marginTop: 8 }}>
                <strong>能力分组与风险投影</strong>
                {plugin.capability_groups?.map((group) => <section key={group.kind} aria-label={`${group.label}贡献`} style={{ borderTop: '1px solid var(--line)', paddingTop: 7 }}>
                  <div style={{ fontWeight: 600 }}>{group.label} · {group.count} 项</div>
                  {group.items.length > 0 && <ul style={{ display: 'grid', gap: 6, margin: '5px 0 0', padding: 0, listStyle: 'none' }}>
                    {group.items.map((item) => <li key={`${group.kind}:${item.name}`} style={{ borderRadius: 7, background: 'var(--surface-2, var(--surface))', padding: '6px 8px' }}>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'baseline' }}>
                        <code>{item.name}</code><small>{item.loaded ? '已加载' : '未加载'}</small>
                        {item.execution === 'metadata-only' && <small>metadata-only · 不执行</small>}
                      </div>
                      {item.description && <div style={{ marginTop: 2 }}>{item.description}</div>}
                      <div><small>来源：{item.source_type} · {item.source}</small></div>
                      <div><small>请求工具：{item.requested_tools.length ? item.requested_tools.join('、') : '未声明'}</small></div>
                      <div><small>网络能力：{item.network_access}</small></div>
                      <div><small>审批要求：{item.approval}</small></div>
                    </li>)}
                  </ul>}
                </section>)}
                {!plugin.capability_groups && <small>当前后端尚未提供能力投影。</small>}
              </section>
              {plugin.metadata && Object.keys(plugin.metadata).length > 0 && <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>插件元数据：{JSON.stringify(plugin.metadata, null, 2)}</pre>}
            </div>
          </details>
        </li>
      ))}
    </ul>

    <h2 style={{ marginTop: 18 }}>插件市场</h2>
    <p style={{ margin: '0 0 10px', fontSize: 13 }}>市场是按来源添加的一批插件目录。可浏览条目并逐个安装。</p>
    <form className={styles.settingsForm} onSubmit={async (event) => {
      event.preventDefault();
      if (!marketSource.trim()) return;
      const added = await post('/api/plugin-marketplaces', { source: marketSource.trim(), ref: marketSourceRef.trim() || undefined });
      if (added) { setMarketSource(''); setMarketSourceRef(''); setNotice('插件市场已添加'); }
    }}>
      <label>市场来源
        <input aria-label="插件市场来源" placeholder="本地路径或 git 地址（仓库里要有 marketplace.json）" value={marketSource} onChange={(e) => setMarketSource(e.target.value)} />
      </label>
      <label>分支或标签（可选）
        <input aria-label="插件市场分支或标签" placeholder="默认使用仓库默认分支" value={marketSourceRef} onChange={(e) => setMarketSourceRef(e.target.value)} />
      </label>
      <button className={styles.settingsAction} disabled={busy || !marketSource.trim()}>添加市场</button>
    </form>
    {marketplaceError && <p className={styles.settingsError} role="alert">无法读取插件市场：{marketplaceError}</p>}
    {marketplaces.length > 0 && <label style={{ display: 'block', margin: '10px 0' }}>搜索市场来源
      <input aria-label="搜索插件市场来源" placeholder="名称、类型、来源路径" value={marketplaceQuery} onChange={(e) => setMarketplaceQuery(e.target.value)} />
    </label>}
    {marketplaces.length > 0 && visibleMarketplaces.length === 0 && <p>没有符合搜索条件的市场来源。</p>}
    {visibleMarketplaces.length > 0 && <ul>
      {visibleMarketplaces.map((market) => (
        <li key={market.name ?? market.path}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ flex: 1, minWidth: 0 }}>
              <strong>{market.name ?? '未命名市场'}</strong> <small>{market.type === 'git' ? 'git' : '本地'}{market.source ? ` · ${market.source}` : ''}</small>
            </span>
            <button className={styles.quietButton} disabled={busy || !market.name}
              onClick={() => { if (browsing?.name === market.name) setBrowsing(null); else void browse(market.name ?? ''); }}>
              {browsing?.name === market.name ? '收起' : '浏览'}
            </button>
            {market.type === 'git' && <button className={styles.quietButton} disabled={busy || !market.name}
              onClick={() => {
                const name = market.name;
                if (!name) return;
                void post(`/api/plugin-marketplaces/${encodeURIComponent(name)}/update`, undefined, (body) => {
                  const status = body.updated === true ? '已更新' : '未更新';
                  setMarketplaceStatuses((current) => ({ ...current, [name]: status }));
                  return body.updated === true ? '插件市场已更新' : '插件市场无需更新';
                });
              }}>
              更新来源
            </button>}
          </div>
          <small role="status">{marketplaceStatuses[market.name ?? ''] ?? (market.type === 'git' ? 'git 来源，尚未更新' : '本地来源，无需更新')}</small>
          <details style={{ margin: '4px 0 0' }}>
            <summary style={{ cursor: 'pointer', fontSize: 12.5 }}>查看市场来源详情</summary>
            <div style={{ display: 'grid', gap: 4, padding: '6px 0', fontSize: 12.5 }}>
              {market.source && <div>来源：<code>{market.source}</code></div>}
              {market.path && <div>目录：<code>{market.path}</code></div>}
              <div>类型：{market.type === 'git' ? 'git' : '本地'}</div>
            </div>
          </details>
          {browsing && browsing.name === market.name && (browsing.entries.length ? (
            <div style={{ margin: '8px 0 0' }}>
              <label style={{ display: 'block', margin: '8px 0' }}>搜索市场插件
                <input aria-label="搜索当前市场插件" placeholder="名称、说明、作者或关键词" value={marketPluginQuery} onChange={(e) => setMarketPluginQuery(e.target.value)} />
              </label>
              {visibleMarketEntries.length === 0 ? <p>没有符合搜索条件的插件。</p> : <ul>
              {visibleMarketEntries.map((entry, index) => {
                const installed = plugins.some((plugin) => plugin.name === entry.name);
                return (
                <li key={entry.name ?? index}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                    <span style={{ flex: '1 1 240px', minWidth: 0 }}>
                      <strong>{entry.displayName ?? entry.name ?? '未命名插件'}</strong> <small>{entry.version ? `v${entry.version} · ` : ''}{installed ? '已安装' : '未安装'}</small>
                      {entry.description && <div><small>{entry.description}</small></div>}
                      {entry.category && <div><small>分类：{entry.category}</small></div>}
                    </span>
                    <button className={styles.quietButton} disabled={busy || !entry.name || installed}
                      onClick={() => market.name && entry.name && void startPluginInstall(`marketplace:${market.name}/${entry.name}`, undefined, 'marketplace', market.name, entry.name)}>
                      {installed ? '已安装' : '安装'}
                    </button>
                  </div>
                  <details style={{ margin: '4px 0 0' }}>
                    <summary style={{ cursor: 'pointer', fontSize: 12.5 }}>查看市场条目详情</summary>
                    <div style={{ display: 'grid', gap: 4, padding: '6px 0', fontSize: 12.5 }}>
                      {authorText(entry.author) && <div>作者：{authorText(entry.author)}</div>}
                      {entry.homepage && <div>主页：{safeExternalUrl(entry.homepage) ? <a href={safeExternalUrl(entry.homepage) ?? undefined} target="_blank" rel="noreferrer">{entry.homepage}</a> : <code>{entry.homepage}</code>}</div>}
                      {entry.repository && <div>仓库：{entry.repository}</div>}
                      {entry.license && <div>许可证：{entry.license}</div>}
                      {entry.keywords?.length ? <div>关键词：{entry.keywords.join('、')}</div> : null}
                      {entry.source && <div>安装来源：<code>{valueText(entry.source)}</code></div>}
                    </div>
                  </details>
                </li>
              ); })}
              </ul>}
            </div>
          ) : <small style={{ display: 'block', marginTop: 6 }}>这个市场里还没有列出插件。</small>)}
        </li>
      ))}
    </ul>}
  </section>;
}

export function NotificationsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [urls, setUrls] = useState('');
  const [status, setStatus] = useState<{ enabled?: boolean; targets?: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [statusResponse, urlsResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/api/notifications/status`),
        fetch(`${apiBaseUrl}/api/notifications/urls`),
      ]);
      if (statusResponse.ok) setStatus(await statusResponse.json());
      if (urlsResponse.ok) setUrls((await urlsResponse.json()).urls.join('\n'));
    } catch (exc) {
      setError(String(exc));
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`${apiBaseUrl}/api/notifications/urls`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ urls: urls.split('\n').map((u) => u.trim()).filter(Boolean) }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setMessage('已保存并立即生效。');
      await refresh();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="通知设置">
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <h2>任务完成通知</h2>
      <button className={styles.quietButton} onClick={async () => {
        setBusy(true);
        try {
          const response = await fetch(`${apiBaseUrl}/api/notifications/test`, { method: 'POST' });
          const result = await response.json();
          setMessage(result.enabled ? `已发送到 ${result.sent.length} 个目标` : '尚未配置任何通知目标');
        } catch (exc) {
          setError(String(exc));
        } finally {
          setBusy(false);
        }
      }} disabled={busy}>发送测试通知</button>
    </header>
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    <p>后台任务完成或失败时主动通知你。每行一个 Apprise 地址，例如 <code>windows://</code>（Windows 弹窗）或 <code>tgram://bottoken/chatid</code>。</p>
    <form className={styles.settingsForm} onSubmit={save}>
      <textarea
        rows={3}
        value={urls}
        placeholder={'windows://'}
        onChange={(e) => setUrls(e.target.value)}
        style={{ fontFamily: 'monospace' }}
      />
      <button className={styles.settingsAction} disabled={busy}>
        {busy ? <LoaderCircle size={14} className={styles.spin ?? undefined} /> : null} 保存通知目标
      </button>
      {status && <small>当前 {status.targets ?? 0} 个目标{status.enabled ? '' : '（未配置 = 静默）'}</small>}
    </form>
  </section>;
}

export default function ConsolePage({ apiBaseUrl }: { apiBaseUrl: string }) {
  return <div aria-label="控制台" style={{ display: 'grid', gap: 16 }}>
    <ProjectsPanel apiBaseUrl={apiBaseUrl} />
    <HubPanel apiBaseUrl={apiBaseUrl} />
    <PluginsPanel apiBaseUrl={apiBaseUrl} />
    <NotificationsPanel apiBaseUrl={apiBaseUrl} />
  </div>;
}
