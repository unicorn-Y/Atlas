import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';

type ToolTrace = {
  call_id: string;
  run_id: string;
  tool_name: string;
  family: string | null;
  tier: string | null;
  started_at: string;
  duration_ms: number | null;
  status: string;
  is_error: number | boolean;
  arguments_chars: number | null;
  result_chars: number | null;
  error_detail: string | null;
};

export default function ToolTracePanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [traces, setTraces] = useState<ToolTrace[]>([]);
  const [query, setQuery] = useState('');
  const [runId, setRunId] = useState('');
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (query.trim()) params.set('q', query.trim());
      if (runId.trim()) params.set('run_id', runId.trim());
      const data = await api<{ traces: ToolTrace[] }>(apiBaseUrl, `/api/maintenance/tool-traces?${params.toString()}`);
      setTraces(data.traces ?? []);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, query, runId]);

  useEffect(() => { void load(); }, [load]);

  const rows = onlyErrors ? traces.filter((row) => Boolean(row.is_error)) : traces;
  const totalMs = rows.reduce((sum, row) => sum + (row.duration_ms ?? 0), 0);
  const errorCount = traces.filter((row) => Boolean(row.is_error)).length;

  return (
    <div className="grid gap-3">
      <p className="m-0 text-[11.5px] text-fg-3">
        每次工具调用都会留下一条记录：工具名、家族、档位、耗时、是否报错、参数与结果的长度。
        只记录这些可观测事实，不保存参数和结果的正文，所以这里看不到内容本身。
      </p>

      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-[11px] text-fg-3">
          搜索
          <input
            aria-label="搜索工具调用"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="工具名 / 家族 / 错误信息"
            className="w-56 rounded border border-line bg-surface px-2 py-1.5 text-[12px] text-fg"
          />
        </label>
        <label className="grid gap-1 text-[11px] text-fg-3">
          只属于某个运行
          <input
            aria-label="按运行 ID 过滤"
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            placeholder="run_id（可留空）"
            className="w-64 rounded border border-line bg-surface px-2 py-1.5 font-mono text-[11px] text-fg"
          />
        </label>
        <label className="flex items-center gap-1.5 text-[11.5px] text-fg-2">
          <input type="checkbox" checked={onlyErrors} onChange={(event) => setOnlyErrors(event.target.checked)} />
          只看报错的
        </label>
        <button type="button" onClick={() => void load()} className="rounded border border-line px-2.5 py-1 text-[11px] text-fg">
          {loading ? '读取中…' : '刷新'}
        </button>
      </div>

      {error && <p role="alert" className="m-0 text-danger">读取工具调用记录失败：{error}</p>}

      <p className="m-0 text-[11.5px] text-fg-3">
        共 {traces.length} 条{onlyErrors ? `，其中报错 ${rows.length} 条` : `，其中报错 ${errorCount} 条`}
        {rows.length > 0 && ` · 累计耗时 ${totalMs} ms`}
      </p>

      {!rows.length && !error && (
        <p className="m-0 text-[12px] text-fg-3">
          {traces.length ? '没有符合筛选条件的记录。' : '还没有工具调用记录。跑一次会用到工具的对话就会出现。'}
        </p>
      )}

      {rows.length > 0 && (
        <div className="max-h-96 overflow-auto rounded-lg border border-line">
          <table className="w-full border-collapse text-[11.5px]">
            <thead className="sticky top-0 bg-sunken text-left text-fg-3">
              <tr>
                <th className="px-2 py-1.5 font-medium">时间</th>
                <th className="px-2 py-1.5 font-medium">工具</th>
                <th className="px-2 py-1.5 font-medium">家族</th>
                <th className="px-2 py-1.5 font-medium">档位</th>
                <th className="px-2 py-1.5 text-right font-medium">耗时</th>
                <th className="px-2 py-1.5 text-right font-medium">参数</th>
                <th className="px-2 py-1.5 text-right font-medium">结果</th>
                <th className="px-2 py-1.5 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const failed = Boolean(row.is_error);
                return (
                  <tr key={row.call_id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-2 py-1.5 text-fg-3">
                      {row.started_at ? new Date(row.started_at).toLocaleTimeString() : '—'}
                    </td>
                    <td className="px-2 py-1.5 font-mono text-fg">
                      {row.tool_name}
                      {row.run_id && (
                        <div className="font-sans text-[10px] text-fg-3" title={row.run_id}>
                          运行 {row.run_id.slice(0, 8)}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-1.5 text-fg-2">{row.family || '—'}</td>
                    <td className="px-2 py-1.5 text-fg-2">{row.tier || '—'}</td>
                    <td className="px-2 py-1.5 text-right text-fg-2">{row.duration_ms == null ? '—' : `${row.duration_ms} ms`}</td>
                    <td className="px-2 py-1.5 text-right text-fg-3">{row.arguments_chars ?? '—'}</td>
                    <td className="px-2 py-1.5 text-right text-fg-3">{row.result_chars ?? '—'}</td>
                    <td className={`px-2 py-1.5 ${failed ? 'text-danger' : 'text-fg-2'}`}>
                      {row.status}
                      {failed && row.error_detail && (
                        <div className="max-w-56 whitespace-pre-wrap break-words text-[10px] text-danger" title={row.error_detail}>
                          {row.error_detail.length > 120 ? `${row.error_detail.slice(0, 120)}…` : row.error_detail}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
