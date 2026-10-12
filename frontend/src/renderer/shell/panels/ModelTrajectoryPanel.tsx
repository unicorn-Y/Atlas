import { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../../services/api';

interface TrajectoryCall {
  id: number;
  request_id: string;
  run_id: string;
  occurred_at: string;
  model: string;
  source: string;
  call_type: string;
  subtask_id?: string | null;
  usage_available?: boolean | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cached_input_tokens?: number | null;
  cache_write_tokens?: number | null;
  details: Record<string, unknown>;
}
interface TrajectoryResult { items: TrajectoryCall[]; total: number; limit: number; offset: number }

const fieldClass = 'h-9 min-w-0 rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
const buttonClass = 'inline-flex h-8 items-center rounded-lg px-2.5 text-[12px] text-fg-2 hover:bg-hover disabled:opacity-40';

/** Per-request model calls with source/type filters and independent trajectory search. */
export default function ModelTrajectoryPanel({ apiBaseUrl, conversationId }: { apiBaseUrl: string; conversationId: string }) {
  const [query, setQuery] = useState('');
  const [source, setSource] = useState('');
  const [callType, setCallType] = useState('');
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<TrajectoryResult | null>(null);
  const [filterValues, setFilterValues] = useState<TrajectoryCall[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<number[]>([]);
  const sources = useMemo(() => [...new Set(filterValues.map((call) => call.source).filter(Boolean))].sort(), [filterValues]);
  const types = useMemo(() => [...new Set(filterValues.map((call) => call.call_type).filter(Boolean))].sort(), [filterValues]);

  useEffect(() => { setQuery(''); setSource(''); setCallType(''); setOffset(0); setResult(null); setExpanded([]); }, [conversationId]);
  useEffect(() => {
    if (!conversationId) { setResult({ items: [], total: 0, limit: 100, offset: 0 }); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true);
      setError('');
      const params = new URLSearchParams({ q: query, source, call_type: callType, limit: '100', offset: String(offset) });
      try {
        const path = `/api/conversations/${encodeURIComponent(conversationId)}/model-trajectory?${params}`;
        const page = await api<TrajectoryResult>(apiBaseUrl, path, { signal: controller.signal });
        setResult((current) => offset === 0 ? page : { ...page, items: [...(current?.items ?? []), ...page.items] });
        if (!query && !source && !callType) setFilterValues((current) => offset === 0 ? page.items : [...current, ...page.items]);
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '模型轨迹读取失败');
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [apiBaseUrl, callType, conversationId, offset, query, source]);

  const changeQuery = (value: string) => { setOffset(0); setQuery(value); };
  const changeSource = (value: string) => { setOffset(0); setSource(value); };
  const changeType = (value: string) => { setOffset(0); setCallType(value); };

  const toggle = (id: number) => setExpanded((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  return <section className="flex h-full min-h-0 flex-col gap-3 overflow-hidden p-3" aria-label="模型调用轨迹">
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(8rem,0.55fr)_minmax(8rem,0.55fr)]">
      <label className="relative"><Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-fg-3" />
        <input className={`${fieldClass} w-full pl-9`} type="search" value={query} onChange={(event) => changeQuery(event.target.value)} placeholder="检索模型调用、轮次或请求 ID" aria-label="检索模型轨迹" />
      </label>
      <select className={fieldClass} value={source} onChange={(event) => changeSource(event.target.value)} aria-label="按调用来源筛选">
        <option value="">所有来源</option>{sources.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
      <select className={fieldClass} value={callType} onChange={(event) => changeType(event.target.value)} aria-label="按调用类型筛选">
        <option value="">所有类型</option>{types.map((value) => <option key={value} value={value}>{value}</option>)}
      </select>
    </div>
    {error && <p role="alert" className="text-[12px] text-danger">{error}</p>}
    <div className="min-h-0 flex-1 overflow-auto rounded-xl border border-line">
      {loading && !result && <p className="p-4 text-[12px] text-fg-3">正在读取真实调用记录…</p>}
      {!loading && !error && result?.items.length === 0 && <p className="p-4 text-[12px] text-fg-3">此会话暂无已采集的模型调用记录。</p>}
      <ol className="divide-y divide-line">
        {result?.items.map((call) => <li key={call.id} className="p-3">
          <button type="button" className="flex w-full items-start justify-between gap-3 text-left" onClick={() => toggle(call.id)} aria-expanded={expanded.includes(call.id)}>
            <span className="min-w-0"><span className="block truncate text-[13px] font-medium text-heading">{call.model}</span>
              <span className="mt-1 block truncate text-[11px] text-fg-3">{call.source} · {call.call_type} · {call.request_id}</span></span>
            <span className="shrink-0 text-right text-[11px] text-fg-3">{new Date(call.occurred_at).toLocaleString()}<span className="mt-1 block">{call.usage_available !== true ? 'Token 用量未知' : `输入 ${call.input_tokens ?? '—'} / 输出 ${call.output_tokens ?? '—'}`}</span></span>
          </button>
          {expanded.includes(call.id) && <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 border-t border-line pt-2 text-[11px]">
            <dt className="text-fg-3">运行</dt><dd className="break-all text-fg-2">{call.run_id}</dd>
            <dt className="text-fg-3">子任务</dt><dd className="break-all text-fg-2">{call.subtask_id || '—'}</dd>
            <dt className="text-fg-3">缓存 Token</dt><dd className="text-fg-2">{call.cached_input_tokens ?? '—'} / 写入 {call.cache_write_tokens ?? '—'}</dd>
            <dt className="text-fg-3">附加记录</dt><dd className="break-all text-fg-2">{Object.entries(call.details).filter(([key]) => !['input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_write_tokens'].includes(key)).map(([key, value]) => `${key}: ${String(value)}`).join(' · ') || '无'}</dd>
          </dl>}
        </li>)}
      </ol>
    </div>
    <div className="flex shrink-0 items-center justify-between text-[11px] text-fg-3"><span>{loading ? '正在更新…' : `命中 ${result?.total ?? 0} 次调用`}</span>
      {result && result.total > result.items.length && <span>当前显示最近 {result.items.length} 条</span>}
      {result && result.offset + result.items.length < result.total && <button className={buttonClass} type="button" disabled={loading} onClick={() => setOffset((value) => value + 100)}>载入更多</button>}
      <button className={buttonClass} type="button" disabled={!query && !source && !callType} onClick={() => { setOffset(0); setQuery(''); setSource(''); setCallType(''); }}>清除筛选</button>
    </div>
  </section>;
}
