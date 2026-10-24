import { useEffect, useState, type FormEvent } from 'react';
import { File, Folder, FolderOpen, Globe, NotebookText, Plus, RefreshCw, Trash2 } from 'lucide-react';
import type { ProjectSource, ProjectSources } from '@atlas/backend-adapter';
import { backend } from '../store/useAtlasStore';
import { api } from '../services/api';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

const KINDS: Record<ProjectSource['kind'], { label: string; icon: typeof File; placeholder: string }> = {
  folder: { label: '文件夹', icon: Folder, placeholder: 'D:\\项目资料' },
  file: { label: '文件', icon: File, placeholder: 'D:\\资料\\需求说明.docx' },
  url: { label: '网址', icon: Globe, placeholder: 'https://…' },
  note: { label: '笔记', icon: NotebookText, placeholder: '直接写下要 Atlas 记住的内容' },
};
const size = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : bytes >= 1024 ? `${Math.round(bytes / 1024)} KB` : `${bytes} B`;

/** What every conversation in the project can use: standing instructions plus indexed files, links and notes. */
export default function ProjectSourcesPanel({ projectId, workspacePath, apiBaseUrl, onToast }: { projectId: string; workspacePath: string; apiBaseUrl: string; onToast: (text: string) => void }) {
  const [data, setData] = useState<ProjectSources | null>(null);
  const [instructions, setInstructions] = useState('');
  const [notes, setNotes] = useState('');
  const [savedNotes, setSavedNotes] = useState('');
  const [notesLoading, setNotesLoading] = useState(false);
  const [notesBusy, setNotesBusy] = useState(false);
  const [notesError, setNotesError] = useState('');
  const [kind, setKind] = useState<ProjectSource['kind']>('folder');
  const [value, setValue] = useState('');
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [memoryScope, setMemoryScope] = useState<'global' | 'project-only'>('global');
  const [scopeBusy, setScopeBusy] = useState(false);
  const load = () => backend.getProjectSources(projectId).then((result) => { setData(result); setInstructions(result.instructions); setError(''); })
    .catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)));
  useEffect(() => { setData(null); void load(); }, [projectId]);
  useEffect(() => {
    let cancelled = false;
    void api<{ memory_scope?: 'global' | 'project-only' }>(apiBaseUrl, `/api/projects/${encodeURIComponent(projectId)}`)
      .then((project) => { if (!cancelled) setMemoryScope(project.memory_scope === 'project-only' ? 'project-only' : 'global'); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [apiBaseUrl, projectId]);
  useEffect(() => {
    let cancelled = false;
    setNotes(''); setSavedNotes(''); setNotesError('');
    if (!workspacePath || workspacePath.startsWith('ssh://')) return;
    setNotesLoading(true);
    void api<{ content: string }>(apiBaseUrl, `/api/workspace/notes?root=${encodeURIComponent(workspacePath)}`)
      .then((result) => { if (!cancelled) { setNotes(result.content); setSavedNotes(result.content); } })
      .catch((exc) => { if (!cancelled) setNotesError(exc instanceof Error ? exc.message : String(exc)); })
      .finally(() => { if (!cancelled) setNotesLoading(false); });
    return () => { cancelled = true; };
  }, [apiBaseUrl, workspacePath]);

  const run = async (key: string, action: () => Promise<unknown>, done: string) => {
    setBusy(key); setError('');
    try { await action(); await load(); onToast(done); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };
  const add = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) return;
    const body = kind === 'url' ? { url: trimmed } : kind === 'note' ? { text: trimmed } : { path: trimmed };
    void run('add', () => backend.addProjectSource(projectId, { kind, title: title.trim() || undefined, ...body }), '已加入项目资料').then(() => { setValue(''); setTitle(''); });
  };
  const pick = async () => {
    if (kind !== 'folder' || !window.atlasDesktop?.selectDirectory) return;
    const picked = await window.atlasDesktop.selectDirectory(value || undefined);
    if (picked) setValue(picked);
  };

  const field = 'rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <section className="mt-5 grid gap-3 text-[13px]" aria-label="项目资料">
    <h3 className="m-0 text-[14px] font-semibold text-heading">项目资料</h3>
    <label className="flex items-center gap-2 rounded-lg bg-sunken p-2.5 text-fg-2"><input type="checkbox" checked={memoryScope === 'project-only'} disabled={scopeBusy}
      onChange={(event) => {
        const next = event.target.checked ? 'project-only' : 'global';
        setScopeBusy(true);
        void api(apiBaseUrl, `/api/projects/${encodeURIComponent(projectId)}`, { method: 'PUT', json: { memory_scope: next } })
          .then(() => setMemoryScope(next)).catch((exc) => setError(exc instanceof Error ? exc.message : String(exc))).finally(() => setScopeBusy(false));
      }} />只在本项目内使用记忆</label>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
    <label className="grid gap-1 text-fg-2">项目指令（这个项目里的每次任务都会带上）
      <textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} rows={3} maxLength={8000}
        placeholder="比如：代码风格跟 src/ 里现有的保持一致；改完要跑 npm test；不要动 legacy/ 目录" className={cn(field, 'py-2 leading-[1.6]')} /></label>
    {data && instructions !== data.instructions && <div><Button size="sm" variant="primary" disabled={busy === 'instructions'}
      onClick={() => void run('instructions', () => backend.setProjectInstructions(projectId, instructions), '项目指令已保存')}>保存指令</Button></div>}

    <div className="grid gap-1.5">
      <label className="grid gap-1 text-fg-2" htmlFor="project-notes">项目 NOTES.md（工作区的 .atlas/NOTES.md）</label>
      {!workspacePath || workspacePath.startsWith('ssh://')
        ? <p className="m-0 text-[12.5px] text-fg-3">项目没有本地工作区路径，无法编辑 NOTES.md。</p>
        : <>
          {notesError && <p role="alert" className="m-0 text-[12px] text-danger">读取或保存 NOTES.md 失败：{notesError}</p>}
          <textarea id="project-notes" value={notes} onChange={(event) => setNotes(event.target.value)} rows={5} maxLength={65536}
            disabled={notesLoading || notesBusy} placeholder={notesLoading ? '正在读取…' : '写下这个项目需要长期保留的说明'}
            className={cn(field, 'py-2 leading-[1.6]')} />
          <div className="flex items-center justify-between gap-2">
            <small className="text-[11.5px] text-fg-3">保存到工作区 .atlas/NOTES.md，最多 64 KiB。</small>
            {notes !== savedNotes && <Button size="sm" variant="primary" disabled={notesLoading || notesBusy || new TextEncoder().encode(notes).length > 65536}
              onClick={() => {
                setNotesBusy(true); setNotesError('');
                void api(apiBaseUrl, '/api/workspace/notes', { method: 'PUT', json: { root: workspacePath, content: notes } })
                  .then(() => { setSavedNotes(notes); onToast('项目 NOTES.md 已保存'); })
                  .catch((exc) => setNotesError(exc instanceof Error ? exc.message : String(exc)))
                  .finally(() => setNotesBusy(false));
              }}>{notesBusy ? '保存中…' : '保存 NOTES.md'}</Button>}
          </div>
        </>}
    </div>

    <div className="grid gap-1.5">
      {data?.sources.map((source) => {
        const Icon = KINDS[source.kind]?.icon ?? File;
        return <div key={source.id} className="flex items-center gap-2.5 rounded-xl card-surface px-3 py-2">
          <Icon size={15} className="shrink-0 text-brand" />
          <span className="min-w-0 flex-1">
            <b className="block truncate font-medium text-fg" title={source.path ?? source.url ?? source.title}>{source.title}</b>
            <small className="block truncate text-[12px] text-fg-3">{KINDS[source.kind]?.label} · {size(source.bytes)}{source.path ? ` · ${source.path}` : source.url ? ` · ${source.url}` : ''}</small>
          </span>
          {source.kind !== 'note' && <button aria-label={`重新索引「${source.title}」`} title="重新读取内容" disabled={Boolean(busy)} onClick={() => void run(source.id, () => backend.refreshProjectSource(projectId, source.id), '已重新索引')}
            className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg disabled:opacity-50"><RefreshCw size={13} className={busy === source.id ? 'spin' : undefined} /></button>}
          <button aria-label={`移除「${source.title}」`} disabled={Boolean(busy)} onClick={() => void run(`del:${source.id}`, () => backend.deleteProjectSource(projectId, source.id), '已移除')}
            className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-danger disabled:opacity-50"><Trash2 size={13} /></button>
        </div>;
      })}
      {data && !data.sources.length && <p className="m-0 text-[12.5px] text-fg-3">还没有资料。加进来的文件、文件夹、网址和笔记会建立索引，项目里的对话可以随时搜索引用。</p>}
    </div>

    <form onSubmit={add} className="grid gap-2 rounded-xl bg-sunken p-3">
      <div className="flex gap-1" role="radiogroup" aria-label="资料类型">
        {(Object.keys(KINDS) as Array<ProjectSource['kind']>).map((key) => {
          const Icon = KINDS[key].icon;
          return <button key={key} type="button" role="radio" aria-checked={kind === key} onClick={() => { setKind(key); setValue(''); }}
            className={cn('inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px]', kind === key ? 'bg-overlay text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}><Icon size={13} />{KINDS[key].label}</button>;
        })}
      </div>
      <div className="flex gap-2">
        {kind === 'note'
          ? <textarea value={value} onChange={(event) => setValue(event.target.value)} rows={3} placeholder={KINDS.note.placeholder} aria-label="笔记内容" className={cn(field, 'min-w-0 flex-1 bg-overlay py-2')} />
          : <input value={value} onChange={(event) => setValue(event.target.value)} placeholder={KINDS[kind].placeholder} aria-label={`${KINDS[kind].label}地址`} className={cn(field, 'h-8 min-w-0 flex-1 bg-overlay')} />}
        {kind === 'folder' && window.atlasDesktop?.selectDirectory && <Button type="button" size="sm" onClick={() => void pick()}><FolderOpen />选择</Button>}
      </div>
      <div className="flex gap-2">
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="标题（可选）" aria-label="资料标题" className={cn(field, 'h-8 min-w-0 flex-1 bg-overlay')} />
        <Button type="submit" size="sm" variant="primary" disabled={!value.trim() || busy === 'add'}><Plus />加入</Button>
      </div>
      <small className="text-[11.5px] text-fg-3">单个文件 2 MB、总共 50 MB 以内；支持文本、代码、Markdown、Word、Excel、PPT、PDF。网址只在加入时读一次，要更新就点刷新。</small>
    </form>
  </section>;
}
