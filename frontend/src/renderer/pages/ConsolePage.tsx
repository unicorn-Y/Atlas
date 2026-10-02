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

interface Plugin {
  name: string;
  display_name?: string;
  version: string;
  description?: string;
  source?: string;
  marketplace?: string | null;
  enabled: boolean;
  loaded: boolean;
  update_available?: boolean;
  skills?: string[];
  commands?: string[];
  agents?: string[];
  hooks?: number;
  mcp_servers?: string[];
}

interface ReloadReport { loaded?: string[]; skipped?: Array<{ name?: string; reason?: string }>; errors?: Record<string, string> }

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
  const [marketplaces, setMarketplaces] = useState<Array<{ name?: string; type?: string; source?: string; path?: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [source, setSource] = useState('');
  const [marketSource, setMarketSource] = useState('');
  const [confirmRemove, setConfirmRemove] = useState('');
  const [browsing, setBrowsing] = useState<{ name: string; entries: Array<{ name?: string; description?: string }> } | null>(null);

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const [pluginsResponse, marketResponse] = await Promise.all([
        fetch(`${apiBaseUrl}/api/plugins`),
        fetch(`${apiBaseUrl}/api/plugin-marketplaces`).catch(() => null),
      ]);
      if (!pluginsResponse.ok) throw new Error(`HTTP ${pluginsResponse.status}`);
      setPlugins((await pluginsResponse.json()).plugins);
      if (marketResponse?.ok) setMarketplaces((await marketResponse.json()).marketplaces);
      setError(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  /** Shared wrapper for every button action; shows the reload report in plain Chinese. */
  const act = async (input: RequestInfo, init?: RequestInit, done?: string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await fetch(input, init);
      if (!response.ok) throw new Error(await response.json().then((body) => body?.detail).catch(() => `HTTP ${response.status}`));
      const body = await response.json().catch(() => ({}));
      const detail = reportText(body?.report);
      setNotice([done, detail].filter(Boolean).join('。') || '已完成');
      setConfirmRemove('');
      await refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };
  const post = (path: string, body?: unknown) => act(`${apiBaseUrl}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) });

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

  return <section className={styles.settingsCard} aria-label="插件管理">
    <header className={styles.settingsCardHeading}>
      <h2>插件</h2>
      <button className={styles.quietButton} onClick={() => void refresh()} disabled={busy}><RefreshCw size={14} className={busy ? styles.settingsSpinner : undefined} /> 刷新</button>
    </header>
    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {notice && <p role="status" style={{ margin: '0 0 10px', fontSize: 13, color: 'var(--fg-2)' }}>{notice}</p>}
    <form className={styles.settingsForm} onSubmit={async (event) => {
      event.preventDefault();
      if (!source.trim()) return;
      await post('/api/plugins/install', { source: source.trim() });
      setSource('');
    }}>
      <label>从哪里安装
        <input placeholder="本地目录路径、git 地址，或 用户名/仓库" value={source} onChange={(e) => setSource(e.target.value)} />
      </label>
      <p style={{ margin: 0, fontSize: 12.5 }}>本地目录要装 Claude Code 插件的格式（带 plugin.json）；git 地址或「用户名/仓库」会自动克隆安装。填一个 marketplace 仓库则注册为插件市场。</p>
      <button className={styles.settingsAction} disabled={busy || !source.trim()}>安装</button>
    </form>
    {plugins.length === 0 && !busy && <p>还没有插件。装一个，或者把含 plugin.json 的目录放进 plugins/ 文件夹。</p>}
    <ul>
      {plugins.map((plugin) => (
        <li key={plugin.name}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ flex: 1, minWidth: 0 }}>
              <strong>{plugin.display_name || plugin.name}</strong> <small>v{plugin.version} · {SOURCE_LABEL[plugin.source ?? ''] ?? plugin.source ?? '本地'}{plugin.marketplace ? ` · ${plugin.marketplace}` : ''}{plugin.loaded ? ' · 已加载' : ''}{plugin.update_available ? ' · 有新版本' : ''}</small>
              {plugin.description && <div><small>{plugin.description}</small></div>}
              {(plugin.skills?.length || plugin.commands?.length || plugin.agents?.length || plugin.mcp_servers?.length || plugin.hooks) && (
                <div><small>技能 {plugin.skills?.length ?? 0} · 命令 {plugin.commands?.length ?? 0} · Agent {plugin.agents?.length ?? 0} · Hook {plugin.hooks ?? 0} · MCP {plugin.mcp_servers?.length ?? 0}</small></div>
              )}
            </span>
            <button className={styles.quietButton} onClick={() => void post(`/api/plugins/${encodeURIComponent(plugin.name)}/enabled`, { enabled: !plugin.enabled })} disabled={busy}>
              {plugin.enabled ? '停用' : '启用'}
            </button>
            <button className={styles.quietButton} onClick={() => void post(`/api/plugins/${encodeURIComponent(plugin.name)}/update`)} disabled={busy}>更新</button>
            <button className={styles.quietButton} style={confirmRemove === plugin.name ? { color: 'var(--danger)' } : undefined}
              onClick={() => {
                if (confirmRemove !== plugin.name) { setConfirmRemove(plugin.name); return; }
                void act(`${apiBaseUrl}/api/plugins/${encodeURIComponent(plugin.name)}`, { method: 'DELETE' }, `已卸载 ${plugin.name}`);
              }} disabled={busy}>
              {confirmRemove === plugin.name ? '确认卸载' : '卸载'}
            </button>
          </div>
        </li>
      ))}
    </ul>

    <h2 style={{ marginTop: 18 }}>插件市场</h2>
    <p style={{ margin: '0 0 10px', fontSize: 13 }}>市场是一次性加进来的一批插件目录。添加后可以浏览里面的插件并逐个安装。</p>
    <form className={styles.settingsForm} onSubmit={async (event) => {
      event.preventDefault();
      if (!marketSource.trim()) return;
      await post('/api/plugin-marketplaces', { source: marketSource.trim() });
      setMarketSource('');
      setNotice('插件市场已添加');
    }}>
      <label>市场来源
        <input placeholder="本地路径或 git 地址（仓库里要有 marketplace.json）" value={marketSource} onChange={(e) => setMarketSource(e.target.value)} />
      </label>
      <button className={styles.settingsAction} disabled={busy || !marketSource.trim()}>添加市场</button>
    </form>
    {marketplaces.length > 0 && <ul>
      {marketplaces.map((market) => (
        <li key={market.name ?? market.path}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <span style={{ flex: 1, minWidth: 0 }}>
              <strong>{market.name ?? '未命名市场'}</strong> <small>{market.type === 'git' ? 'git' : '本地'}{market.source ? ` · ${market.source}` : ''}</small>
            </span>
            <button className={styles.quietButton} disabled={busy || !market.name}
              onClick={() => { if (browsing?.name === market.name) setBrowsing(null); else void browse(market.name ?? ''); }}>
              {browsing?.name === market.name ? '收起' : '浏览'}
            </button>
          </div>
          {browsing && browsing.name === market.name && (browsing.entries.length ? (
            <ul style={{ margin: '8px 0 0' }}>
              {browsing.entries.map((entry, index) => (
                <li key={entry.name ?? index}>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span style={{ flex: 1, minWidth: 0 }}>
                      <strong>{entry.name ?? '未命名插件'}</strong>
                      {entry.description && <div><small>{entry.description}</small></div>}
                    </span>
                    <button className={styles.quietButton} disabled={busy || !entry.name}
                      onClick={() => void post(`/api/plugin-marketplaces/${encodeURIComponent(market.name ?? '')}/install`, { plugin: entry.name })}>
                      安装
                    </button>
                  </div>
                </li>
              ))}
            </ul>
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
