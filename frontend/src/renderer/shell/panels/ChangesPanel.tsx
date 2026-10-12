import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react';
import { Check, ChevronDown, ChevronRight, ChevronUp, ExternalLink, FileDiff, History, LoaderCircle, MessageSquarePlus, Pencil, RotateCcw, Search, Send, ThumbsDown, ThumbsUp, X } from 'lucide-react';
import type { RunChangeFile, RunDiagnosticsFile } from '@atlas/backend-adapter';
import { backend, useAtlasStore } from '../../store/useAtlasStore';
import { api, relativeTime } from '../../services/api';
import { DiagnosticsList, SeverityDots } from '../../components/diagnostics';
import type { LspDiagnosticItem } from '../../components/timeline';
import { shortPath } from '../../components/timeline';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';

/** A note on one line of the diff, sent to Atlas together with the others. */
interface LineComment { id: string; path: string; line: number | null; side: 'new' | 'old'; code: string; text: string }

interface Checkpoint { id: string; workspace: string; created_at: string; run_id?: string | null; files: Array<{ path: string; directory?: boolean }> }
interface RunChangeHunk {
  id: string; old_start: number; old_count: number; new_start: number; new_count: number;
  status: 'pending' | 'accepted' | 'rejected'; reviewable: boolean;
}
type RunChange = RunChangeFile & { root?: string; relative_path?: string; diff_hash?: string; hunks?: RunChangeHunk[] };
interface FileRestoreTarget { id: string; workspace: string; path: string }

const STATUS: Record<RunChangeFile['status'], { label: string; tone: string }> = {
  added: { label: '新增', tone: 'text-ok' },
  modified: { label: '修改', tone: 'text-brand' },
  deleted: { label: '删除', tone: 'text-danger' },
};

const normalizePath = (path: string) => path.replace(/\\/g, '/').replace(/\/$/, '');
const changeRoot = (file: RunChange) => file.root ?? file.workspace;
const changeKey = (file: RunChange) => `${changeRoot(file)}\0${normalizePath(file.path)}`;
const workspaceName = (workspace: string) => workspace.replace(/[\\/]+$/, '').split(/[\\/]/).filter(Boolean).pop() ?? '';
function samePath(left: string, right: string): boolean {
  const a = normalizePath(left);
  const b = normalizePath(right);
  return /^[A-Za-z]:\//.test(a) || /^[A-Za-z]:\//.test(b) ? a.toLowerCase() === b.toLowerCase() : a === b;
}

