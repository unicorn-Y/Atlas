import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';

/**
 * Run replay — "what actually happened in that run?"
 *
 * Every run already writes a JSONL event log. This panel reads it back as a
 * timeline so a turn that felt wrong can be inspected instead of guessed at:
 * which model was asked, which tools were called, how long each step took, and
 * what it cost.
 *
 * Read-only by design. Nothing here re-executes anything. Resuming an
 * interrupted run is a separate, explicit act started from that run's own
 * entry point — never from this panel.
 */

type RunRow = {
  run_id: string;
  status: string;
  event_count: number;
  bad_lines: number;
  start_time: string | null;
  duration_ms: number | null;
  size_bytes: number;
};

type TimelineItem = {
  index: number;
  kind: string;
  timestamp: string | null;
  label: string;
  detail: unknown;
  elapsed_ms: number | null;
  tool_name: string | null;
  tool_call_id: string | null;
  is_error: boolean | null;
};

type RunDetail = {
  run_id: string;
  status: string | null;
  terminal_status: string | null;
  model: string | null;
  duration_ms: number | null;
  cost_usd: number | null;
  bad_lines: number;
  truncated: boolean;
  timeline_count: number;
  timeline_truncated: boolean;
  timeline: TimelineItem[];
  summary?: {
    model_requests?: number;
    tool_calls?: number;
    steps?: number;
    cost?: { total_usd?: number | null; recorded?: boolean };
  };
};

type Checkpoint = {
  id: number;
  sequence: number;
  kind: string;
  phase: string | null;
  tool_name: string | null;
  state: string | null;
  replay_safe: boolean;
};

const STATUS_TONE: Record<string, string> = {
  completed: 'bg-[var(--ok-soft)] text-[var(--ok)]',
  running: 'bg-[var(--brand-soft)] text-[var(--brand)]',
  failed: 'bg-[var(--danger-soft)] text-[var(--danger)]',
  cancelled: 'bg-[var(--sunken)] text-fg-2',
};

const clock = (value: string | null) => {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString('zh-CN', { hour12: false });
};

/** Run details are arbitrary JSON; show only what helps a human read the turn. */
const summarise = (detail: unknown): string => {
  if (detail === null || detail === undefined) return '';
  if (typeof detail === 'string') return detail;
  if (typeof detail !== 'object') return String(detail);
  const record = detail as Record<string, unknown>;
  const picked = ['model', 'tool', 'reason', 'error', 'category', 'message', 'chars', 'items']
    .filter((key) => record[key] !== undefined && record[key] !== null && record[key] !== '')
    .map((key) => `${key}=${typeof record[key] === 'object' ? JSON.stringify(record[key]) : String(record[key])}`);
  if (picked.length) return picked.join(' · ');
  const text = JSON.stringify(record);
  return text.length > 120 ? `${text.slice(0, 120)}…` : text;
};

