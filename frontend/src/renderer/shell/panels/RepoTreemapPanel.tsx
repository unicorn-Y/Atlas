import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { backend } from '../../store/useAtlasStore';

interface FileRow { path: string; size: number }
interface TreeNode { path: string; name: string; kind: 'directory' | 'file'; bytes: number; files: number; children: TreeNode[] }
interface Rect { x: number; y: number; width: number; height: number }
interface Tile { node: TreeNode; rect: Rect }
type AreaMode = 'size' | 'count';

function nodeWeight(node: TreeNode, mode: AreaMode): number {
  return Math.max(1, mode === 'size' ? node.bytes : node.files);
}

function worstAspect(row: TreeNode[], shortSide: number, mode: AreaMode, unitArea: number): number {
  if (!row.length || shortSide <= 0) return Number.POSITIVE_INFINITY;
  const areas = row.map((node) => nodeWeight(node, mode) * unitArea);
  const sum = areas.reduce((total, area) => total + area, 0);
  const min = Math.min(...areas); const max = Math.max(...areas);
  return Math.max((shortSide * shortSide * max) / (sum * sum), (sum * sum) / (shortSide * shortSide * min));
}

/** Squarified treemap rows keep rectangles close to square while preserving relative area. */
function squarify(nodes: TreeNode[], bounds: Rect, mode: AreaMode): Tile[] {
  if (!nodes.length || bounds.width <= 0 || bounds.height <= 0) return [];
  const pending = [...nodes].sort((left, right) => nodeWeight(right, mode) - nodeWeight(left, mode) || left.name.localeCompare(right.name));
  const total = pending.reduce((sum, node) => sum + nodeWeight(node, mode), 0);
  const unitArea = bounds.width * bounds.height / total;
  let remaining = { ...bounds };
  const tiles: Tile[] = [];
  while (pending.length) {
    const row: TreeNode[] = [];
    const shortSide = Math.min(remaining.width, remaining.height);
    while (pending.length) {
      const next = pending[0];
      if (row.length && worstAspect([...row, next], shortSide, mode, unitArea) > worstAspect(row, shortSide, mode, unitArea)) break;
      row.push(pending.shift()!);
    }
    const rowArea = row.reduce((sum, node) => sum + nodeWeight(node, mode) * unitArea, 0);
    if (remaining.width >= remaining.height) {
      const stripWidth = Math.min(remaining.width, rowArea / remaining.height);
      let y = remaining.y;
      for (const node of row) {
        const height = Math.max(0, Math.min(remaining.y + remaining.height - y, nodeWeight(node, mode) * unitArea / Math.max(stripWidth, 1)));
        tiles.push({ node, rect: { x: remaining.x, y, width: stripWidth, height } });
        y += height;
      }
      remaining = { ...remaining, x: remaining.x + stripWidth, width: Math.max(0, remaining.width - stripWidth) };
    } else {
      const stripHeight = Math.min(remaining.height, rowArea / remaining.width);
      let x = remaining.x;
      for (const node of row) {
        const width = Math.max(0, Math.min(remaining.x + remaining.width - x, nodeWeight(node, mode) * unitArea / Math.max(stripHeight, 1)));
        tiles.push({ node, rect: { x, y: remaining.y, width, height: stripHeight } });
        x += width;
      }
      remaining = { ...remaining, y: remaining.y + stripHeight, height: Math.max(0, remaining.height - stripHeight) };
    }
  }
  return tiles;
}