/** What this run changed on disk, and the snapshots that can put it back. */
export default function ChangesPanel({ runId, runStatus, apiBaseUrl, connected, onToast, onAsk }: {
  runId?: string; runStatus?: string; apiBaseUrl: string; connected: boolean; onToast: (text: string) => void; onAsk?: (text: string) => void;
}) {
  const [comments, setComments] = useState<LineComment[]>([]);
  useEffect(() => setComments([]), [runId]);
  const send = () => {
    if (!onAsk || !comments.length) return;
    const body = comments.map((comment, index) => `${index + 1}. \`${comment.path}${comment.line ? `:${comment.line}` : ''}\`${comment.side === 'old' ? '（删掉的那行）' : ''}\n   代码：\`${comment.code.trim().slice(0, 200)}\`\n   意见：${comment.text}`).join('\n');
    onAsk(`我看了这次的改动，有 ${comments.length} 处要调整：\n\n${body}\n\n按这些意见修改，改完说明每一处怎么处理的。`);
    setComments([]);
    onToast('评论已发给 Atlas');
  };
  const editComment = (id: string, text: string) => setComments((current) => current.map((comment) => comment.id === id ? { ...comment, text } : comment));
  const [files, setFiles] = useState<RunChange[] | null>(null);
  const [open, setOpen] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [changesReload, setChangesReload] = useState(0);
  const [restoreTargets, setRestoreTargets] = useState<Record<string, FileRestoreTarget>>({});
  const [restoreNotice, setRestoreNotice] = useState('');
  const [restoreConfirm, setRestoreConfirm] = useState('');
  const [restoringFile, setRestoringFile] = useState('');
  const [restoreError, setRestoreError] = useState('');
  const [hunkBusyId, setHunkBusyId] = useState('');
  const [hunkError, setHunkError] = useState('');
  useEffect(() => {
    if (!runId || !connected) { setFiles([]); setError(''); return; }
    let stale = false;
    setFiles(null);
    setError('');
    backend.getRunChanges(runId)
      .then((result) => { if (!stale) { setFiles(result as RunChange[]); setOpen(result.length === 1 ? [result[0].path] : []); } })
      .catch((exc) => { if (!stale) { setFiles([]); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [runId, runStatus, connected, changesReload]);

  // A run's earliest checkpoint containing a changed path is the version from before
  // that file was first edited. Only files with that concrete snapshot get a restore action.
  useEffect(() => {
    if (!runId || !connected || !files?.length) {
      setRestoreTargets({});
      setRestoreNotice('');
      return;
    }
    let stale = false;
    setRestoreTargets({});
    setRestoreNotice('');
    setRestoreConfirm('');
    setRestoreError('');
    const roots = [...new Set(files.map((file) => changeRoot(file)).filter(Boolean))];
    void Promise.all(roots.map(async (workspace) => {
      const params = new URLSearchParams({ workspace, run_id: runId });
      try {
        return { workspace, items: await api<Checkpoint[]>(apiBaseUrl, `/api/checkpoints?${params}`) };
      } catch {
        return { workspace, items: null };
      }
    })).then((groups) => {
      if (stale) return;
      const targets: Record<string, FileRestoreTarget> = {};
      const failedRoot = groups.some((group) => group.items === null);
      for (const file of files) {
        const workspace = changeRoot(file);
        const group = groups.find((item) => samePath(item.workspace, workspace));
        if (!group?.items) continue;
        const rootName = workspaceName(workspace);
        const candidates = new Set<string>();
        for (const checkpoint of group.items) {
          if (checkpoint.run_id && checkpoint.run_id !== runId) continue;
          for (const saved of checkpoint.files) {
            if (saved.directory) continue;
            if (samePath(saved.path, file.path) || (rootName && samePath(file.path, `${rootName}/${saved.path}`))) {
              candidates.add(normalizePath(saved.path));
            }
          }
        }
        // Multi-root run-change rows include the root's basename in their display path.
        // If both that path and its stripped form exist, don't guess which file to mutate.
        if (candidates.size !== 1) continue;
        const path = [...candidates][0];
        const checkpoint = group.items
          .filter((item) => (!item.run_id || item.run_id === runId)
            && item.files.some((saved) => !saved.directory && samePath(saved.path, path)))
          .sort((a, b) => a.created_at.localeCompare(b.created_at))[0];
        if (checkpoint) targets[changeKey(file)] = { id: checkpoint.id, workspace, path };
      }
      setRestoreTargets(targets);
      if (failedRoot) setRestoreNotice('部分工作目录的任务前快照无法读取；没有安全快照的文件不会提供恢复操作。');
      else if (Object.keys(targets).length < files.length) setRestoreNotice('没有找到部分文件的任务前快照；这些文件不会提供逐文件恢复操作。');
    });
    return () => { stale = true; };
  }, [apiBaseUrl, connected, files, runId]);
  // 这次运行改过的文件当前的 LSP 诊断。路径统一成正斜杠再对上；拉不到就不显示徽标。
  const [diagnostics, setDiagnostics] = useState<Record<string, RunDiagnosticsFile>>({});
  useEffect(() => {
    if (!runId || !connected) { setDiagnostics({}); return; }
    let stale = false;
    backend.getRunDiagnostics(runId)
      .then((result) => { if (!stale) setDiagnostics(Object.fromEntries(result.files.map((file) => [normalizePath(file.path), file]))); })
      .catch(() => { if (!stale) setDiagnostics({}); });
    return () => { stale = true; };
  }, [runId, runStatus, connected]);

  const toggle = (path: string) => setOpen((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path]);
  const additions = files?.reduce((sum, file) => sum + file.additions, 0) ?? 0;
  const deletions = files?.reduce((sum, file) => sum + file.deletions, 0) ?? 0;
  const restoreFile = async (file: RunChange) => {
    const key = changeKey(file);
    const target = restoreTargets[key];
    if (!target || !runId || restoringFile) return;
    if (restoreConfirm !== key) { setRestoreConfirm(key); return; }
    setRestoreConfirm('');
    setRestoringFile(key);
    setRestoreError('');
    try {
      await backend.restoreVersion(target.workspace, target.path, `checkpoint:${target.id}`);
      onToast(`已恢复 ${file.path} 到本次任务前的版本`);
      setChangesReload((value) => value + 1);
    } catch (exc) {
      setRestoreError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRestoringFile('');
    }
  };
  const reviewHunk = async (file: RunChange, hunk: RunChangeHunk, action: 'accept' | 'reject') => {
    if (!runId || !file.diff_hash || !hunk.reviewable || hunkBusyId) return;
    setHunkBusyId(hunk.id);
    setHunkError('');
    try {
      await api(apiBaseUrl, `/api/runs/${encodeURIComponent(runId)}/changes/hunks/review`, {
        method: 'POST',
        json: { workspace: changeRoot(file), path: file.relative_path ?? file.path,
          hunk_id: hunk.id, action, expected_diff_hash: file.diff_hash },
      });
      setChangesReload((value) => value + 1);
    } catch (exc) {
      setHunkError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setHunkBusyId('');
    }
  };

  return <div className="grid gap-6">
    <section>
      <h3 className="m-0 mb-2 flex items-center gap-2 text-[12.5px] font-semibold text-fg-2">
        这次的改动{files && files.length > 0 && <span className="font-normal tabular-nums text-fg-3">{files.length} 个文件 <span className="text-ok">+{additions}</span> <span className="text-danger">−{deletions}</span></span>}
      </h3>
      {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
      {hunkError && <div role="alert" className="mb-2 flex items-center gap-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger"><span className="min-w-0 flex-1">Diff 审核未完成：{hunkError}</span><button type="button" onClick={() => setChangesReload((value) => value + 1)} className="shrink-0 underline underline-offset-2">重新载入</button></div>}
      {restoreError && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">逐文件恢复失败：{restoreError}</p>}
      {restoreNotice && <p role="status" className="m-0 mb-2 rounded-lg bg-sunken px-3 py-2 text-[12px] text-fg-3">{restoreNotice}</p>}
      {files === null ? <p className="py-6 text-center text-[13px] text-fg-3">正在读取改动…</p>
        : files.length ? <div className="grid gap-1.5">{files.map((file) => {
          const expanded = open.includes(file.path);
          const fileDiagnostics = diagnostics[normalizePath(file.path)];
          const fileKey = changeKey(file);
          const restoreTarget = restoreTargets[fileKey];
          const active = useAtlasStore.getState();
          const activeConversation = active.conversations.find((item) => item.id === active.activeConversationId);
          const activeWorkspace = activeConversation?.worktree_path ?? activeConversation?.workspace ?? '';
          const relativePath = file.relative_path ?? file.path;
          const openPath = samePath(changeRoot(file), activeWorkspace) && file.status !== 'deleted'
            ? `${activeWorkspace.replace(/[\\/]+$/, '')}${activeWorkspace.includes('\\') ? '\\' : '/'}${relativePath.replace(/[\\/]/g, activeWorkspace.includes('\\') ? '\\' : '/')}`
            : undefined;
          return <div key={`${file.workspace}:${file.path}`} className="overflow-hidden rounded-xl card-surface">
            <button onClick={() => toggle(file.path)} aria-expanded={expanded} className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] hover:bg-hover">
              <ChevronRight size={13} className={cn('shrink-0 text-fg-3 transition-transform', expanded && 'rotate-90')} />
              <span aria-label={`文件状态：${STATUS[file.status]?.label ?? file.status}`} className={cn('shrink-0 rounded-full bg-sunken px-2 py-0.5 text-[11px]', STATUS[file.status]?.tone)}>{STATUS[file.status]?.label ?? file.status}</span>
              <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg" title={file.path}>{shortPath(file.path)}</code>
              {fileDiagnostics && fileDiagnostics.count > 0 && <span title="LSP 诊断" className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-sunken px-2 py-0.5 text-[11px] tabular-nums text-fg-2">
                <SeverityDots diagnostics={fileDiagnostics.diagnostics as LspDiagnosticItem[]} />{fileDiagnostics.count} 个问题
              </span>}
              <span className="shrink-0 text-[11.5px] tabular-nums"><span className="text-ok">+{file.additions}</span> <span className="text-danger">−{file.deletions}</span></span>
            </button>
            {expanded && <>
              <DiffView diff={file.diff} truncated={file.truncated} path={file.path} openPath={openPath} hunks={file.hunks}
                busyHunkId={hunkBusyId} onReviewHunk={(hunk, action) => void reviewHunk(file, hunk, action)} comments={onAsk ? comments.filter((comment) => comment.path === file.path) : undefined}
                onAdd={(comment) => setComments((current) => [...current, { ...comment, id: `${Date.now()}-${current.length}` }])} onEdit={editComment}
                onRemove={(id) => setComments((current) => current.filter((comment) => comment.id !== id))} />
              {restoreTarget && <div className="flex items-center gap-2 border-t border-line px-3 py-2">
                <button type="button" disabled={Boolean(restoringFile)} onClick={() => void restoreFile(file)}
                  className={cn('inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[12px] disabled:opacity-50', restoreConfirm === fileKey ? 'bg-danger-soft text-danger' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
                  {restoringFile === fileKey ? <LoaderCircle size={12} className="spin" /> : <RotateCcw size={12} />}
                  {restoringFile === fileKey ? '正在恢复…' : restoreConfirm === fileKey ? '确认恢复此文件' : '恢复此文件到任务前'}
                </button>
                {restoreConfirm === fileKey && <span role="status" className="text-[11.5px] text-fg-3">只还原这个文件，会先保存当前版本供文件历史恢复。</span>}
              </div>}
              {fileDiagnostics && fileDiagnostics.diagnostics.length > 0 && <div className="border-t border-line px-3 py-2">
                <p className="m-0 mb-1.5 text-[11.5px] text-fg-3">LSP 诊断（当前共 {fileDiagnostics.count} 个）</p>
                <DiagnosticsList diagnostics={fileDiagnostics.diagnostics as LspDiagnosticItem[]} />
                {fileDiagnostics.count > fileDiagnostics.diagnostics.length && <p className="m-0 mt-1 text-[11.5px] text-fg-3">仅显示前 20 条</p>}
              </div>}
            </>}
          </div>;
        })}</div>
        : <Empty title={runId ? '这次没有改文件' : '还没有开始'} body={runId ? 'Atlas 这次只读了东西、运行了命令，或者直接回答了。' : '发出一个任务后，改过的文件会列在这里。'} />}
      {comments.length > 0 && <div className="sticky bottom-0 mt-2 flex items-center gap-2 rounded-xl bg-brand-soft px-3 py-2 text-[12.5px] text-fg">
        <MessageSquarePlus size={14} className="shrink-0 text-brand" /><span className="flex-1">{comments.length} 条评论</span>
        <button onClick={() => setComments([])} className="text-fg-3 hover:text-fg">清空</button>
        <button onClick={send} className="primary-fill inline-flex h-7 items-center gap-1 rounded-lg px-2.5"><Send size={12} />发给 Atlas 修改</button>
      </div>}
    </section>
    <Checkpoints apiBaseUrl={apiBaseUrl} connected={connected} onToast={onToast} runId={runId} refreshKey={`${runId}:${runStatus}`} />
  </div>;
}

type DiffLine = { text: string; kind: 'add' | 'del' | 'ctx' | 'hunk'; oldNo: number | null; newNo: number | null; hunkIndex: number };
interface DiffSearchHit { lineIndex: number; start: number; end: number }

/** 诊断表和改动清单都按正斜杠对齐路径，避免 \ 与 / 混写对不上。 */
/** Unified diff lines with their old/new line numbers, read from the @@ hunk headers. */
function numberLines(diff: string): DiffLine[] {
  let oldNo = 0, newNo = 0;
  let hunkIndex = -1;
  const raw = diff.replace(/\n$/, '').split('\n');
  let skippedHeaders = 0;
  return raw.filter((line) => {
    if (skippedHeaders < 2 && (line.startsWith('--- ') || line.startsWith('+++ '))) { skippedHeaders += 1; return false; }
    return true;
  }).map((text) => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) { oldNo = Number(hunk[1]); newNo = Number(hunk[2]); hunkIndex += 1; return { text, kind: 'hunk', oldNo: null, newNo: null, hunkIndex }; }
    // "\ No newline at end of file" describes the line above; it is not a line of the file.
    if (text.startsWith('\\')) return { text, kind: 'hunk', oldNo: null, newNo: null, hunkIndex };
    if (text.startsWith('+')) return { text, kind: 'add', oldNo: null, newNo: newNo++, hunkIndex };
    if (text.startsWith('-')) return { text, kind: 'del', oldNo: oldNo++, newNo: null, hunkIndex };
    return { text, kind: 'ctx', oldNo: oldNo++, newNo: newNo++, hunkIndex };
  });
}

/** 统一 diff 渲染（含行号）；InitDialog 复用它来预览 AGENTS.md 的提案差异。 */
export function DiffView({ diff, truncated, path, openPath, hunks, busyHunkId, onReviewHunk, comments, onAdd, onEdit, onRemove }: {
  diff: string; truncated?: boolean; path: string; openPath?: string; hunks?: RunChangeHunk[]; busyHunkId?: string;
  onReviewHunk?: (hunk: RunChangeHunk, action: 'accept' | 'reject') => void; comments?: LineComment[];
  onAdd: (comment: Omit<LineComment, 'id'>) => void; onEdit: (id: string, text: string) => void; onRemove: (id: string) => void;
}) {
  const lines = useMemo(() => numberLines(diff), [diff]);
  const [draft, setDraft] = useState<{ index: number; text: string } | null>(null);
  const [editing, setEditing] = useState<{ id: string; text: string } | null>(null);
  const [externalError, setExternalError] = useState('');
  const [searchText, setSearchText] = useState('');
  const [activeSearchHit, setActiveSearchHit] = useState(0);
  const searchInputId = useId();
  const searchHitRefs = useRef<Array<HTMLElement | null>>([]);
  const commentable = Boolean(comments);
  const searchHits = useMemo<DiffSearchHit[]>(() => {
    if (!searchText) return [];
    const escaped = searchText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const matcher = new RegExp(escaped, 'giu');
    const hits: DiffSearchHit[] = [];
    lines.forEach((line, lineIndex) => {
      if (line.kind === 'hunk') return;
      const content = line.text.slice(1);
      for (const match of content.matchAll(matcher)) {
        if (match.index !== undefined) hits.push({ lineIndex, start: match.index, end: match.index + match[0].length });
      }
    });
    return hits;
  }, [lines, searchText]);
  const searchHitsByLine = useMemo(() => {
    const grouped = new Map<number, number[]>();
    searchHits.forEach((hit, hitIndex) => {
      const indexes = grouped.get(hit.lineIndex) ?? [];
      indexes.push(hitIndex);
      grouped.set(hit.lineIndex, indexes);
    });
    return grouped;
  }, [searchHits]);
  const moveSearchHit = (direction: -1 | 1) => {
    if (!searchHits.length) return;
    setActiveSearchHit((current) => (current + direction + searchHits.length) % searchHits.length);
  };
  useEffect(() => {
    if (searchText && searchHits.length) searchHitRefs.current[activeSearchHit]?.scrollIntoView({ block: 'center', inline: 'nearest' });
  }, [activeSearchHit, searchHits.length, searchText]);
  useEffect(() => {
    setActiveSearchHit((current) => searchHits.length ? Math.min(current, searchHits.length - 1) : 0);
  }, [searchHits.length]);
  const save = () => {
    if (!draft?.text.trim()) { setDraft(null); return; }
    const line = lines[draft.index];
    onAdd({ path, line: line.newNo ?? line.oldNo, side: line.kind === 'del' ? 'old' : 'new', code: line.text.slice(1), text: draft.text.trim() });
    setDraft(null);
  };
  return <div className="max-h-96 overflow-auto bg-code py-2 font-mono text-[11.5px] leading-[1.6] shadow-[inset_0_1px_0_var(--line)]">
    {openPath && window.atlasDesktop?.openPath && <div className="mb-1 flex justify-end px-3 font-sans">
      <button type="button" onClick={() => { setExternalError(''); void window.atlasDesktop!.openPath(openPath).then((result) => { if (result !== 'opened' && result !== 'revealed') setExternalError(`无法打开文件：${result}`); }).catch((error) => setExternalError(error instanceof Error ? error.message : String(error))); }}
        className="inline-flex min-h-7 items-center gap-1.5 rounded-md px-2 text-[11.5px] text-fg-2 hover:bg-hover hover:text-fg"><ExternalLink size={12} />用默认编辑器打开</button>
    </div>}
    {externalError && <p role="alert" className="mx-3 my-1 rounded-md bg-danger-soft px-2 py-1 font-sans text-[11.5px] text-danger">{externalError}</p>}
    <div role="search" aria-label="在当前文件改动中搜索" className="mb-1 flex flex-wrap items-center gap-1.5 px-3 font-sans">
      <label htmlFor={searchInputId} className="sr-only">搜索当前文件改动</label>
      <div className="flex h-7 min-w-32 flex-1 items-center gap-1.5 rounded-md bg-sunken px-2 shadow-[inset_0_0_0_1px_var(--line)] focus-within:shadow-[inset_0_0_0_1px_var(--brand)]">
        <Search size={12} aria-hidden="true" className="shrink-0 text-fg-3" />
        <input id={searchInputId} type="search" value={searchText} autoComplete="off" spellCheck={false}
          onChange={(event) => { setSearchText(event.target.value); setActiveSearchHit(0); }}
          onKeyDown={(event) => {
            // Navigation is scoped to this input; comment fields keep their own Ctrl/Meta+Enter and Escape behavior.
            if (event.key === 'Enter') { event.preventDefault(); moveSearchHit(event.shiftKey ? -1 : 1); }
            else if (event.key === 'Escape' && searchText) { event.preventDefault(); setSearchText(''); setActiveSearchHit(0); }
          }}
          placeholder="搜索 diff 文本"
          className="min-w-0 flex-1 bg-transparent text-[11.5px] text-fg outline-none placeholder:text-fg-3" />
        {searchText && <button type="button" aria-label="清空 diff 搜索" onClick={() => { setSearchText(''); setActiveSearchHit(0); }}
          className="grid h-5 w-5 shrink-0 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"><X size={11} /></button>}
      </div>
      <span role="status" aria-live="polite" aria-atomic="true" className="min-w-20 text-right text-[11px] tabular-nums text-fg-3">
        {searchText ? searchHits.length ? `${activeSearchHit + 1} / ${searchHits.length} 项` : '0 / 0 · 无结果' : '输入文本搜索'}
      </span>
      <button type="button" aria-label="上一个 diff 搜索命中" title="上一个命中（Shift+Enter）" disabled={!searchHits.length}
        onClick={() => moveSearchHit(-1)} className="grid h-7 w-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40"><ChevronUp size={14} /></button>
      <button type="button" aria-label="下一个 diff 搜索命中" title="下一个命中（Enter）" disabled={!searchHits.length}
        onClick={() => moveSearchHit(1)} className="grid h-7 w-7 place-items-center rounded-md text-fg-2 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-40"><ChevronDown size={14} /></button>
    </div>
    {lines.map((line, index) => {
      const number = line.newNo ?? line.oldNo;
      const notes = comments?.filter((comment) => comment.line === number && comment.side === (line.kind === 'del' ? 'old' : 'new') && line.kind !== 'hunk') ?? [];
      const lineHitIndexes = searchHitsByLine.get(index) ?? [];
      const lineContent = line.kind === 'hunk' ? line.text : line.text.slice(1);
      const highlighted: ReactNode[] = [];
      let cursor = 0;
      for (const hitIndex of lineHitIndexes) {
        const hit = searchHits[hitIndex];
        if (hit.start > cursor) highlighted.push(lineContent.slice(cursor, hit.start));
        highlighted.push(<mark key={`search-${hitIndex}`} ref={(node) => { searchHitRefs.current[hitIndex] = node; }}
          aria-current={activeSearchHit === hitIndex ? 'true' : undefined}
          className={cn('rounded-sm', activeSearchHit === hitIndex ? 'bg-amber-300 text-black ring-1 ring-amber-500' : 'bg-amber-900/50 text-inherit')}>
          {lineContent.slice(hit.start, hit.end)}
        </mark>);
        cursor = hit.end;
      }
      if (lineHitIndexes.length) highlighted.push(lineContent.slice(cursor));
      return <div key={index}>
        <div className={cn('group flex', line.kind === 'add' ? 'bg-ok-soft text-fg' : line.kind === 'del' ? 'bg-danger-soft text-fg' : line.kind === 'hunk' ? 'text-fg-3' : 'text-fg-2')}>
          <span className="w-9 shrink-0 pr-1.5 text-right text-fg-3 select-none tabular-nums">{line.kind === 'hunk' ? '' : number}</span>
          {commentable && line.kind !== 'hunk'
            ? <button aria-label={`评论第 ${number} 行`} onClick={() => setDraft({ index, text: '' })}
              className="grid w-4 shrink-0 place-items-center text-brand opacity-0 group-hover:opacity-100 focus:opacity-100"><MessageSquarePlus size={11} /></button>
            : <span className="w-4 shrink-0" />}
          <span className="min-w-0 flex-1 pr-3 whitespace-pre">{line.kind === 'hunk' ? line.text || ' ' : <>{line.text.slice(0, 1)}{lineHitIndexes.length ? highlighted : line.text.slice(1) || ' '}</>}</span>
        </div>
        {line.kind === 'hunk' && line.text.startsWith('@@') && (() => {
          const hunk = hunks?.[line.hunkIndex];
          if (!hunk) return null;
          return <div className="flex items-center gap-2 border-y border-line/60 bg-sunken/50 px-3 py-1 font-sans text-[11.5px]" aria-label={`差异块 ${line.hunkIndex + 1} 审核`}>
            <span className="min-w-0 flex-1 text-fg-3">差异块 {line.hunkIndex + 1} · {hunk.status === 'accepted' ? '已接受' : hunk.status === 'rejected' ? '已拒绝' : '待审核'}</span>
            {hunk.status === 'pending' && <>
              <button type="button" aria-label={`接受差异块 ${line.hunkIndex + 1}`} disabled={!hunk.reviewable || busyHunkId === hunk.id}
                onClick={() => onReviewHunk?.(hunk, 'accept')} className="inline-flex min-h-7 items-center gap-1 rounded-md px-2 text-ok hover:bg-ok-soft disabled:cursor-not-allowed disabled:opacity-45">
                {busyHunkId === hunk.id ? <LoaderCircle size={12} className="spin" /> : <ThumbsUp size={12} />}接受
              </button>
              <button type="button" aria-label={`拒绝差异块 ${line.hunkIndex + 1}`} disabled={!hunk.reviewable || busyHunkId === hunk.id}
                onClick={() => onReviewHunk?.(hunk, 'reject')} className="inline-flex min-h-7 items-center gap-1 rounded-md px-2 text-danger hover:bg-danger-soft disabled:cursor-not-allowed disabled:opacity-45">
                <ThumbsDown size={12} />拒绝
              </button>
            </>}
            {hunk.status === 'accepted' && <Check size={13} aria-hidden="true" className="text-ok" />}
            {!hunk.reviewable && hunk.status === 'pending' && <span className="text-fg-3">此差异块不可安全审核</span>}
          </div>;
        })()}
        {notes.map((note) => <div key={note.id} className="mx-3 my-1 flex items-start gap-2 rounded-lg bg-overlay px-2.5 py-1.5 font-sans text-[12px] text-fg shadow-[inset_0_0_0_1px_var(--line)]">
          {editing?.id === note.id
            ? <div className="min-w-0 flex-1">
              <textarea autoFocus value={editing.text} onChange={(event) => setEditing({ id: note.id, text: event.target.value })} rows={2} aria-label="编辑行评论"
                className="w-full resize-y rounded-md bg-sunken px-2 py-1.5 text-[12px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--brand)]" />
              <div className="mt-1 flex justify-end gap-2 text-[11.5px]"><button onClick={() => setEditing(null)} className="text-fg-3 hover:text-fg">取消</button>
                <button disabled={!editing.text.trim()} onClick={() => { onEdit(note.id, editing.text.trim()); setEditing(null); }} className="text-brand disabled:opacity-50">保存</button></div>
            </div>
            : <span className="min-w-0 flex-1 whitespace-pre-wrap">{note.text}</span>}
          {editing?.id !== note.id && <button aria-label="编辑这条评论" onClick={() => setEditing({ id: note.id, text: note.text })} className="shrink-0 text-fg-3 hover:text-fg"><Pencil size={12} /></button>}
          <button aria-label="删除这条评论" onClick={() => onRemove(note.id)} className="shrink-0 text-fg-3 hover:text-fg"><X size={12} /></button>
        </div>)}
        {draft?.index === index && <div className="mx-3 my-1 grid gap-1.5 font-sans">
          <textarea autoFocus value={draft.text} onChange={(event) => setDraft({ index, text: event.target.value })} rows={2} placeholder="这一行要怎么改？" aria-label="评论内容"
            onKeyDown={(event) => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); save(); } if (event.key === 'Escape') setDraft(null); }}
            className="rounded-lg bg-overlay px-2.5 py-1.5 text-[12.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--brand)]" />
          <div className="flex justify-end gap-2 text-[12px]">
            <button onClick={() => setDraft(null)} className="text-fg-3 hover:text-fg">取消</button>
            <button onClick={save} disabled={!draft.text.trim()} className="primary-fill h-6 rounded-md px-2 disabled:opacity-50">添加评论</button>
          </div>
        </div>}
      </div>;
    })}
    {truncated && <div className="px-3 pt-1 text-fg-3">改动太大，只显示了前一部分。</div>}
  </div>;
}

/** Shadow snapshots Atlas takes before changing files; restoring one puts those files back. */
function Checkpoints({ apiBaseUrl, connected, onToast, runId, refreshKey }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void; runId?: string; refreshKey: string }) {
  const [items, setItems] = useState<Checkpoint[] | null>(null);
  const [confirm, setConfirm] = useState('');
  const [restoring, setRestoring] = useState('');
  const [error, setError] = useState('');
  const invoke = <T,>(name: string, inputs: Record<string, unknown> = {}) =>
    api<{ result: T }>(apiBaseUrl, `/api/agent/capabilities/${name}/invoke`, { method: 'POST', json: inputs }).then((body) => body.result);
  useEffect(() => {
    if (!connected) return;
    let stale = false;
    api<Checkpoint[]>(apiBaseUrl, '/api/checkpoints')
      .then((result) => {
        if (stale) return;
        // This run's snapshots first, then the newest of the rest.
        const sorted = [...result].sort((a, b) => Number(b.run_id === runId) - Number(a.run_id === runId) || b.created_at.localeCompare(a.created_at));
        setItems(sorted);
        setError('');
      })
      .catch((exc) => { if (!stale) { setItems([]); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [apiBaseUrl, connected, refreshKey, runId]);

  const restore = async (checkpoint: Checkpoint) => {
    if (confirm !== checkpoint.id) { setConfirm(checkpoint.id); return; }
    setConfirm('');
    setRestoring(checkpoint.id);
    try {
      const result = await invoke<{ restored?: unknown[] }>('workspace.checkpoint.restore', { checkpoint_id: checkpoint.id });
      onToast(`已恢复 ${Array.isArray(result.restored) ? result.restored.length : fileCount(checkpoint)} 个文件`);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setRestoring(''); }
  };

  return <section>
    <h3 className="m-0 mb-1 text-[12.5px] font-semibold text-fg-2">快照恢复</h3>
    <p className="m-0 mb-2 text-[12px] leading-[1.6] text-fg-3">Atlas 改文件前会先存一份快照。恢复只还原文件，不会撤销命令、网络请求或数据库改动。</p>
    {!connected ? <Empty title="后端没有连接" body="连上 Atlas 后端后才能查看快照。" />
      : items === null ? <p className="py-6 text-center text-[13px] text-fg-3">正在读取快照…</p>
      : <div className="grid gap-2">
        {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
        {items.slice(0, 30).map((checkpoint) => <div key={checkpoint.id} className="card-surface flex items-center gap-3 rounded-xl p-3">
          <History size={16} className="shrink-0 text-fg-3" />
          <span className="min-w-0 flex-1">
            <b className="block truncate text-[13px] font-medium text-fg" title={checkpoint.workspace}>{checkpoint.workspace.split(/[\\/]/).filter(Boolean).pop() ?? checkpoint.workspace}</b>
            <small className="block truncate text-[12px] text-fg-3" title={checkpoint.files.map((file) => file.path).join('\n')}>
              {runId && checkpoint.run_id === runId && <span className="text-brand">这次任务 · </span>}{relativeTime(checkpoint.created_at)}，{checkpoint.files.map((file) => file.path.split(/[\\/]/).pop()).slice(0, 3).join('、')}{fileCount(checkpoint) > 3 ? ` 等 ${fileCount(checkpoint)} 个` : ''}
            </small>
          </span>
          <button onClick={() => void restore(checkpoint)} disabled={Boolean(restoring)}
            className={cn('inline-flex h-7 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] disabled:opacity-50', confirm === checkpoint.id ? 'bg-danger-soft text-danger' : 'text-fg-2 hover:bg-hover hover:text-fg')}>
            {restoring === checkpoint.id ? <LoaderCircle size={13} className="spin" /> : <RotateCcw size={13} />}{confirm === checkpoint.id ? '确认恢复' : '恢复'}
          </button>
        </div>)}
        {!items.length && !error && <Empty title="还没有快照" body="Atlas 修改文件时会自动留一份，出了问题可以在这里退回去。" icon={<FileDiff size={20} />} />}
      </div>}
  </section>;
}

const fileCount = (checkpoint: Checkpoint) => checkpoint.files.filter((file) => !file.directory).length;
