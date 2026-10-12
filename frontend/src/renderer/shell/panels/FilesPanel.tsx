import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react';
import { ChevronLeft, ChevronRight, Code2, Copy, Download, Eye, ExternalLink, File, Folder, FolderOpen, History, LoaderCircle, RefreshCw, RotateCcw, Search, X, ZoomIn, ZoomOut } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { WorkspaceEntry, WorkspaceFile } from '@atlas/backend-adapter';
import type { PlatformEditorId } from '../../../shared/ipc';
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
const XLSX = /\.xlsx$/i;
const PDF = /\.pdf$/i;
const canPreview = (path: string) => MARKDOWN.test(path) || IMAGE.test(path) || FRAME.test(path) || OFFICE.test(path);
const basename = (path: string) => path.split(/[\\/]/).filter(Boolean).at(-1) ?? path;
const absoluteWorkspacePath = (root: string, relative: string): string | null => {
  if (root.startsWith('ssh://') || relative.split(/[\\/]/).some((part) => part === '..')) return null;
  if (!relative) return root;
  const separator = root.includes('\\') ? '\\' : '/';
  const clean = relative.split(/[\\/]/).filter((part) => part && part !== '.').join(separator);
  return `${root.replace(/[\\/]+$/, '')}${separator}${clean}`;
};

interface WorkbookSheet { name: string; html: string }

