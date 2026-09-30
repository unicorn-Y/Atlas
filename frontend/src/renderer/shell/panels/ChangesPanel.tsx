import { useEffect, useState } from 'react';
import { ChevronRight, FileDiff, History, LoaderCircle, MessageSquarePlus, RotateCcw, Send, X } from 'lucide-react';
import type { RunChangeFile } from '@atlas/backend-adapter';
import { backend } from '../../store/useAtlasStore';
import { api, relativeTime } from '../../services/api';
import { shortPath } from '../../components/timeline';
import { cn } from '../../ui/cn';
import { Empty } from './Empty';

/** A note on one line of the diff, sent to Atlas together with the others. */
interface LineComment { id: string; path: string; line: number | null; side: 'new' | 'old'; code: string; text: string }

interface Checkpoint { id: string; workspace: string; created_at: string; run_id?: string | null; files: Array<{ path: string; directory?: boolean }> }

const STATUS: Record<RunChangeFile['status'], { label: string; tone: string }> = {
  added: { label: '新增', tone: 'text-ok' },
  modified: { label: '修改', tone: 'text-brand' },
  deleted: { label: '删除', tone: 'text-danger' },
};

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
  const [files, setFiles] = useState<RunChangeFile[] | null>(null);
  const [open, setOpen] = useState<string[]>([]);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!runId || !connected) { setFiles([]); return; }
    let stale = false;
    setError('');
    backend.getRunChanges(runId)
      .then((result) => { if (!stale) { setFiles(result); setOpen(result.length === 1 ? [result[0].path] : []); } })
      .catch((exc) => { if (!stale) { setFiles([]); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [runId, runStatus, connected]);

  const toggle = (path: string) => setOpen((current) => current.includes(path) ? current.filter((item) => item !== path) : [...current, path]);
  const additions = files?.reduce((sum, file) => sum + file.additions, 0) ?? 0;
  const deletions = files?.reduce((sum, file) => sum + file.deletions, 0) ?? 0;

  return <div className="grid gap-6">
    <section>
      <h3 className="m-0 mb-2 flex items-center gap-2 text-[12.5px] font-semibold text-fg-2">
        这次的改动{files && files.length > 0 && <span className="font-normal tabular-nums text-fg-3">{files.length} 个文件 <span className="text-ok">+{additions}</span> <span className="text-danger">−{deletions}</span></span>}
      </h3>
      {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
      {files === null ? <p className="py-6 text-center text-[13px] text-fg-3">正在读取改动…</p>
        : files.length ? <div className="grid gap-1.5">{files.map((file) => {
          const expanded = open.includes(file.path);
          return <div key={`${file.workspace}:${file.path}`} className="overflow-hidden rounded-xl card-surface">
            <button onClick={() => toggle(file.path)} aria-expanded={expanded} className="flex w-full items-center gap-2 px-3 py-2 text-left text-[13px] hover:bg-hover">
              <ChevronRight size={13} className={cn('shrink-0 text-fg-3 transition-transform', expanded && 'rotate-90')} />
              <span className={cn('shrink-0 text-[11.5px]', STATUS[file.status]?.tone)}>{STATUS[file.status]?.label ?? file.status}</span>
              <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-fg" title={file.path}>{shortPath(file.path)}</code>
              <span className="shrink-0 text-[11.5px] tabular-nums"><span className="text-ok">+{file.additions}</span> <span className="text-danger">−{file.deletions}</span></span>
            </button>
            {expanded && <DiffView diff={file.diff} truncated={file.truncated} path={file.path} comments={onAsk ? comments.filter((comment) => comment.path === file.path) : undefined}
              onAdd={(comment) => setComments((current) => [...current, { ...comment, id: `${Date.now()}-${current.length}` }])}
              onRemove={(id) => setComments((current) => current.filter((comment) => comment.id !== id))} />}
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

type DiffLine = { text: string; kind: 'add' | 'del' | 'ctx' | 'hunk'; oldNo: number | null; newNo: number | null };

/** Unified diff lines with their old/new line numbers, read from the @@ hunk headers. */
function numberLines(diff: string): DiffLine[] {
  let oldNo = 0, newNo = 0;
  const raw = diff.replace(/\n$/, '').split('\n');
  return raw.filter((line) => !line.startsWith('---') && !line.startsWith('+++')).map((text) => {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(text);
    if (hunk) { oldNo = Number(hunk[1]); newNo = Number(hunk[2]); return { text, kind: 'hunk', oldNo: null, newNo: null }; }
    // "\ No newline at end of file" describes the line above; it is not a line of the file.
    if (text.startsWith('\\')) return { text, kind: 'hunk', oldNo: null, newNo: null };
    if (text.startsWith('+')) return { text, kind: 'add', oldNo: null, newNo: newNo++ };
    if (text.startsWith('-')) return { text, kind: 'del', oldNo: oldNo++, newNo: null };
    return { text, kind: 'ctx', oldNo: oldNo++, newNo: newNo++ };
  });
}

function DiffView({ diff, truncated, path, comments, onAdd, onRemove }: {
  diff: string; truncated?: boolean; path: string; comments?: LineComment[];
  onAdd: (comment: Omit<LineComment, 'id'>) => void; onRemove: (id: string) => void;
}) {
  const lines = numberLines(diff);
  const [draft, setDraft] = useState<{ index: number; text: string } | null>(null);
  const commentable = Boolean(comments);
  const save = () => {
    if (!draft?.text.trim()) { setDraft(null); return; }
    const line = lines[draft.index];
    onAdd({ path, line: line.newNo ?? line.oldNo, side: line.kind === 'del' ? 'old' : 'new', code: line.text.slice(1), text: draft.text.trim() });
    setDraft(null);
  };
  return <div className="max-h-96 overflow-auto bg-code py-2 font-mono text-[11.5px] leading-[1.6] shadow-[inset_0_1px_0_var(--line)]">
    {lines.map((line, index) => {
      const number = line.newNo ?? line.oldNo;
      const notes = comments?.filter((comment) => comment.line === number && comment.side === (line.kind === 'del' ? 'old' : 'new') && line.kind !== 'hunk') ?? [];
      return <div key={index}>
        <div className={cn('group flex', line.kind === 'add' ? 'bg-ok-soft text-fg' : line.kind === 'del' ? 'bg-danger-soft text-fg' : line.kind === 'hunk' ? 'text-fg-3' : 'text-fg-2')}>
          <span className="w-9 shrink-0 pr-1.5 text-right text-fg-3 select-none tabular-nums">{line.kind === 'hunk' ? '' : number}</span>
          {commentable && line.kind !== 'hunk'
            ? <button aria-label={`评论第 ${number} 行`} onClick={() => setDraft({ index, text: '' })}
              className="grid w-4 shrink-0 place-items-center text-brand opacity-0 group-hover:opacity-100 focus:opacity-100"><MessageSquarePlus size={11} /></button>
            : <span className="w-4 shrink-0" />}
          <span className="min-w-0 flex-1 pr-3 whitespace-pre">{line.text || ' '}</span>
        </div>
        {notes.map((note) => <div key={note.id} className="mx-3 my-1 flex items-start gap-2 rounded-lg bg-overlay px-2.5 py-1.5 font-sans text-[12px] text-fg shadow-[inset_0_0_0_1px_var(--line)]">
          <span className="min-w-0 flex-1 whitespace-pre-wrap">{note.text}</span>
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
