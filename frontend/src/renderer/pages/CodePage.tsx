import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { FolderGit2, LoaderCircle, Plus, RefreshCw, Search, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';
import ProjectSourcesPanel from './ProjectSourcesPanel';

interface Project { project_id: string; name: string; workspace_path: string; status: string; current_goal: string; current_state: string; updated_at?: string }
interface RecallHit { conversation_title: string; snippet: string; created_at: string }
const STATUS: Record<string, string> = { active: '进行中', paused: '已暂停', archived: '已归档', done: '已完成', completed: '已完成' };
const statusName = (value: string) => STATUS[value] ?? value;

export default function CodePage({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [form, setForm] = useState({ name: '', workspace_path: '', current_goal: '' });
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<RecallHit[] | null>(null);

  const refresh = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    try {
      const body = await api<{ projects: Project[] }>(apiBaseUrl, '/api/projects');
      setProjects(body.projects);
      setSelected((current) => current && body.projects.some((item) => item.project_id === current) ? current : body.projects[0]?.project_id ?? '');
      setError('');
    } catch (exc) { setError(`读取项目失败：${exc instanceof Error ? exc.message : String(exc)}`); }
    finally { setBusy(false); }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { setConfirmDelete(false); setHits(null); setQuery(''); }, [selected]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const created = await api<Partial<Project>>(apiBaseUrl, '/api/projects', { method: 'POST', json: { name: form.name.trim(), workspace_path: form.workspace_path.trim(), current_goal: form.current_goal.trim() } });
      setForm({ name: '', workspace_path: '', current_goal: '' });
      setCreating(false);
      if (created.project_id) setSelected(created.project_id);
      onToast('已创建项目');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
    await refresh();
  };
  const remove = async (id: string) => {
    setBusy(true);
    try { await api(apiBaseUrl, `/api/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }); onToast('已删除项目'); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
    await refresh();
  };
  const recall = async (event: FormEvent) => {
    event.preventDefault();
    if (!query.trim() || !selected) return;
    try {
      const body = await api<{ results: RecallHit[] }>(apiBaseUrl, `/api/projects/${encodeURIComponent(selected)}/recall?query=${encodeURIComponent(query.trim())}`);
      setHits(body.results);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };

  const current = projects.find((item) => item.project_id === selected);

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>项目与代码</h1><p>给 Atlas 一个项目：它会记住目标、进度和相关对话，下次接着做。</p></div>
      <div className="btns">
        <button className="btn ghost" aria-label="刷新项目" onClick={() => void refresh()} disabled={busy || !connected}>{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        <button className="btn primary" disabled={!connected} onClick={() => setCreating(true)}><Plus size={15} />新建项目</button>
      </div>
    </header>
    {!connected && <div className="error-note">Atlas 后端未连接。</div>}
    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}

    {creating && <form className="card glass form" onSubmit={(event) => void create(event)}>
      <h2>新建项目</h2>
      <div className="two">
        <label>项目名称<input required autoFocus value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="例如：Atlas 桌面端" /></label>
        <label>工作区路径<input value={form.workspace_path} onChange={(event) => setForm({ ...form, workspace_path: event.target.value })} placeholder="D:\code\my-app（可选）" /></label>
      </div>
      <label>当前目标<input value={form.current_goal} onChange={(event) => setForm({ ...form, current_goal: event.target.value })} placeholder="这一阶段要完成什么（可选）" /></label>
      <div className="foot"><button type="button" className="btn ghost" onClick={() => setCreating(false)}>取消</button><button className="btn primary" disabled={busy || !form.name.trim()}>创建项目</button></div>
    </form>}

    <div className="split">
      <div className="list glass" role="listbox" aria-label="项目">
        {projects.map((project) => <button className="row" role="option" key={project.project_id} aria-selected={project.project_id === selected} onClick={() => setSelected(project.project_id)}>
          <span className="ico brass"><FolderGit2 size={17} /></span>
          <span style={{ minWidth: 0 }}><p>{project.name}</p><small>{project.current_goal || project.workspace_path || '还没有设定目标'}</small></span>
          <span className="when"><b>{statusName(project.status)}</b>{relativeTime(project.updated_at)}</span>
        </button>)}
        {!projects.length && !busy && <div className="empty"><FolderGit2 size={22} /><b>还没有项目</b>新建一个项目，挂在项目下的对话会自动带上项目的目标和进度。</div>}
      </div>
      {current ? <aside className="detail glass" aria-label="项目详情">
        <h2>{current.name}</h2>
        <div className="sub">{statusName(current.status)}</div>
        <dl>
          <div><dt>目标</dt><dd>{current.current_goal || '未设定'}</dd></div>
          <div><dt>进度</dt><dd>{current.current_state || '还没有记录'}</dd></div>
          {current.workspace_path && <div><dt>工作区</dt><dd style={{ fontFamily: 'var(--f-mono)', fontSize: 13 }}>{current.workspace_path}</dd></div>}
        </dl>
        <ProjectSourcesPanel projectId={current.project_id} onToast={onToast} />
        <form onSubmit={(event) => void recall(event)} style={{ marginTop: 18 }}>
          <label className="field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="在这个项目的历史对话里找…" aria-label="项目历史搜索" /></label>
        </form>
        {hits && <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
          {hits.map((hit, index) => <div key={index} style={{ fontSize: 13 }}><b style={{ fontWeight: 500 }}>{hit.conversation_title}</b><div style={{ color: 'var(--ink2)' }}>{hit.snippet.slice(0, 160)}</div></div>)}
          {!hits.length && <div className="empty-note">没有找到相关的历史对话。</div>}
        </div>}
        <div className="btns">
          <button className={`btn ${confirmDelete ? 'danger' : 'ghost'}`} disabled={busy} onClick={() => { if (confirmDelete) void remove(current.project_id); else setConfirmDelete(true); }}>{confirmDelete ? '确认删除项目' : '删除项目'}</button>
        </div>
      </aside> : <div />}
    </div>
  </div></div>;
}
