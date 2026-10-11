import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { FolderGit2, LoaderCircle, Plus, RefreshCw, Search, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';
import ProjectSourcesPanel from './ProjectSourcesPanel';
import { ProjectIcon, PROJECT_ICON_OPTIONS } from './ProjectIcon';

interface Project { project_id: string; name: string; workspace_path: string; repo_url: string; status: string; current_goal: string; current_state: string; color: string; icon: string; updated_at?: string }
interface RecallHit { conversation_title: string; snippet: string; created_at: string }
const STATUS: Record<string, string> = { active: '进行中', paused: '已暂停', archived: '已归档', done: '已完成', completed: '已完成' };
const statusName = (value: string) => STATUS[value] ?? value;

export default function CodePage({ apiBaseUrl, connected, onToast }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importPath, setImportPath] = useState('');
  const [editingName, setEditingName] = useState(false);
  const [name, setName] = useState('');
  const [color, setColor] = useState('');
  const [icon, setIcon] = useState('folder');
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
      window.dispatchEvent(new Event('atlas:projects-updated'));
      setSelected((current) => current && body.projects.some((item) => item.project_id === current) ? current : body.projects[0]?.project_id ?? '');
      setError('');
    } catch (exc) { setError(`读取项目失败：${exc instanceof Error ? exc.message : String(exc)}`); }
    finally { setBusy(false); }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { setConfirmDelete(false); setHits(null); setQuery(''); }, [selected]);
  useEffect(() => {
    const current = projects.find((item) => item.project_id === selected);
    setName(current?.name ?? '');
    setColor(current?.color ?? '');
    setIcon(current?.icon ?? 'folder');
    setEditingName(false);
  }, [projects, selected]);

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
  const update = async (id: string, values: Record<string, string>, message: string) => {
    setBusy(true);
    try {
      await api(apiBaseUrl, `/api/projects/${encodeURIComponent(id)}`, { method: 'PUT', json: values });
      onToast(message);
      await refresh();
      return true;
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); return false; }
    finally { setBusy(false); }
  };
  const changeStatus = async (id: string, action: 'close' | 'reopen') => {
    setBusy(true);
    try {
      await api(apiBaseUrl, `/api/projects/${encodeURIComponent(id)}/${action}`, { method: 'POST' });
      onToast(action === 'close' ? '已关闭项目，可从最近关闭重新打开' : '已重新打开项目');
      await refresh();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const importLocal = async (event: FormEvent) => {
    event.preventDefault();
    if (!importPath.trim()) return;
    setBusy(true);
    try {
      const imported = await api<Project>(apiBaseUrl, '/api/projects/import', { method: 'POST', json: { workspace_path: importPath.trim() } });
      setImporting(false);
      setImportPath('');
      setSelected(imported.project_id);
      onToast('已导入本地项目');
      await refresh();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const pickImportPath = async () => {
    const picked = await window.atlasDesktop?.selectDirectory?.(importPath || undefined);
    if (picked) setImportPath(picked);
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
  const openProjects = projects.filter((item) => item.status !== 'archived');
  const closedProjects = projects.filter((item) => item.status === 'archived');

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>项目与代码</h1><p>给 Atlas 一个项目：它会记住目标、进度和相关对话，下次接着做。</p></div>
      <div className="btns">
        <button className="btn ghost" aria-label="刷新项目" onClick={() => void refresh()} disabled={busy || !connected}>{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
        <button className="btn ghost" disabled={!connected} onClick={() => { setImporting(true); setCreating(false); }}>导入本地目录</button>
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

    {importing && <form className="card glass form" onSubmit={(event) => void importLocal(event)}>
      <h2>导入本地项目</h2>
      <p>选择已存在的本地目录，Atlas 会登记此目录，并读取 Git origin 地址；不会改动目录文件。</p>
      <label>目录路径<input required value={importPath} onChange={(event) => setImportPath(event.target.value)} placeholder="D:\code\my-app" /></label>
      <div className="foot">
        {window.atlasDesktop?.selectDirectory && <button type="button" className="btn ghost" onClick={() => void pickImportPath()}>选择目录</button>}
        <button type="button" className="btn ghost" onClick={() => setImporting(false)}>取消</button>
        <button className="btn primary" disabled={busy || !importPath.trim()}>导入</button>
      </div>
    </form>}

    <div className="split">
      <div className="list glass" role="listbox" aria-label="项目">
        {openProjects.map((project) => <button className="row" role="option" key={project.project_id} aria-selected={project.project_id === selected} onClick={() => setSelected(project.project_id)}>
          <span className="ico brass"><ProjectIcon icon={project.icon} color={project.color} /></span>
          <span style={{ minWidth: 0 }}><p>{project.name}</p><small>{project.current_goal || project.workspace_path || '还没有设定目标'}</small></span>
          <span className="when"><b>{statusName(project.status)}</b>{relativeTime(project.updated_at)}</span>
        </button>)}
        {!projects.length && !busy && <div className="empty"><FolderGit2 size={22} /><b>还没有项目</b>新建一个项目，挂在项目下的对话会自动带上项目的目标和进度。</div>}
        {closedProjects.length > 0 && <details className="p-3" open={closedProjects.some((item) => item.project_id === selected)}>
          <summary className="cursor-pointer text-sm">最近关闭 ({closedProjects.length})</summary>
          {closedProjects.map((project) => <button className="row" role="option" key={project.project_id} aria-selected={project.project_id === selected} onClick={() => setSelected(project.project_id)}>
            <span className="ico brass"><ProjectIcon icon={project.icon} color={project.color} /></span>
            <span style={{ minWidth: 0 }}><p>{project.name}</p><small>{project.workspace_path || '无工作区'}</small></span>
            <span className="when">{relativeTime(project.updated_at)}</span>
          </button>)}
        </details>}
      </div>
      {current ? <aside className="detail glass" aria-label="项目详情">
        <h2><ProjectIcon icon={current.icon} color={current.color} size={19} /> {current.name}</h2>
        <div className="sub">{statusName(current.status)}</div>
        {editingName ? <form onSubmit={(event) => { event.preventDefault(); if (name.trim()) void update(current.project_id, { name: name.trim() }, '已重命名项目').then((saved) => { if (saved) setEditingName(false); }); }}>
          <label>项目名称<input autoFocus required value={name} onChange={(event) => setName(event.target.value)} /></label>
          <div className="btns"><button type="button" className="btn ghost" onClick={() => setEditingName(false)}>取消</button><button className="btn primary" disabled={busy || !name.trim()}>保存名称</button></div>
        </form> : <button className="btn ghost" disabled={busy} onClick={() => setEditingName(true)}>重命名</button>}
        <dl>
          <div><dt>目标</dt><dd>{current.current_goal || '未设定'}</dd></div>
          <div><dt>进度</dt><dd>{current.current_state || '还没有记录'}</dd></div>
          {current.workspace_path && <div><dt>工作区</dt><dd style={{ fontFamily: 'var(--f-mono)', fontSize: 13 }}>{current.workspace_path}</dd></div>}
          {current.repo_url && <div><dt>仓库 origin</dt><dd style={{ fontFamily: 'var(--f-mono)', fontSize: 13, overflowWrap: 'anywhere' }}>{current.repo_url}</dd></div>}
        </dl>
        <form onSubmit={(event) => { event.preventDefault(); void update(current.project_id, { color, icon }, '已保存项目外观'); }}>
          <h3>项目外观</h3>
          <div className="two">
            <label>颜色<input type="color" value={color || '#b79a72'} onChange={(event) => setColor(event.target.value)} /></label>
            <label>图标<select value={icon} onChange={(event) => setIcon(event.target.value)}>{PROJECT_ICON_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          </div>
          <div className="btns">
            <button type="button" className="btn ghost" disabled={busy || !current.color} onClick={() => void update(current.project_id, { color: '', icon }, '已恢复默认项目颜色')}>默认颜色</button>
            <button className="btn ghost" disabled={busy || (color === current.color && icon === current.icon)}>保存外观</button>
          </div>
        </form>
        <ProjectSourcesPanel projectId={current.project_id} workspacePath={current.workspace_path} apiBaseUrl={apiBaseUrl} onToast={onToast} />
        <form onSubmit={(event) => void recall(event)} style={{ marginTop: 18 }}>
          <label className="field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="在这个项目的历史对话里找…" aria-label="项目历史搜索" /></label>
        </form>
        {hits && <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
          {hits.map((hit, index) => <div key={index} style={{ fontSize: 13 }}><b style={{ fontWeight: 500 }}>{hit.conversation_title}</b><div style={{ color: 'var(--ink2)' }}>{hit.snippet.slice(0, 160)}</div></div>)}
          {!hits.length && <div className="empty-note">没有找到相关的历史对话。</div>}
        </div>}
        <div className="btns">
          <button className="btn ghost" disabled={busy} onClick={() => void changeStatus(current.project_id, current.status === 'archived' ? 'reopen' : 'close')}>{current.status === 'archived' ? '重新打开项目' : '关闭项目'}</button>
          <button className={`btn ${confirmDelete ? 'danger' : 'ghost'}`} disabled={busy} onClick={() => { if (confirmDelete) void remove(current.project_id); else setConfirmDelete(true); }}>{confirmDelete ? '确认删除项目' : '删除项目'}</button>
        </div>
      </aside> : <div />}
    </div>
  </div></div>;
}
