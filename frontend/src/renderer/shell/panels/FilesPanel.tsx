import { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronRight, Code2, Eye, ExternalLink, File, Folder, FolderOpen, LoaderCircle, RefreshCw, RotateCcw } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { WorkspaceEntry, WorkspaceFile } from '@atlas/backend-adapter';
import { backend, useAtlasStore } from '../../store/useAtlasStore';
import { Button } from '../../ui/Button';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';
import FileHistoryMenu, { type ViewedVersion } from './FileHistoryMenu';

const GIT: Record<string, { label: string; tone: string }> = {
  M: { label: 'M', tone: 'text-brand' }, A: { label: 'A', tone: 'text-ok' }, D: { label: 'D', tone: 'text-danger' }, '?': { label: 'U', tone: 'text-ok' },
};

/** Browse the conversation's working directory and read files without leaving Atlas. */
const PREVIEWABLE = /\.(html?|pdf|svg|png|jpe?g|gif|webp)$/i;
const IMAGE = /\.(png|jpe?g|gif|webp|svg)$/i;
const MARKDOWN = /\.(md|markdown)$/i;
const FRAME = /\.(html?|pdf)$/i;
const OFFICE = /\.(docx|xlsx|pptx)$/i;
const canPreview = (path: string) => MARKDOWN.test(path) || IMAGE.test(path) || FRAME.test(path) || OFFICE.test(path);