/** Keep the generated workbook preview's known table structure and discard every attribute/tag. */
function workbookSheets(html: string): WorkbookSheet[] {
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  const allowed = new Set(['SECTION', 'H2', 'TABLE', 'TBODY', 'TR', 'TD']);
  const safeMarkup = (node: Node): string => {
    if (node.nodeType === Node.TEXT_NODE) return (node.textContent ?? '').replace(/[&<>"']/g, (char) => {
      if (char === '&') return '&amp;'; if (char === '<') return '&lt;'; if (char === '>') return '&gt;';
      return char === '"' ? '&quot;' : '&#39;';
    });
    if (!(node instanceof Element) || !allowed.has(node.tagName)) return '';
    const children = Array.from(node.childNodes).map(safeMarkup).join('');
    return `<${node.tagName.toLowerCase()}>${children}</${node.tagName.toLowerCase()}>`;
  };
  return Array.from(parsed.body.children).filter((node) => node.tagName === 'SECTION').map((section, index) => ({
    name: section.querySelector('h2')?.textContent?.trim() || `Sheet ${index + 1}`,
    html: safeMarkup(section),
  }));
}

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
  const [fileQuery, setFileQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Array<{ path: string; name: string; type: string }>>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const [selected, setSelected] = useState('');
  const [file, setFile] = useState<WorkspaceFile | null>(null);
  const [draft, setDraft] = useState('');
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveConflict, setSaveConflict] = useState(false);
  const [wrapCode, setWrapCode] = useState(true);
  const [codeFontSize, setCodeFontSize] = useState(11.5);
  const [error, setError] = useState('');
  const [mode, setMode] = useState<'preview' | 'code'>('preview');
  const [version, setVersion] = useState<ViewedVersion | null>(null);
  const [reloads, setReloads] = useState(0);
  const [tabs, setTabs] = useState<string[]>([]);
  const [recentlyClosed, setRecentlyClosed] = useState<string[]>([]);
  const [showClosedTabs, setShowClosedTabs] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; path: string; directory: boolean } | null>(null);
  const [lightbox, setLightbox] = useState(false);
  const [imageZoom, setImageZoom] = useState(100);
  const [pdfPage, setPdfPage] = useState(1);
  const [pdfZoom, setPdfZoom] = useState(100);
  const [pdfError, setPdfError] = useState('');
  const [sheets, setSheets] = useState<WorkbookSheet[]>([]);
  const [sheetIndex, setSheetIndex] = useState(0);
  const [workbookError, setWorkbookError] = useState('');
  const [workbookLoading, setWorkbookLoading] = useState(false);
  // C6R: 订阅内部「打开文件」请求；highlightLine 是要定位的行，codeRef 用来滚动。
  const openRequest = useAtlasStore((state) => state.fileOpenRequest);
  const [highlightLine, setHighlightLine] = useState<number | null>(null);
  const codeRef = useRef<HTMLPreElement | null>(null);
  const contextMenuRef = useRef<HTMLDivElement | null>(null);

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
  useEffect(() => {
    setExpanded([]); setSelected(''); setFile(null); setDraft(''); setEditing(false); setSaveConflict(false); setTabs([]); setRecentlyClosed([]); setShowClosedTabs(false);
    setFileQuery(''); setSearchResults([]); setSearchError('');
    setContextMenu(null); setLightbox(false); setPdfPage(1); setPdfZoom(100); setPdfError('');
  }, [workspace]);
  // 手动浏览选中（树节点、关闭）时重置显示方式/版本/行定位；「打开文件」请求不经过这里，
  // 否则它触发的 selected 变化会在下一个 commit 把刚设置的定位清掉。
  const selectFile = (path: string) => {
    setSelected(path);
    if (path) {
      setTabs((current) => current.includes(path) ? current : [...current, path]);
      setRecentlyClosed((current) => current.filter((item) => item !== path));
    }
    setFile((current) => current?.path === path ? current : null);
    setMode('preview'); setVersion(null); setHighlightLine(null); setPdfPage(1); setPdfZoom(100); setPdfError(''); setLightbox(false); setError('');
  };
  const closeFileTab = (path: string) => {
    setRecentlyClosed((current) => [path, ...current.filter((item) => item !== path)].slice(0, 10));
    const index = tabs.indexOf(path);
    const next = tabs.filter((item) => item !== path);
    setTabs(next);
    if (selected === path) {
      setSelected(next[Math.min(index, next.length - 1)] ?? '');
      setFile(null); setVersion(null); setHighlightLine(null); setMode('preview');
    }
  };
  const openContextMenu = (event: MouseEvent, path: string, directory = false) => {
    event.preventDefault();
    setContextMenu({ x: Math.max(8, Math.min(event.clientX, window.innerWidth - 240)), y: Math.max(8, Math.min(event.clientY, window.innerHeight - 180)), path, directory });
  };
  const openExternal = async (path: string) => {
    const full = workspace ? absoluteWorkspacePath(workspace, path) : null;
    if (!window.atlasDesktop?.openPath || !full) {
      setError('当前环境不能安全地把这个工作区文件交给本机程序打开。');
      return;
    }
    try {
      const result = await window.atlasDesktop.openPath(full);
      if (result !== 'opened' && result !== 'revealed') setError(`打不开：${result}`);
      else setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  const openInEditor = async (path: string, editor: PlatformEditorId) => {
    const full = workspace ? absoluteWorkspacePath(workspace, path) : null;
    if (!workspace || !full || workspace.startsWith('ssh://') || !window.atlasDesktop?.openFileInEditor) return;
    try { await window.atlasDesktop.openFileInEditor(editor, workspace, full); setError(''); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  const copyPath = async (path: string, absolute = false) => {
    const value = absolute && workspace ? absoluteWorkspacePath(workspace, path) ?? path : path;
    try { await navigator.clipboard.writeText(value); setError(''); }
    catch (exc) { setError(`复制路径失败：${exc instanceof Error ? exc.message : String(exc)}`); }
  };
  const revealInFolder = async (path: string, directory = false) => {
    if (!window.atlasDesktop?.openPath || !workspace) return;
    const parent = directory ? path : path.replace(/\\/g, '/').split('/').slice(0, -1).join('/');
    const full = absoluteWorkspacePath(workspace, parent);
    if (!full) return;
    try {
      const result = await window.atlasDesktop.openPath(full);
      if (result !== 'opened' && result !== 'revealed') setError(`打不开文件夹：${result}`);
      else setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  const downloadFile = async (path: string) => {
    if (!workspace) return;
    try {
      const response = await fetch(backend.rawFileUrl(workspace, path));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = basename(path);
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (exc) { setError(`下载失败：${exc instanceof Error ? exc.message : String(exc)}`); }
  };
  const saveDraft = async () => {
    if (!workspace || !file?.sha256 || !editing || saving) return;
    setSaving(true); setSaveConflict(false);
    try {
      await backend.saveWorkspaceFile(workspace, file.path, draft, file.sha256);
      const saved = await backend.getWorkspaceFile(workspace, file.path);
      setFile(saved); setDraft(saved.content); setEditing(false); setError('');
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (/changed on disk|磁盘上更改/i.test(message)) setSaveConflict(true);
      else setError(`保存失败：${message}`);
    } finally { setSaving(false); }
  };
  const reloadAfterConflict = async () => {
    if (!workspace || !file) return;
    try {
      const fresh = await backend.getWorkspaceFile(workspace, file.path);
      setFile(fresh); setDraft(fresh.content); setEditing(false); setSaveConflict(false); setError('');
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };
  const addFileToContext = (path: string) => {
    window.dispatchEvent(new CustomEvent('atlas:add-context-file', { detail: { path } }));
  };
  const reorderTab = (source: string, target: string) => {
    if (!source || source === target) return;
    setTabs((current) => {
      const from = current.indexOf(source); const to = current.indexOf(target);
      if (from < 0 || to < 0) return current;
      const next = [...current]; next.splice(from, 1); next.splice(to, 0, source); return next;
    });
  };
  // C6R: 消费内部「打开文件」请求:展开父目录、选中文件、切源码视图并定位行。
  useEffect(() => {
    if (!openRequest || !workspace) return;
    for (const dir of ancestorPaths(openRequest.file)) {
      setExpanded((current) => current.includes(dir) ? current : [...current, dir]);
      if (!dirs[dir]) void load(dir);
    }
    setSelected(openRequest.file);
    setTabs((current) => current.includes(openRequest.file) ? current : [...current, openRequest.file]);
    setFile((current) => current?.path === openRequest.file ? current : null);
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
    backend.getWorkspaceFile(workspace, selected).then((result) => { if (!stale) { setFile(result); setDraft(result.content); setEditing(false); setSaveConflict(false); } })
      .catch((exc) => { if (!stale) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { stale = true; };
  }, [workspace, selected, refreshKey, reloads]);

  useEffect(() => {
    if (!contextMenu) return;
    const dismiss = (event: PointerEvent) => { if (!contextMenuRef.current?.contains(event.target as Node)) setContextMenu(null); };
    const keydown = (event: KeyboardEvent) => { if (event.key === 'Escape') setContextMenu(null); };
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('keydown', keydown);
    contextMenuRef.current?.querySelector<HTMLButtonElement>('button')?.focus();
    return () => { document.removeEventListener('pointerdown', dismiss); document.removeEventListener('keydown', keydown); };
  }, [contextMenu]);

  useEffect(() => {
    if (!workspace || !selected || !XLSX.test(selected) || mode !== 'preview' || version) {
      setSheets([]); setWorkbookError(''); setWorkbookLoading(false); setSheetIndex(0);
      return;
    }
    let stale = false;
    const controller = new AbortController();
    setSheets([]); setWorkbookError(''); setWorkbookLoading(true); setSheetIndex(0);
    fetch(backend.officePreviewUrl(workspace, selected), { signal: controller.signal }).then(async (response) => {
      if (!response.ok) throw new Error(response.status === 413 ? '这个工作簿超过 10 MB 的预览上限。' : `工作簿预览失败（HTTP ${response.status}）。`);
      const parsed = workbookSheets(await response.text());
      if (!parsed.length) throw new Error('预览里没有可读取的工作表。');
      if (!stale) setSheets(parsed);
    }).catch((exc) => {
      if (!stale && !(exc instanceof DOMException && exc.name === 'AbortError')) setWorkbookError(exc instanceof Error ? exc.message : String(exc));
    }).finally(() => { if (!stale) setWorkbookLoading(false); });
    return () => { stale = true; controller.abort(); };
  }, [workspace, selected, mode, version, refreshKey, reloads]);

  useEffect(() => {
    const query = fileQuery.trim();
    if (!workspace || !query) { setSearchResults([]); setSearchError(''); setSearching(false); return; }
    let stale = false;
    setSearchResults([]);
    const timer = window.setTimeout(() => {
      setSearching(true); setSearchError('');
      backend.searchWorkspace(workspace, query, 100).then((items) => { if (!stale) setSearchResults(items); })
        .catch((exc) => { if (!stale) { setSearchResults([]); setSearchError(exc instanceof Error ? exc.message : String(exc)); } })
        .finally(() => { if (!stale) setSearching(false); });
    }, 180);
    return () => { stale = true; window.clearTimeout(timer); };
  }, [workspace, fileQuery]);

  useEffect(() => {
    if (!lightbox) return;
    const keydown = (event: KeyboardEvent) => { if (event.key === 'Escape') setLightbox(false); };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [lightbox]);

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
    const row = <button key={entry.path} role="treeitem" aria-level={depth + 1} aria-selected={selected === entry.path}
      aria-expanded={entry.type === 'dir' ? open : undefined} onContextMenu={(event) => openContextMenu(event, entry.path, entry.type === 'dir')}
      onClick={() => toggle(entry)} title={entry.path}
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
    <div className="flex items-center gap-2 rounded-lg border border-line bg-sunken px-2">
      <Search size={13} className="shrink-0 text-fg-3" />
      <input type="search" value={fileQuery} onChange={(event) => setFileQuery(event.target.value)} aria-label="搜索工作区文件名" placeholder="搜索文件名…"
        className="min-w-0 flex-1 bg-transparent py-1.5 text-[12px] text-fg outline-none placeholder:text-fg-3" />
      {searching && <LoaderCircle size={13} aria-label="正在搜索" className="spin shrink-0 text-fg-3" />}
      {fileQuery && <button type="button" aria-label="清除文件搜索" onClick={() => setFileQuery('')} className="grid size-6 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><X size={12} /></button>}
    </div>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
    {searchError && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">文件搜索失败：{searchError}</p>}
    <div className={cn('min-h-0 overflow-auto', file ? 'max-h-[42%] shrink-0' : 'flex-1')} role={fileQuery.trim() ? 'listbox' : 'tree'} aria-label={fileQuery.trim() ? '文件搜索结果' : '工作目录文件'}>
      {fileQuery.trim() ? <>
        {searching && !searchResults.length ? <p role="status" className="py-5 text-center text-[12px] text-fg-3">正在搜索工作区…</p>
          : searchResults.length ? searchResults.map((item) => <button key={item.path} type="button" role="option" aria-selected={selected === item.path} title={item.path}
            onContextMenu={(event) => openContextMenu(event, item.path)}
            onClick={() => selectFile(item.path)} className={cn('flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] hover:bg-hover', selected === item.path ? 'bg-selected text-fg' : 'text-fg-2')}>
            <File size={13} className="shrink-0 text-fg-3" /><span className="min-w-0 flex-1 truncate">{item.path}</span>
          </button>)
            : <p className="py-5 text-center text-[12px] text-fg-3">没有匹配的文件名。</p>}
        {searchResults.length >= 100 && <p className="m-0 px-2 py-1 text-[10.5px] text-fg-3">只显示前 100 个结果，请加长搜索词缩小范围。</p>}
      </> : <>
        {dirs[''] ? rows('', 0) : <p className="py-6 text-center text-[13px] text-fg-3">正在读取目录…</p>}
        {dirs[''] && !dirs[''].length && <p className="py-6 text-center text-[13px] text-fg-3">这个文件夹是空的。</p>}
      </>}
    </div>
    {(tabs.length > 0 || recentlyClosed.length > 0) && <div className="relative flex min-h-8 items-center gap-1 border-b border-line">
      <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" role="tablist" aria-label="已打开文件">
        {tabs.map((path) => <div key={path} draggable onDragStart={(event) => { event.dataTransfer.setData('text/atlas-file-tab', path); event.dataTransfer.effectAllowed = 'move'; }}
          onDragOver={(event) => { if (event.dataTransfer.types.includes('text/atlas-file-tab')) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; } }}
          onDrop={(event) => { const source = event.dataTransfer.getData('text/atlas-file-tab'); if (source) { event.preventDefault(); reorderTab(source, path); } }}
          className={cn('flex shrink-0 items-center rounded-t-md', selected === path ? 'bg-overlay text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}
          onContextMenu={(event) => openContextMenu(event, path)}>
          <button role="tab" data-file-tab={path} aria-selected={selected === path} title={path} onClick={() => selectFile(path)}
            onKeyDown={(event) => {
              if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
              event.preventDefault();
              const buttons = Array.from(event.currentTarget.closest('[role="tablist"]')?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? []);
              const index = buttons.indexOf(event.currentTarget);
              const target = buttons[(index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length];
              target?.focus();
              const path = target?.getAttribute('data-file-tab');
              if (path) selectFile(path);
            }}
            className="max-w-36 truncate px-2 py-1 text-[11.5px]">{basename(path)}</button>
          <button type="button" aria-label={`关闭 ${basename(path)}`} title={`关闭 ${basename(path)}`} onClick={() => closeFileTab(path)}
            className="mr-1 grid size-5 shrink-0 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><X size={12} /></button>
        </div>)}
      </div>
      {recentlyClosed.length > 0 && <div className="relative ml-auto shrink-0">
        <button type="button" aria-label="恢复最近关闭的文件" aria-expanded={showClosedTabs} title="恢复最近关闭的文件" onClick={() => setShowClosedTabs((value) => !value)}
          className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><History size={13} /></button>
        {showClosedTabs && <div role="menu" aria-label="最近关闭的文件" className="absolute right-0 top-full z-40 mt-1 max-h-52 w-60 overflow-auto rounded-lg border border-line bg-overlay p-1 shadow-xl">
          {recentlyClosed.map((path) => <button key={path} role="menuitem" title={path} onClick={() => {
            setRecentlyClosed((current) => current.filter((item) => item !== path)); setShowClosedTabs(false); selectFile(path);
          }} className="block w-full truncate rounded-md px-2 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">{path}</button>)}
        </div>}
      </div>}
    </div>}
    {file && <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl card-surface">
      <div className="flex items-center gap-2 px-3 py-2 text-[12px] text-fg-2 shadow-[inset_0_-1px_0_var(--line)]">
        <File size={13} className="shrink-0 text-fg-3" /><code className="min-w-0 flex-1 truncate font-mono">{file.path}</code>
        <FileHistoryMenu workspace={workspace} path={file.path} onView={setVersion} onError={setError} />
        {canPreview(file.path) && <div className="flex shrink-0 rounded-md bg-sunken p-0.5" role="group" aria-label="显示方式">
          {(['preview', 'code'] as const).map((value) => <button key={value} onClick={() => setMode(value)} aria-pressed={mode === value} title={value === 'preview' ? '预览' : '源码'}
            className={cn('grid h-5 w-6 place-items-center rounded', mode === value ? 'bg-overlay text-fg shadow-sm' : 'text-fg-3 hover:text-fg')}>{value === 'preview' ? <Eye size={12} /> : <Code2 size={12} />}</button>)}
        </div>}
        {mode === 'code' && !version && !file.binary && !file.truncated && !workspace.startsWith('ssh://') && (editing
          ? <>
            <button type="button" disabled={!file.sha256 || saving || draft === file.content} onClick={() => void saveDraft()} className="shrink-0 rounded px-2 py-1 text-[11.5px] text-brand hover:bg-hover disabled:opacity-40">{saving ? '保存中…' : '保存'}</button>
            <button type="button" onClick={() => { setDraft(file.content); setEditing(false); setSaveConflict(false); }} className="shrink-0 rounded px-2 py-1 text-[11.5px] text-fg-3 hover:bg-hover">取消</button>
          </>
          : <button type="button" onClick={() => setEditing(true)} className="shrink-0 rounded px-2 py-1 text-[11.5px] text-fg-2 hover:bg-hover">编辑</button>)}
        {mode === 'code' && <div className="flex shrink-0 items-center gap-0.5" role="group" aria-label="源码显示设置">
          <button type="button" aria-pressed={wrapCode} title="切换自动换行" onClick={() => setWrapCode((value) => !value)} className="rounded px-1.5 py-1 text-[10.5px] text-fg-3 hover:bg-hover">换行</button>
          <button type="button" aria-label="缩小源码字体" onClick={() => setCodeFontSize((size) => Math.max(9, size - 1))} className="rounded px-1 py-1 text-[11px] text-fg-3 hover:bg-hover">A−</button>
          <button type="button" aria-label="放大源码字体" onClick={() => setCodeFontSize((size) => Math.min(20, size + 1))} className="rounded px-1 py-1 text-[11px] text-fg-3 hover:bg-hover">A+</button>
        </div>}
        {PREVIEWABLE.test(file.path) && <button onClick={() => onPreview(backend.rawFileUrl(workspace, file.path))} className="shrink-0 text-fg-2 hover:text-fg">在浏览器预览</button>}
        {window.atlasDesktop?.openPath && !workspace.startsWith('ssh://') && <button title="用默认程序打开" aria-label="用默认程序打开" onClick={() => {
          void openExternal(file.path);
        }} className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><ExternalLink size={13} /></button>}
        <button type="button" title="复制相对路径" aria-label="复制相对路径" onClick={() => void copyPath(file.path)} className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><Copy size={13} /></button>
        <button type="button" title="下载文件" aria-label="下载文件" onClick={() => downloadFile(file.path)} className="grid size-6 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg"><Download size={13} /></button>
        <button onClick={() => closeFileTab(file.path)} className="shrink-0 text-fg-3 hover:text-fg">关闭</button>
      </div>
      {version && <div className="flex items-center gap-2 bg-brand-soft px-3 py-1.5 text-[12px] text-fg">
        <span className="min-w-0 flex-1 truncate">正在看 {version.label} 的版本</span>
        <button onClick={() => void restore()} className="inline-flex shrink-0 items-center gap-1 font-medium hover:underline"><RotateCcw size={12} />恢复这个版本</button>
        <button onClick={() => setVersion(null)} className="shrink-0 text-fg-2 hover:text-fg">回到当前</button>
      </div>}
      {saveConflict && <div role="alert" className="flex items-center gap-2 bg-danger-soft px-3 py-2 text-[12px] text-danger">
        <span className="min-w-0 flex-1">文件已在磁盘上更改。你的编辑仍保留；重新加载会丢弃本地草稿。</span>
        <button type="button" onClick={() => void reloadAfterConflict()} className="shrink-0 underline">加载磁盘版本</button>
      </div>}
      {shown && previewing
        ? MARKDOWN.test(shown.path)
          ? <div className="prose-atlas min-h-0 flex-1 overflow-auto px-4 py-3 text-[13.5px]"><ReactMarkdown remarkPlugins={[remarkGfm]}>{shown.content}</ReactMarkdown></div>
          : OFFICE.test(file.path)
            ? XLSX.test(file.path)
              ? <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                {sheets.length > 1 && <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-line px-2 py-1" role="tablist" aria-label="工作表">
                  {sheets.map((sheet, index) => <button key={`${index}:${sheet.name}`} role="tab" aria-selected={sheetIndex === index} onClick={() => setSheetIndex(index)}
                    className={cn('shrink-0 rounded-md px-2 py-1 text-[11.5px]', sheetIndex === index ? 'bg-overlay text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}>{sheet.name}</button>)}
                </div>}
                {workbookLoading ? <p role="status" className="m-0 p-4 text-[12.5px] text-fg-3">正在读取工作簿…</p>
                  : workbookError ? <div role="alert" className="p-4 text-[12.5px] text-danger">{workbookError}</div>
                    : sheets[sheetIndex] && <iframe title={`预览工作表 ${sheets[sheetIndex].name}`} key={`${file.path}:${sheetIndex}`} sandbox=""
                      srcDoc={`<!doctype html><html><head><meta charset="utf-8"><style>body{font:14px system-ui,sans-serif;margin:1rem;color:#20242a}table{border-collapse:collapse;margin:1rem 0;width:100%}td{border:1px solid #bbb;padding:.4rem;white-space:pre-wrap}</style></head><body>${sheets[sheetIndex].html}</body></html>`}
                      className="min-h-0 w-full flex-1 border-0 bg-white" />}
              </div>
              // Rendered server-side to static HTML; scripts are disabled in the frame.
              : <iframe title={`预览 ${file.path}`} src={backend.officePreviewUrl(workspace, file.path)} onError={() => setError('办公文档预览加载失败；可以用外部程序打开。')} sandbox="" className="min-h-0 w-full flex-1 border-0 bg-white" />
          : PDF.test(file.path) && !version
            ? <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="flex shrink-0 items-center gap-1.5 border-b border-line px-2 py-1" role="group" aria-label="PDF 页面与缩放">
                <button type="button" aria-label="上一页" title="上一页" disabled={pdfPage <= 1} onClick={() => { setPdfPage((page) => Math.max(1, page - 1)); setPdfError(''); }}
                  className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:opacity-40"><ChevronLeft size={14} /></button>
                <label className="flex items-center gap-1 text-[11.5px] text-fg-3">页码
                  <input type="number" min={1} value={pdfPage} onChange={(event) => { setPdfPage(Math.max(1, Number(event.target.value) || 1)); setPdfError(''); }}
                    aria-label="PDF 页码" className="w-14 rounded border border-line bg-sunken px-1.5 py-1 text-center text-fg" />
                </label>
                <button type="button" aria-label="下一页" title="下一页" onClick={() => { setPdfPage((page) => page + 1); setPdfError(''); }}
                  className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover"><ChevronRight size={14} /></button>
                <span className="mx-1 h-4 border-l border-line" />
                <button type="button" aria-label="缩小 PDF" title="缩小" disabled={pdfZoom <= 50} onClick={() => setPdfZoom((zoom) => Math.max(50, zoom - 25))}
                  className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:opacity-40"><ZoomOut size={14} /></button>
                <span aria-live="polite" className="min-w-10 text-center text-[11.5px] text-fg-3">{pdfZoom}%</span>
                <button type="button" aria-label="放大 PDF" title="放大" disabled={pdfZoom >= 300} onClick={() => setPdfZoom((zoom) => Math.min(300, zoom + 25))}
                  className="grid size-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:opacity-40"><ZoomIn size={14} /></button>
                <span className="min-w-0 flex-1" />
                <button type="button" onClick={() => downloadFile(file.path)} className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11.5px] text-fg-2 hover:bg-hover"><Download size={12} />下载</button>
              </div>
              {pdfError && <div role="alert" className="flex items-center gap-2 px-3 py-2 text-[12px] text-danger">{pdfError}
                <button type="button" onClick={() => void openExternal(file.path)} className="shrink-0 underline">用外部程序打开</button>
              </div>}
              <iframe key={`${file.path}:${pdfPage}:${pdfZoom}`} title={`PDF 预览 ${file.path}，第 ${pdfPage} 页`} src={`${backend.rawFileUrl(workspace, file.path)}#page=${pdfPage}&zoom=${pdfZoom}`}
                onError={() => setPdfError('内置 PDF 查看器无法打开此文件。')}
                onLoad={() => setPdfError('')} sandbox="allow-scripts" className="min-h-0 w-full flex-1 border-0 bg-white" />
            </div>
          : IMAGE.test(file.path)
            ? <button type="button" onClick={() => { setImageZoom(100); setLightbox(true); }} aria-label={`放大预览图片 ${file.path}`}
              className="grid min-h-0 flex-1 place-items-center overflow-auto bg-code p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
              <img src={backend.rawFileUrl(workspace, file.path)} alt={file.path} onError={() => setError('图片预览加载失败。')} className="max-h-full max-w-full object-contain" />
            </button>
            // The raw endpoint already serves scriptable files sandboxed; the frame gets no same-origin access either way.
            : <iframe title={`预览 ${file.path}`} src={backend.rawFileUrl(workspace, file.path)} onError={() => setError('文件预览加载失败。')} sandbox="allow-scripts" className="min-h-0 w-full flex-1 border-0 bg-white" />
        : shown?.binary ? <p className="m-0 p-4 text-[13px] text-fg-3">{version ? '这个版本是二进制文件，看不了内容；可以恢复后再预览。' : '这是二进制文件，不能直接预览。'}</p>
        : editing && !version ? <textarea aria-label={`编辑 ${file.path}`} spellCheck={false} value={draft} onChange={(event) => setDraft(event.target.value)}
          wrap={wrapCode ? 'soft' : 'off'} style={{ fontSize: `${codeFontSize}px`, whiteSpace: wrapCode ? 'pre-wrap' : 'pre' }}
          className="m-0 min-h-0 flex-1 resize-none overflow-auto bg-code p-3 font-mono leading-[1.6] text-fg-2 outline-none" />
        : highlightLine && shown?.content ? <pre ref={codeRef} style={{ fontSize: `${codeFontSize}px`, whiteSpace: wrapCode ? 'pre-wrap' : 'pre' }} className="m-0 min-h-0 flex-1 overflow-auto bg-code p-3 font-mono leading-[1.6] text-fg-2">
          {shown.content.split('\n').map((text, index) => {
            const line = index + 1;
            return <span key={line} data-line={line} className={cn(line === highlightLine && 'bg-brand-soft text-fg shadow-[inset_2px_0_0_var(--brand)]')}>{`${text}\n`}</span>;
          })}
          {shown.truncated && '\n\n…文件太大，只显示了前 512 KB。'}
        </pre>
        : <pre style={{ fontSize: `${codeFontSize}px`, whiteSpace: wrapCode ? 'pre-wrap' : 'pre' }} className="m-0 min-h-0 flex-1 overflow-auto bg-code p-3 font-mono leading-[1.6] text-fg-2">{shown?.content}{shown?.truncated && '\n\n…文件太大，只显示了前 512 KB。'}</pre>}
    </div>}
    {contextMenu && <div ref={contextMenuRef} data-file-context-menu role="menu" aria-label={`${contextMenu.path} 文件操作`}
      onContextMenu={(event) => event.preventDefault()} style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 80 }}
      className="min-w-52 rounded-lg border border-line bg-overlay p-1 shadow-xl">
      {!contextMenu.directory && <button type="button" role="menuitem" onClick={() => { selectFile(contextMenu.path); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">在 Atlas 中打开</button>}
      {!contextMenu.directory && <button type="button" role="menuitem" onClick={() => { addFileToContext(contextMenu.path); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">加入消息上下文</button>}
      {!contextMenu.directory && window.atlasDesktop?.openPath && !workspace.startsWith('ssh://') && <button type="button" role="menuitem" onClick={() => { void openExternal(contextMenu.path); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">在外部程序中打开</button>}
      {!contextMenu.directory && window.atlasDesktop?.openFileInEditor && !workspace.startsWith('ssh://') && (['vscode', 'cursor', 'zed', 'idea', 'pycharm'] as const).map((editor) => <button key={editor} type="button" role="menuitem" onClick={() => { void openInEditor(contextMenu.path, editor); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">在 {{ vscode: 'VS Code', cursor: 'Cursor', zed: 'Zed', idea: 'IntelliJ IDEA', pycharm: 'PyCharm' }[editor]} 中打开</button>)}
      {window.atlasDesktop?.openPath && !workspace.startsWith('ssh://') && <button type="button" role="menuitem" onClick={() => { void revealInFolder(contextMenu.path, contextMenu.directory); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">在文件管理器中显示</button>}
      <button type="button" role="menuitem" onClick={() => { void copyPath(contextMenu.path); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">复制相对路径</button>
      {!workspace.startsWith('ssh://') && <button type="button" role="menuitem" onClick={() => { void copyPath(contextMenu.path, true); setContextMenu(null); }}
        className="block w-full rounded-md px-2.5 py-1.5 text-left text-[12px] text-fg-2 hover:bg-hover hover:text-fg">复制绝对路径</button>}
    </div>}
    {lightbox && file && IMAGE.test(file.path) && <div role="dialog" aria-modal="true" aria-label={`图片预览 ${file.path}`}
      onMouseDown={(event) => { if (event.target === event.currentTarget) setLightbox(false); }}
      className="fixed inset-0 z-[90] flex flex-col bg-black/90 p-3 text-white">
      <div className="flex shrink-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[12.5px]" title={file.path}>{file.path}</span>
        <button type="button" aria-label="缩小图片" title="缩小" disabled={imageZoom <= 25} onClick={() => setImageZoom((zoom) => Math.max(25, zoom - 25))}
          className="grid size-8 place-items-center rounded-md text-white hover:bg-white/15 disabled:opacity-40"><ZoomOut size={16} /></button>
        <span aria-live="polite" className="min-w-12 text-center text-[12px]">{imageZoom}%</span>
        <button type="button" aria-label="放大图片" title="放大" disabled={imageZoom >= 400} onClick={() => setImageZoom((zoom) => Math.min(400, zoom + 25))}
          className="grid size-8 place-items-center rounded-md text-white hover:bg-white/15 disabled:opacity-40"><ZoomIn size={16} /></button>
        <button type="button" onClick={() => downloadFile(file.path)} className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-[12px] text-white hover:bg-white/15"><Download size={14} />下载</button>
        <button type="button" aria-label="关闭图片预览" title="关闭" autoFocus onClick={() => setLightbox(false)} className="grid size-8 place-items-center rounded-md text-white hover:bg-white/15"><X size={16} /></button>
      </div>
      <div className="grid min-h-0 flex-1 place-items-center overflow-auto p-4">
        <img src={backend.rawFileUrl(workspace, file.path)} alt={file.path} draggable={false}
          style={{ transform: `scale(${imageZoom / 100})`, transformOrigin: 'center center' }} className="max-h-[82vh] max-w-[90vw] object-contain" />
      </div>
      <p className="m-0 shrink-0 text-center text-[11px] text-white/70">按 Esc 关闭；可用缩放按钮放大和缩小。</p>
    </div>}
  </div>;
}
