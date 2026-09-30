import { useCallback, useEffect, useState } from 'react';
import { ChevronRight, Code2, Eye, ExternalLink, File, Folder, FolderOpen, LoaderCircle, RefreshCw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { WorkspaceEntry, WorkspaceFile } from '@atlas/backend-adapter';
import { backend } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';

const GIT: Record<string, { label: string; tone: string }> = {
  M: { label: 'M', tone: 'text-brand' }, A: { label: 'A', tone: 'text-ok' }, D: { label: 'D', tone: 'text-danger' }, '?': { label: 'U', tone: 'text-ok' },
};

/** Browse the conversation's working directory and read files without leaving Atlas. */
const PREVIEWABLE = /\.(html?|pdf|svg|png|jpe?g|gif|webp)$/i;
const IMAGE = /\.(png|jpe?g|gif|webp|svg)$/i;
const MARKDOWN = /\.(md|markdown)$/i;
const FRAME = /\.(html?|pdf)$/i;
const canPreview = (path: string) => MARKDOWN.test(path) || IMAGE.test(path) || FRAME.test(path);

export default function FilesPanel({ workspace, onChooseWorkspace, refreshKey, onPreview }: {
  workspace?: string | null; onChooseWorkspace: () => void; refreshKey: string; onPreview: (url: string) => void;
}) {
  const [dirs, setDirs] = useState<Record<string, WorkspaceEntry[]>>({});
  const [expanded, setExpanded] = useState<string[]>([]);
  const [loading, setLoading] = useState<string[]>([]);
  const [selected, setSelected] = useState('');
  const [file, setFile] = useState<WorkspaceFile | null>(null);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'preview' | 'code'>('preview');

  const load = useCallback(async (path: string) => {
    if (!workspace) return;
    setLoading((current) => [...current, path]);
    try {
      const entries = await backend.getWorkspaceTree(workspace, path);
      setDirs((current) => ({ ...current, [path]: [...entries].sort((a, b) => a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'dir' ? -1 : 1) }));
      setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setLoading((current) => current.filter((item) => item !== path)); }
  }, [workspace]);

  // A new directory or a finished run: reload the open folders so new files and git marks show up.
  useEffect(() => {
    setDirs({});
    if (!workspace) return;
    void load('');
    expanded.forEach((path) => void load(path));
  }, [workspace, refreshKey, load]);
  useEffect(() => { setExpanded([]); setSelected(''); setFile(null); }, [workspace]);
  useEffect(() => setMode('preview'), [selected]);

  useEffect(() => {
    if (!workspace || !selected) { setFile(null); return; }
    let stale = false;
    backend.getWorkspaceFile(workspace, selected).then((result) => { if (!stale) setFile(result); })
      .catch((exc) => { if (!stale) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { stale = true; };
  }, [workspace, selected, refreshKey]);

  if (!workspace) return <Empty title="还没有选工作目录" body="选一个文件夹，Atlas 的命令和文件操作都会在里面进行，这里也能直接浏览。"
    icon={<FolderOpen size={22} />} action={<Button variant="primary" onClick={onChooseWorkspace}><FolderOpen />选择文件夹</Button>} />;

  const toggle = (entry: WorkspaceEntry) => {
    if (entry.type === 'file') { setSelected(entry.path); return; }
    if (expanded.includes(entry.path)) { setExpanded((current) => current.filter((item) => item !== entry.path)); return; }
    setExpanded((current) => [...current, entry.path]);
    if (!dirs[entry.path]) void load(entry.path);
  };
  const rows = (path: string, depth: number): JSX.Element[] => (dirs[path] ?? []).flatMap((entry) => {
    const open = expanded.includes(entry.path);
    const git = entry.git ? GIT[entry.git] ?? { label: entry.git, tone: 'text-fg-3' } : null;
    const row = <button key={entry.path} onClick={() => toggle(entry)} title={entry.path}
      className={cn('flex w-full items-center gap-1.5 rounded-md py-[3px] pr-2 text-left text-[12.5px] hover:bg-hover', selected === entry.path ? 'bg-selected text-fg' : 'text-fg-2')}
      style={{ paddingLeft: 6 + depth * 14 }}>
      {entry.type === 'dir'
        ? <><ChevronRight size={12} className={cn('shrink-0 text-fg-3 transition-transform', open && 'rotate-90')} />{open ? <FolderOpen size={14} className="shrink-0 text-brand" /> : <Folder size={14} className="shrink-0 text-brand" />}</>
        : <><span className="w-3 shrink-0" /><File size={14} className="shrink-0 text-fg-3" /></>}
      <span className="min-w-0 flex-1 truncate">{entry.name}</span>
      {loading.includes(entry.path) && <LoaderCircle size={12} className="spin shrink-0 text-fg-3" />}
      {git && <span className={cn('shrink-0 font-mono text-[11px]', git.tone)}>{git.label}</span>}
    </button>;
    return open ? [row, ...rows(entry.path, depth + 1)] : [row];
  });

  return <div className="flex h-full min-h-0 flex-col gap-3">
    <div className="flex items-center gap-2">
      <button onClick={onChooseWorkspace} title={`${workspace}（点击更换）`} className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1 text-left text-[12.5px] text-fg-2 hover:bg-hover">
        <FolderOpen size={14} className="shrink-0 text-brand" /><span className="truncate">{workspace}</span>
      </button>
      <button aria-label="刷新文件" onClick={() => { void load(''); expanded.forEach((path) => void load(path)); }} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><RefreshCw size={13} /></button>
    </div>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
    <div className={cn('min-h-0 overflow-auto', file ? 'max-h-[42%] shrink-0' : 'flex-1')} role="tree" aria-label="工作目录文件">
      {dirs[''] ? rows('', 0) : <p className="py-6 text-center text-[13px] text-fg-3">正在读取目录…</p>}
      {dirs[''] && !dirs[''].length && <p className="py-6 text-center text-[13px] text-fg-3">这个文件夹是空的。</p>}
    </div>
    {file && <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl card-surface">
      <div className="flex items-center gap-2 px-3 py-2 text-[12px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)]">
        <File size={13} className="shrink-0 text-fg-3" /><code className="min-w-0 flex-1 truncate font-mono">{file.path}</code>
        {canPreview(file.path) && <div className="flex shrink-0 rounded-md bg-sunken p-0.5" role="group" aria-label="显示方式">
          {(['preview', 'code'] as const).map((value) => <button key={value} onClick={() => setMode(value)} aria-pressed={mode === value} title={value === 'preview' ? '预览' : '源码'}
            className={cn('grid h-5 w-6 place-items-center rounded', mode === value ? 'bg-overlay text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}>{value === 'preview' ? <Eye size={12} /> : <Code2 size={12} />}</button>)}
        </div>}
        {PREVIEWABLE.test(file.path) && <button onClick={() => onPreview(backend.rawFileUrl(workspace, file.path))} className="shrink-0 text-fg-2 hover:text-fg">在浏览器预览</button>}
        {window.atlasDesktop?.openPath && !workspace.startsWith('ssh://') && <button title="用默认程序打开" aria-label="用默认程序打开" onClick={() => {
          const full = `${workspace.replace(/[\\/]+$/, '')}\\${file.path.replace(/\//g, '\\')}`;
          void window.atlasDesktop!.openPath(full).then((result) => { if (result !== 'opened' && result !== 'revealed') setError(`打不开：${result}`); });
        }} className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ExternalLink size={13} /></button>}
        <button onClick={() => setSelected('')} className="shrink-0 text-fg-3 hover:text-fg">关闭</button>
      </div>
      {canPreview(file.path) && mode === 'preview'
        ? MARKDOWN.test(file.path)
          ? <div className="prose-atlas min-h-0 flex-1 overflow-auto px-4 py-3 text-[13.5px]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{file.content}</ReactMarkdown></div>
          : IMAGE.test(file.path)
            ? <div className="grid min-h-0 flex-1 place-items-center overflow-auto bg-code p-3"><img src={backend.rawFileUrl(workspace, file.path)} alt={file.path} className="max-h-full max-w-full object-contain" /></div>
            // The raw endpoint already serves scriptable files sandboxed; the frame gets no same-origin access either way.
            : <iframe title={`预览 ${file.path}`} src={backend.rawFileUrl(workspace, file.path)} sandbox="allow-scripts" className="min-h-0 w-full flex-1 border-0 bg-white" />
        : file.binary ? <p className="m-0 p-4 text-[13px] text-fg-3">这是二进制文件，不能直接预览。</p>
        : <pre className="m-0 min-h-0 flex-1 overflow-auto bg-code p-3 font-mono text-[11.5px] leading-[1.6] text-fg-2">{file.content}{file.truncated && '\n\n…文件太大，只显示了前 512 KB。'}</pre>}
    </div>}
  </div>;
}