/** 相对路径的全部祖先目录(不含文件本身),如 `a/b/c.ts` → `['a', 'a/b']`。 */
export const ancestorPaths = (file: string): string[] => {
  const segments = file.split('/').filter(Boolean);
  segments.pop();
  const out: string[] = [];
  let current = '';
  for (const segment of segments) { current = current ? `${current}/${segment}` : segment; out.push(current); }
  return out;
};

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
  const [version, setVersion] = useState<ViewedVersion | null>(null);
  const [reloads, setReloads] = useState(0);
  // C6R: 订阅内部「打开文件」请求；highlightLine 是要定位的行，codeRef 用来滚动。
  const openRequest = useAtlasStore((state) => state.fileOpenRequest);
  const [highlightLine, setHighlightLine] = useState<number | null>(null);
  const codeRef = useRef<HTMLPreElement | null>(null);

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
  // 手动浏览选中（树节点、关闭）时重置显示方式/版本/行定位；「打开文件」请求不经过这里，
  // 否则它触发的 selected 变化会在下一个 commit 把刚设置的定位清掉。
  const selectFile = (path: string) => { setSelected(path); setMode('preview'); setVersion(null); setHighlightLine(null); };
  // C6R: 消费内部「打开文件」请求:展开父目录、选中文件、切源码视图并定位行。
  useEffect(() => {
    if (!openRequest || !workspace) return;
    for (const dir of ancestorPaths(openRequest.file)) {
      setExpanded((current) => current.includes(dir) ? current : [...current, dir]);
      if (!dirs[dir]) void load(dir);
    }
    setSelected(openRequest.file);
    setVersion(null);
    setMode('code');
    setHighlightLine(openRequest.line);
  }, [openRequest]);
  // 定位请求的行:文件内容渲染后滚动到目标行(居中)。
  useEffect(() => {
    if (!highlightLine) return;
    codeRef.current?.querySelector<HTMLElement>(`[data-line="${highlightLine}"]`)?.scrollIntoView({ block: 'center' });
  }, [file, highlightLine]);

  useEffect(() => {
    if (!workspace || !selected) { setFile(null); return; }
    let stale = false;
    backend.getWorkspaceFile(workspace, selected).then((result) => { if (!stale) setFile(result); })
      .catch((exc) => { if (!stale) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { stale = true; };
  }, [workspace, selected, refreshKey, reloads]);

  if (!workspace) return <Empty title="还没有选工作目录" body="选一个文件夹，Atlas 的命令和文件操作都会在里面进行，这里也能直接浏览。"
    icon={<FolderOpen size={22} />} action={<Button variant="primary" onClick={onChooseWorkspace}><FolderOpen />选择文件夹</Button>} />;

  const toggle = (entry: WorkspaceEntry) => {
    if (entry.type === 'file') { selectFile(entry.path); return; }
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

  const restore = async () => {
    if (!workspace || !file || !version) return;
    try { await backend.restoreVersion(workspace, file.path, version.id); setVersion(null); setReloads((value) => value + 1); setError(''); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  // An earlier version only has its text; previews that load the file by URL would show the current one.
  const shown = version?.file ?? file;
  const previewing = Boolean(shown && canPreview(shown.path) && mode === 'preview' && (!version || MARKDOWN.test(shown.path)));

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
        <FileHistoryMenu workspace={workspace} path={file.path} onView={setVersion} onError={setError} />
        {canPreview(file.path) && <div className="flex shrink-0 rounded-md bg-sunken p-0.5" role="group" aria-label="显示方式">
          {(['preview', 'code'] as const).map((value) => <button key={value} onClick={() => setMode(value)} aria-pressed={mode === value} title={value === 'preview' ? '预览' : '源码'}
            className={cn('grid h-5 w-6 place-items-center rounded', mode === value ? 'bg-overlay text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}>{value === 'preview' ? <Eye size={12} /> : <Code2 size={12} />}</button>)}
        </div>}
        {PREVIEWABLE.test(file.path) && <button onClick={() => onPreview(backend.rawFileUrl(workspace, file.path))} className="shrink-0 text-fg-2 hover:text-fg">在浏览器预览</button>}
        {window.atlasDesktop?.openPath && !workspace.startsWith('ssh://') && <button title="用默认程序打开" aria-label="用默认程序打开" onClick={() => {
          const full = `${workspace.replace(/[\\/]+$/, '')}\\${file.path.replace(/\//g, '\\')}`;
          void window.atlasDesktop!.openPath(full).then((result) => { if (result !== 'opened' && result !== 'revealed') setError(`打不开：${result}`); });
        }} className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ExternalLink size={13} /></button>}
        <button onClick={() => selectFile('')} className="shrink-0 text-fg-3 hover:text-fg">关闭</button>
      </div>
      {version && <div className="flex items-center gap-2 bg-brand-soft px-3 py-1.5 text-[12px] text-fg">
        <span className="min-w-0 flex-1 truncate">正在看 {version.label} 的版本</span>
        <button onClick={() => void restore()} className="inline-flex shrink-0 items-center gap-1 font-medium hover:underline"><RotateCcw size={12} />恢复这个版本</button>
        <button onClick={() => setVersion(null)} className="shrink-0 text-fg-2 hover:text-fg">回到当前</button>
      </div>}
      {shown && previewing
        ? MARKDOWN.test(shown.path)
          ? <div className="prose-atlas min-h-0 flex-1 overflow-auto px-4 py-3 text-[13.5px]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{shown.content}</ReactMarkdown></div>
          : OFFICE.test(file.path)
            // Rendered server-side to static HTML; no scripts at all.
            ? <iframe title={`预览 ${file.path}`} src={backend.officePreviewUrl(workspace, file.path)} sandbox="" className="min-h-0 w-full flex-1 border-0 bg-white" />
          : IMAGE.test(file.path)
            ? <div className="grid min-h-0 flex-1 place-items-center overflow-auto bg-code p-3"><img src={backend.rawFileUrl(workspace, file.path)} alt={file.path} className="max-h-full max-w-full object-contain" /></div>
            // The raw endpoint already serves scriptable files sandboxed; the frame gets no same-origin access either way.
            : <iframe title={`预览 ${file.path}`} src={backend.rawFileUrl(workspace, file.path)} sandbox="allow-scripts" className="min-h-0 w-full flex-1 border-0 bg-white" />
        : shown?.binary ? <p className="m-0 p-4 text-[13px] text-fg-3">{version ? '这个版本是二进制文件，看不了内容；可以恢复后再预览。' : '这是二进制文件，不能直接预览。'}</p>
        : highlightLine && shown?.content ? <pre ref={codeRef} className="m-0 min-h-0 flex-1 overflow-auto bg-code p-3 font-mono text-[11.5px] leading-[1.6] text-fg-2">
          {shown.content.split('\n').map((text, index) => {
            const line = index + 1;
            return <span key={line} data-line={line} className={cn(line === highlightLine && 'bg-brand-soft text-fg shadow-[inset_2px_0_0_var(--brand)]')}>{`${text}\n`}</span>;
          })}
          {shown.truncated && '\n\n…文件太大，只显示了前 512 KB。'}
        </pre>
        : <pre className="m-0 min-h-0 flex-1 overflow-auto bg-code p-3 font-mono text-[11.5px] leading-[1.6] text-fg-2">{shown?.content}{shown?.truncated && '\n\n…文件太大，只显示了前 512 KB。'}</pre>}
    </div>}
  </div>;
}
