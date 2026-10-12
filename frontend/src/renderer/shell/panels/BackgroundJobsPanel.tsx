import { useCallback, useEffect, useState } from 'react';
import { ArrowUpRight, CircleStop, RefreshCw } from 'lucide-react';
import { api, relativeTime } from '../../services/api';
import { cn } from '../../ui/cn';

interface BackgroundRun {
  id: string; status: string; started_at: string; updated_at: string;
  waiting_for?: string | null; backgrounded_at?: string | null;
}
interface BackgroundProcess {
  id: string; command: string; cwd: string; status: string; started_at: string;
  exit_code?: number | null; run_id?: string | null;
}
interface BackgroundSubtask { id: string; run_id: string; title: string; detail: string; status: string }
interface BackgroundJobs {
  conversation_id: string; runs: BackgroundRun[]; subtasks: BackgroundSubtask[]; processes: BackgroundProcess[];
}

const active = (status: string) => ['running', 'paused', 'waiting'].includes(status);
const STATUS_LABELS: Record<string, string> = { running: '运行中', paused: '已暂停', waiting: '等待输入', exited: '已退出', cancelled: '已停止', completed: '已完成', failed: '失败' };
const statusLabel = (status: string) => STATUS_LABELS[status] ?? status;

/** Session scoped controls for live Atlas runs and detached shell processes. */
export default function BackgroundJobsPanel({ apiBaseUrl, conversationId, onReconnect, onToast }: {
  apiBaseUrl: string;
  conversationId: string;
  onReconnect: (runId: string, conversationId: string) => void;
  onToast?: (message: string) => void;
}) {
  const [data, setData] = useState<BackgroundJobs>({ conversation_id: conversationId, runs: [], subtasks: [], processes: [] });
  const [openProcess, setOpenProcess] = useState('');
  const [output, setOutput] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const base = `/api/conversations/${encodeURIComponent(conversationId)}/background-jobs`;

  const refresh = useCallback(async () => {
    if (!conversationId) return;
    try { setData(await api<BackgroundJobs>(apiBaseUrl, base)); setError(''); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [apiBaseUrl, base, conversationId]);

  useEffect(() => {
    setOpenProcess(''); setOutput('');
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!openProcess) { setOutput(''); return; }
    const process = data.processes.find((item) => item.id === openProcess);
    if (!process) { setOutput(''); return; }
    let stale = false;
    const offsets = { stdout: 0, stderr: 0 };
    const poll = async () => {
      try {
        for (const stream of ['stdout', 'stderr'] as const) {
          const chunk = await api<{ output: string; next_offset: number }>(apiBaseUrl,
            `${base}/processes/${encodeURIComponent(openProcess)}/output?stream=${stream}&offset=${offsets[stream]}`);
          if (stale) return;
          offsets[stream] = chunk.next_offset;
          if (chunk.output) setOutput((current) => (current + chunk.output).slice(-30000));
        }
      } catch (cause) { if (!stale) setError(cause instanceof Error ? cause.message : String(cause)); }
    };
    setOutput(''); void poll();
    const timer = window.setInterval(() => void poll(), 1200);
    return () => { stale = true; window.clearInterval(timer); };
  }, [apiBaseUrl, base, data.processes, openProcess]);

  const action = async (key: string, path: string, after?: () => void) => {
    setBusy(key);
    try { await api(apiBaseUrl, `${base}${path}`, { method: 'POST' }); after?.(); await refresh(); }
    catch (cause) { const message = cause instanceof Error ? cause.message : String(cause); setError(message); onToast?.(message); }
    finally { setBusy(''); }
  };

  return <section className="grid gap-3" aria-label="当前会话后台任务">
    <header className="flex items-center gap-2">
      <div className="min-w-0 flex-1">
        <h3 className="m-0 text-[13px] font-semibold text-fg">当前会话后台任务</h3>
        <p className="m-0 mt-0.5 text-[11.5px] text-fg-3">查看运行状态、重连会话或停止后台命令。</p>
      </div>
      <button type="button" aria-label="刷新后台任务" title="刷新" onClick={() => void refresh()} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><RefreshCw size={14} /></button>
    </header>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger/10 px-3 py-2 text-[12px] text-danger">{error}</p>}
    {data.runs.map((run) => <article key={run.id} className="rounded-xl bg-sunken p-3">
      <div className="flex items-center gap-2">
        <span className={cn('size-2 shrink-0 rounded-full', active(run.status) ? 'bg-ok' : 'bg-fg-3')} />
        <div className="min-w-0 flex-1">
          <p className="m-0 text-[12.5px] font-medium text-fg">Agent 会话 · {statusLabel(run.status)}{run.waiting_for ? ` · ${run.waiting_for}` : ''}</p>
          <p className="m-0 mt-0.5 truncate font-mono text-[10.5px] text-fg-3" title={run.id}>{run.id} · {relativeTime(run.updated_at || run.started_at)}</p>
        </div>
        {run.backgrounded_at && active(run.status)
          ? <button type="button" disabled={busy === `foreground-${run.id}`} onClick={() => void action(`foreground-${run.id}`, `/runs/${encodeURIComponent(run.id)}/foreground`, () => onReconnect(run.id, conversationId))}
              className="inline-flex h-7 shrink-0 items-center gap-1 rounded-md bg-overlay px-2 text-[11.5px] text-fg hover:bg-hover disabled:opacity-50"><ArrowUpRight size={13} />重连</button>
          : active(run.status) && <button type="button" disabled={busy === `background-${run.id}`} onClick={() => void action(`background-${run.id}`, `/runs/${encodeURIComponent(run.id)}/background`)}
              className="h-7 shrink-0 rounded-md bg-overlay px-2 text-[11.5px] text-fg-2 hover:bg-hover disabled:opacity-50">转入后台</button>}
        {active(run.status) && <button type="button" aria-label="停止 Agent 任务" title="停止任务" disabled={busy === `stop-run-${run.id}`} onClick={() => void action(`stop-run-${run.id}`, `/runs/${encodeURIComponent(run.id)}/stop`)}
          className="grid size-7 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-danger disabled:opacity-50"><CircleStop size={14} /></button>}
      </div>
    </article>)}
    {data.subtasks.map((task) => <article key={`${task.run_id}:${task.id}`} className="rounded-xl bg-sunken p-3">
      <div className="flex items-center gap-2">
        <span className={cn('size-2 shrink-0 rounded-full', active(task.status) ? 'bg-ok' : 'bg-fg-3')} />
        <div className="min-w-0 flex-1">
          <p className="m-0 truncate text-[12.5px] font-medium text-fg" title={task.title}>{task.title} · {statusLabel(task.status)}</p>
          <p className="m-0 mt-0.5 break-words text-[11px] text-fg-3">{task.detail}</p>
        </div>
        {active(task.status) && <button type="button" aria-label="停止子 Agent" title="停止任务" disabled={busy === `stop-subtask-${task.id}`} onClick={() => void action(`stop-subtask-${task.id}`, `/runs/${encodeURIComponent(task.run_id)}/subtasks/${encodeURIComponent(task.id)}/stop`)}
          className="grid size-7 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-danger disabled:opacity-50"><CircleStop size={14} /></button>}
      </div>
    </article>)}
    {data.processes.map((process) => <article key={process.id} className="overflow-hidden rounded-xl bg-sunken">
      <div className="flex items-center gap-2 p-3">
        <span className={cn('size-2 shrink-0 rounded-full', process.status === 'running' ? 'bg-ok' : 'bg-fg-3')} />
        <button type="button" aria-expanded={openProcess === process.id} onClick={() => setOpenProcess(openProcess === process.id ? '' : process.id)} className="min-w-0 flex-1 text-left">
          <code className="block truncate font-mono text-[11.5px] text-fg" title={process.command}>{process.command}</code>
          <span className="mt-0.5 block text-[11px] text-fg-3">{statusLabel(process.status)} · {relativeTime(process.started_at)}{process.exit_code == null ? '' : ` · 退出码 ${process.exit_code}`}</span>
        </button>
        {process.status === 'running' && <button type="button" aria-label="停止后台命令" title="停止命令" disabled={busy === `stop-process-${process.id}`} onClick={() => void action(`stop-process-${process.id}`, `/processes/${encodeURIComponent(process.id)}/stop`)}
          className="grid size-7 shrink-0 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-danger disabled:opacity-50"><CircleStop size={14} /></button>}
      </div>
      {openProcess === process.id && <pre className="m-0 max-h-56 overflow-auto whitespace-pre-wrap break-words border-t border-line bg-code p-3 font-mono text-[11px] leading-relaxed text-fg-2">{output || '等待进程输出…'}</pre>}
    </article>)}
    {!data.runs.length && !data.subtasks.length && !data.processes.length && !error && <p className="m-0 rounded-xl bg-sunken p-4 text-[12px] text-fg-3">当前会话没有后台任务。</p>}
  </section>;
}