export default function RunReplayPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('');

  const loadRuns = useCallback(async () => {
    setBusy(true);
    setError('');
    try {
      const data = await api<{ items: RunRow[] }>(apiBaseUrl, '/api/run-replay?limit=50');
      setRuns(data.items ?? []);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void loadRuns(); }, [loadRuns]);

  const open = async (runId: string) => {
    if (selected === runId) { setSelected(null); setDetail(null); setCheckpoints([]); return; }
    setSelected(runId);
    setDetail(null);
    setCheckpoints([]);
    setBusy(true);
    setError('');
    try {
      const [run, marks] = await Promise.all([
        api<RunDetail>(apiBaseUrl, `/api/run-replay/${encodeURIComponent(runId)}?timeline_limit=500`),
        api<{ checkpoints: Checkpoint[] }>(apiBaseUrl, `/api/run-checkpoints/${encodeURIComponent(runId)}?limit=500`)
          .catch(() => ({ checkpoints: [] as Checkpoint[] })),
      ]);
      setDetail(run);
      setCheckpoints(marks.checkpoints ?? []);
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      setBusy(false);
    }
  };

  const visible = filter.trim()
    ? runs.filter((run) => run.run_id.toLowerCase().includes(filter.trim().toLowerCase()))
    : runs;

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <strong className="text-[12px]">运行回放</strong>
        <span className="text-[10.5px] text-fg-3">{visible.length} 次运行</span>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="按 run id 过滤"
          className="ml-auto w-40 rounded border border-line bg-surface px-2 py-1 text-[11px]"
        />
        <button type="button" onClick={() => void loadRuns()} disabled={busy} className="rounded border border-line px-2.5 py-1 text-[11px] disabled:opacity-50">
          {busy ? '读取中…' : '刷新'}
        </button>
      </div>
      <p className="m-0 text-[11px] text-fg-3">
        读的是每次运行已经写下的日志，只回放、不重跑。想恢复某次中断的运行，要在那次运行自己的入口点恢复，这里不会替你执行。
      </p>
      {error ? <p role="alert" className="m-0 text-[11.5px] text-danger">{error}</p> : null}

      {visible.length === 0 && !busy ? <p className="m-0 text-[11.5px] text-fg-3">还没有可回放的运行记录。</p> : null}

      <ul className="grid max-h-72 gap-1 overflow-auto">
        {visible.map((run) => (
          <li key={run.run_id}>
            <button
              type="button"
              onClick={() => void open(run.run_id)}
              className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[11.5px] ${selected === run.run_id ? 'bg-hover' : 'hover:bg-sunken'}`}
            >
              <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] ${STATUS_TONE[run.status] ?? 'bg-sunken text-fg-3'}`}>{run.status}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-fg-1">{run.run_id}</span>
              <span className="shrink-0 text-[10.5px] text-fg-3">{run.event_count} 事件</span>
              {run.bad_lines ? <span className="shrink-0 text-[10.5px] text-danger">{run.bad_lines} 行损坏</span> : null}
              <span className="shrink-0 text-[10.5px] text-fg-3">{run.duration_ms ? `${(run.duration_ms / 1000).toFixed(1)}s` : ''}</span>
              <span className="shrink-0 text-[10.5px] text-fg-3">{clock(run.start_time)}</span>
            </button>
          </li>
        ))}
      </ul>

      {selected && detail ? (
        <div className="grid gap-2 rounded-lg bg-sunken p-2">
          <div className="flex flex-wrap items-center gap-2">
            <strong className="font-mono text-[11.5px]">{detail.run_id}</strong>
            <span className={`rounded-full px-2 py-0.5 text-[10px] ${STATUS_TONE[detail.status ?? ''] ?? 'bg-surface text-fg-3'}`}>
              {detail.status ?? '未知'}
            </span>
            <span className="text-[10.5px] text-fg-3">
              {detail.timeline_count} 个时间点{(detail.timeline_truncated || detail.truncated) ? '（已截断）' : ''}
              {detail.model ? ` · ${detail.model}` : ''}
              {detail.summary?.model_requests ? ` · ${detail.summary.model_requests} 次模型请求` : ''}
              {detail.summary?.tool_calls ? ` · ${detail.summary.tool_calls} 次工具调用` : ''}
              {typeof detail.cost_usd === 'number'
                ? ` · $${detail.cost_usd.toFixed(4)}`
                : detail.summary?.cost?.recorded === false ? ' · 未记录成本' : ''}
              {checkpoints.length ? ` · ${checkpoints.length} 个检查点` : ''}
            </span>
            <button type="button" onClick={() => { setSelected(null); setDetail(null); setCheckpoints([]); }} className="ml-auto rounded border border-line px-2 py-0.5 text-[10.5px]">收起</button>
          </div>
          <ol className="grid max-h-80 gap-0.5 overflow-auto">
            {detail.timeline.map((item) => (
              <li key={`${item.index}-${item.kind}`} className={`flex items-start gap-2 text-[11px] ${item.is_error ? 'text-danger' : ''}`}>
                <span className="w-14 shrink-0 font-mono text-fg-3">{clock(item.timestamp)}</span>
                <span className="w-7 shrink-0 text-right font-mono text-fg-3">{item.index}</span>
                <span className="min-w-0 flex-1">
                  <span className="text-fg-1">{item.label}</span>
                  {item.tool_name ? <span className="ml-1 font-mono text-[10px] text-fg-3">[{item.tool_name}]</span> : null}
                  {summarise(item.detail) ? <span className="ml-1 break-words text-fg-3">{summarise(item.detail)}</span> : null}
                </span>
                {item.elapsed_ms ? <span className="shrink-0 text-fg-3">{Math.round(item.elapsed_ms)} ms</span> : null}
              </li>
            ))}
          </ol>
          {checkpoints.length ? (
            <details className="text-[11px]">
              <summary className="cursor-pointer text-fg-2">检查点（中断后可从这里恢复，共 {checkpoints.length} 个）</summary>
              <ul className="mt-1 grid gap-0.5">
                {checkpoints.map((mark) => (
                  <li key={mark.id} className="flex items-center gap-2">
                    <span className="w-7 shrink-0 text-right font-mono text-fg-3">{mark.sequence}</span>
                    <span className="shrink-0 rounded bg-surface px-1.5 py-0.5 text-[10px] text-fg-2">{mark.kind}</span>
                    <span className="min-w-0 flex-1 truncate text-fg-2">{mark.phase ?? mark.tool_name ?? mark.state ?? '—'}</span>
                    {mark.replay_safe ? <span className="shrink-0 text-[10px] text-[var(--ok)]">可重放</span> : null}
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
