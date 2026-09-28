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

function ProjectsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
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
  version: string;
  description: string;
  enabled: boolean;
  loaded: boolean;
  skills: string[];
  commands: string[];
  mcp_servers: string[];
}

function PluginsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [plugins, setPlugins] = useState<Plugin[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState('');

  const refresh = useCallback(async () => {
    setBusy(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/plugins`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setPlugins((await response.json()).plugins);
      setError(null);
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const toggle = async (name: string, enabled: boolean) => {
    setBusy(true);
    try {
      await fetch(`${apiBaseUrl}/api/plugins/${name}/enabled`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled }),
      });
      await refresh();
    } catch (exc) {
      setError(String(exc));
    } finally {
      setBusy(false);
    }
  };

  return <section className={styles.settingsCard} aria-label="插件管理">
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <h2>插件</h2>
      <button className={styles.quietButton} onClick={() => void refresh()} disabled={busy}><RefreshCw size={14} /> 刷新</button>
    </header>
    {error && <p role="alert">{error}</p>}
    <form className={styles.settingsForm} onSubmit={async (event) => {
      event.preventDefault();
      if (!source.trim()) return;
      setBusy(true);
      try {
        await fetch(`${apiBaseUrl}/api/plugins/install-local`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: source.trim() }),
        });
        setSource('');
        await refresh();
      } catch (exc) {
        setError(String(exc));
      } finally {
        setBusy(false);
      }
    }}>
      <input placeholder="本地插件目录路径（含 plugin.json）" value={source} onChange={(e) => setSource(e.target.value)} />
      <button className={styles.settingsAction} disabled={busy || !source.trim()}>从本地安装</button>
    </form>
    {plugins.length === 0 && !busy && <p>还没有插件。把含 plugin.json 的目录放到 plugins/ 下或从本地安装。</p>}
    <ul style={{ listStyle: 'none', padding: 0 }}>
      {plugins.map((plugin) => (
        <li key={plugin.name} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 0' }}>
          <span style={{ flex: 1 }}>
            <strong>{plugin.name}</strong> <small>v{plugin.version}{plugin.loaded ? ' · 已加载' : ''}</small>
            {(plugin.skills.length > 0 || plugin.commands.length > 0 || plugin.mcp_servers.length > 0) && (
              <div><small>skills {plugin.skills.length} · commands {plugin.commands.length} · mcp {plugin.mcp_servers.length}</small></div>
            )}
          </span>
          <button
            className={styles.quietButton}
            onClick={() => void toggle(plugin.name, !plugin.enabled)}
            disabled={busy}
          >{plugin.enabled ? '停用' : '启用'}</button>
        </li>
      ))}
    </ul>
  </section>;
}

function NotificationsPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
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