function buildTree(files: FileRow[]): TreeNode {
  const root: TreeNode = { path: '', name: '仓库根目录', kind: 'directory', bytes: 0, files: 0, children: [] };
  const directories = new Map<string, TreeNode>([['', root]]);
  for (const file of files) {
    const parts = file.path.replace(/\\/g, '/').split('/').filter(Boolean);
    let current = root; let path = '';
    parts.slice(0, -1).forEach((part) => {
      path = path ? `${path}/${part}` : part;
      let child = directories.get(path);
      if (!child) {
        child = { path, name: part, kind: 'directory', bytes: 0, files: 0, children: [] };
        directories.set(path, child); current.children.push(child);
      }
      current = child;
    });
    const leaf = parts.at(-1) ?? file.path;
    current.children.push({ path: file.path, name: leaf, kind: 'file', bytes: Math.max(0, file.size), files: 1, children: [] });
  }
  const aggregate = (node: TreeNode): { bytes: number; files: number } => {
    if (node.kind === 'file') return { bytes: node.bytes, files: 1 };
    const totals = node.children.reduce((sum, child) => {
      const result = aggregate(child); return { bytes: sum.bytes + result.bytes, files: sum.files + result.files };
    }, { bytes: 0, files: 0 });
    node.bytes = totals.bytes; node.files = totals.files;
    return totals;
  };
  aggregate(root);
  return root;
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let amount = value / 1024; let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1; }
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${units[unit]}`;
}

function tileColor(node: TreeNode): string {
  if (node.kind === 'directory') return 'hsl(213 35% 43%)';
  const extension = node.name.includes('.') ? node.name.split('.').at(-1)!.toLowerCase() : '';
  const family = /^(tsx?|jsx?|py|rs|go|java|cs|cpp|h|css|html)$/.test(extension) ? 208
    : /^(md|txt|rst|adoc)$/.test(extension) ? 145
      : /^(png|jpe?g|gif|svg|webp|ico)$/.test(extension) ? 275
        : /^(json|ya?ml|toml|ini|xml|csv)$/.test(extension) ? 38 : 185;
  return `hsl(${family} 42% 42%)`;
}

export default function RepoTreemapPanel({ workspace, onChooseWorkspace, onOpenFile }: {
  workspace?: string | null; onChooseWorkspace: () => void; onOpenFile: (path: string) => void;
}) {
  const [files, setFiles] = useState<FileRow[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [zoomPath, setZoomPath] = useState('');
  const [mode, setMode] = useState<AreaMode>('size');

  const reload = useCallback(async () => {
    if (!workspace) return;
    setLoading(true); setError('');
    try {
      const result = await backend.getWorkspaceTreemap(workspace);
      setFiles(result.files); setTruncated(result.truncated); setZoomPath('');
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, [workspace, refresh]);
  useEffect(() => { setFiles([]); setZoomPath(''); void reload(); }, [reload]);

  const tree = useMemo(() => buildTree(files), [files]);
  const current = useMemo(() => zoomPath ? zoomPath.split('/').reduce<TreeNode | undefined>((node, part) => node?.children.find((item) => item.name === part && item.kind === 'directory'), tree) : tree, [tree, zoomPath]);
  const tiles = useMemo(() => squarify(current?.children ?? [], { x: 0, y: 0, width: 1000, height: 560 }, mode), [current, mode]);
  const crumbs = zoomPath ? zoomPath.split('/') : [];

  return <section className="grid gap-3" aria-label="仓库文件树图" data-repo-treemap="true">
    <header className="flex flex-wrap items-center gap-2">
      <div className="min-w-0 flex-1"><h2 className="m-0 truncate text-[13px] font-semibold text-fg">仓库文件树图</h2><p className="m-0 mt-0.5 truncate text-[10.5px] text-fg-3" title={workspace ?? undefined}>{workspace || '请选择本地工作区'}</p></div>
      <button type="button" aria-label={mode === 'size' ? '面积按文件数量排列' : '面积按文件大小排列'} onClick={() => setMode((currentMode) => currentMode === 'size' ? 'count' : 'size')} className="rounded-lg border border-line px-2 py-1 text-[11px] text-fg-2 hover:bg-hover">面积按{mode === 'size' ? '大小' : '数量'}</button>
      <button type="button" aria-label="刷新文件树图" disabled={!workspace || loading} onClick={() => setRefresh((value) => value + 1)} className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover disabled:opacity-50"><RefreshCw size={14} className={loading ? 'animate-spin' : ''} /></button>
    </header>
    {workspace && !workspace.startsWith('ssh://') && <nav className="flex min-w-0 items-center gap-1 overflow-x-auto text-[10.5px] text-fg-3" aria-label="树图缩放层级">
      <button type="button" onClick={() => setZoomPath('')} className="shrink-0 hover:text-fg">仓库</button>
      {crumbs.map((part, index) => <span key={`${index}-${part}`} className="flex shrink-0 items-center gap-1"><span aria-hidden="true">/</span><button type="button" onClick={() => setZoomPath(crumbs.slice(0, index + 1).join('/'))} className="max-w-36 truncate hover:text-fg">{part}</button></span>)}
    </nav>}
    {!workspace && <div className="rounded-xl border border-dashed border-line p-5 text-center"><p className="m-0 mb-2 text-[12px] text-fg-3">选择工作区后可按文件大小查看仓库结构。</p><button type="button" onClick={onChooseWorkspace} className="rounded-lg bg-brand px-3 py-1.5 text-[12px] text-white">选择工作区</button></div>}
    {workspace?.startsWith('ssh://') && <p role="status" className="m-0 rounded-lg bg-sunken p-3 text-[12px] text-fg-3">当前 SSH 文件列表未提供可靠的文件字节数，树图只适用于本地工作区。</p>}
    {workspace && !workspace.startsWith('ssh://') && <>
      {loading && <p role="status" className="m-0 text-[11px] text-fg-3">正在统计文件大小…</p>}
      {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft p-2.5 text-[11.5px] text-danger">读取仓库树图失败：{error}</p>}
      {!loading && !error && <>
        <p className="m-0 text-[10.5px] text-fg-3">{current?.files ?? 0} 个文件 · {formatBytes(current?.bytes ?? 0)}{mode === 'size' ? ' · 面积按文件大小' : ' · 面积按文件数量'}{truncated ? ' · 仓库较大，当前显示前 12,000 个文件' : ''}</p>
        <div className="relative h-[min(62vh,560px)] min-h-64 overflow-hidden rounded-xl border border-line bg-sunken" role="group" aria-label="文件矩形树图">
          {tiles.map(({ node, rect }) => {
            const directory = node.kind === 'directory';
            const canLabel = rect.width >= 64 && rect.height >= 28;
            const area = mode === 'size' ? formatBytes(node.bytes) : `${node.files} 个文件`;
            return <button key={node.path || node.name} type="button" title={`${node.kind === 'directory' ? '目录' : '文件'}：${node.path || '仓库根目录'} · ${formatBytes(node.bytes)} · ${node.files} 个文件`} aria-label={`${node.kind === 'directory' ? '打开目录' : '打开文件'} ${node.path || node.name}，${area}`}
              onClick={() => directory ? setZoomPath(node.path) : onOpenFile(node.path)}
              style={{ left: `${rect.x / 10}%`, top: `${rect.y / 5.6}%`, width: `${rect.width / 10}%`, height: `${rect.height / 5.6}%`, backgroundColor: tileColor(node) }}
              className="absolute overflow-hidden border border-white/50 p-1.5 text-left text-white transition-[filter] hover:z-10 hover:brightness-125 focus-visible:z-10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white">
              {canLabel && <span className="flex h-full flex-col overflow-hidden"><span className="truncate text-[10px] font-semibold leading-tight">{node.name}{directory ? ' /' : ''}</span><span className="mt-0.5 truncate text-[9px] text-white/75">{area}</span></span>}
            </button>;
          })}
          {!tiles.length && <p role="status" className="absolute inset-0 m-0 grid place-items-center text-[12px] text-fg-3">此目录没有可显示的文件。</p>}
        </div>
        {truncated && <p role="note" className="m-0 text-[10.5px] text-fg-3">性能保护：最多统计 12,000 个文件；`.git`、`node_modules`、`.venv`、`__pycache__` 和 `.atlas-checkpoints` 已跳过。</p>}
      </>}
    </>}
  </section>;
}
