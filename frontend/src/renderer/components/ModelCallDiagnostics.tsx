import { useMemo } from 'react';
import type { AgentEvent } from '../../types/runtime';
import { useEffect, useState } from 'react';
import { api } from '../services/api';

type UsageRow = {
  id: string;
  timestamp: string;
  data: Record<string, unknown>;
};

function finiteCount(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
}

function tokenText(data: Record<string, unknown>): string {
  if (data.usage_available !== true) return '提供方未返回 token 用量';
  const input = finiteCount(data.input_tokens);
  const output = finiteCount(data.output_tokens);
  const cached = finiteCount(data.cached_tokens ?? data.cached_input_tokens);
  if (input === null && output === null) return '用量标为可用，但事件没有 token 数值';
  return `输入 ${input?.toLocaleString() ?? '未提供'} · 输出 ${output?.toLocaleString() ?? '未提供'}${cached === null ? '' : ` · 缓存 ${cached.toLocaleString()}`}`;
}

function display(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function timestamp(value: string): string {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleTimeString() : '时间未提供';
}

/**
 * Read-only per-call view over canonical run events. Token counts are shown
 * only when the provider explicitly marked usage as available.
 */
export function ModelCallDiagnostics({ events }: { events: AgentEvent[] }) {
  const rows = useMemo<UsageRow[]>(() => events.flatMap((event) => {
    if (event.type !== 'run.usage') return [];
    const data = event.data.usage && typeof event.data.usage === 'object'
      ? event.data.usage as Record<string, unknown>
      : event.data;
    return [{ id: String(data.request_id ?? event.id), timestamp: event.timestamp, data }];
  }), [events]);

  if (!rows.length) return null;
  return <details className="basis-full rounded-lg border border-line/70 bg-surface/40 px-2.5 py-2">
    <summary className="cursor-pointer text-[12px] text-fg-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
      逐次模型调用诊断 · {rows.length} 次
    </summary>
    <div className="mt-2 grid gap-1.5">
      <p className="m-0 text-[11.5px] text-fg-3">
        用量来自运行时实际收到的 provider usage。Atlas 当前没有逐请求 HTTP 请求体、响应体、状态码或传输字节日志。
      </p>
      <ol className="m-0 grid max-h-64 gap-1.5 overflow-auto p-0">
        {rows.map((row, index) => {
          const duration = finiteCount(row.data.duration_ms);
          return <li key={`${row.id}-${index}`} className="list-none rounded-md border border-line/60 px-2 py-1.5 text-[12px]">
            <div className="flex flex-wrap gap-x-2 text-fg-2">
              <span>{timestamp(row.timestamp)}</span>
              <span>{display(row.data.purpose, '来源未提供')}</span>
              <span>{display(row.data.provider, 'provider 未提供')} / {display(row.data.model, '模型未提供')}</span>
              {duration !== null && <span>{duration.toLocaleString()} ms</span>}
            </div>
            <div className="mt-0.5 text-fg-3">{tokenText(row.data)}</div>
          </li>;
        })}
      </ol>
    </div>
  </details>;
}

/** Show only reasoning text explicitly delivered as run.status/status=reasoning. */
export function ModelThinkingTranscript({ events, persistedReasoning }: { events: AgentEvent[]; persistedReasoning?: string | null }) {
  const transcript = useMemo(() => events.flatMap((event) => {
    if (event.type !== 'run.status' || event.data.status !== 'reasoning'
      || typeof event.data.text !== 'string' || !event.data.text) return [];
    return [{ id: event.id, timestamp: event.timestamp, text: event.data.text }];
  }), [events]);
  const replayText = transcript.length === 0 && typeof persistedReasoning === 'string' ? persistedReasoning : '';

  if (!transcript.length && !replayText) return null;
  return <details className="basis-full rounded-lg border border-line/70 bg-surface/40 px-2.5 py-2">
    <summary className="cursor-pointer text-[12px] text-fg-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
      模型显式提供的推理转录{transcript.length ? ` · ${transcript.length} 段` : ''}
    </summary>
    <div className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words text-[12px] leading-relaxed text-fg-3">
      {replayText && <p className="m-0 mb-2 border-b border-line/60 pb-2">{replayText}</p>}
      {transcript.map((entry) => <p key={entry.id} className="m-0 mb-2 last:mb-0" data-timestamp={entry.timestamp}>{entry.text}</p>)}
    </div>
  </details>;
}

type NetworkRow = {
  event?: string; timestamp?: string; run_id?: string; request_id?: string; provider?: string; method?: string;
  host?: string; path?: string; status?: number; request_bytes?: number; response_bytes?: number;
  duration_ms?: number; response_duration_ms?: number; exception_category?: string;
  stream_complete?: boolean | null; completion_source?: string;
};

/** Read-only HTTPX transport metadata across this conversation's recent runs. */
export function NetworkDiagnostics({ apiBaseUrl, conversationId }: {
  apiBaseUrl: string; conversationId: string;
}) {
  const [items, setItems] = useState<NetworkRow[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!conversationId) { setItems([]); setError(''); return; }
    let stale = false;
    const refresh = async () => {
      setLoading(true);
      try {
        const query = new URLSearchParams({ limit: '1000' });
        const result = await api<{ items: NetworkRow[] }>(apiBaseUrl,
          `/api/conversations/${encodeURIComponent(conversationId)}/network-diagnostics?${query}`);
        if (!stale) { setItems(result.items); setError(''); }
      } catch (cause) {
        if (!stale) setError(cause instanceof Error ? cause.message : String(cause));
      } finally { if (!stale) setLoading(false); }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2500);
    return () => { stale = true; window.clearInterval(timer); };
  }, [apiBaseUrl, conversationId]);

  return <section className="grid gap-2 rounded-lg border border-line/70 bg-surface/40 px-2.5 py-2">
    <div className="flex items-center gap-2">
      <h3 className="m-0 flex-1 text-[12px] font-medium text-fg-2">网络请求日志 · HTTPX</h3>
    </div>
    <p className="m-0 text-[11.5px] text-fg-3">只记录脱敏主机/路径、HTTP 状态、时长与 HTTPX 交付的请求/响应 payload 字节数；不记录正文、headers、query 或密钥。TLS 与 framing 字节不计。</p>
    {error && <p role="alert" className="m-0 text-[11.5px] text-danger">{error}</p>}
    {!error && !items.length && <p className="m-0 text-[11.5px] text-fg-3">{loading ? '正在读取网络记录…' : '此会话最近的运行暂无 HTTPX 网络记录。'}</p>}
    {items.length > 0 && <ol className="m-0 grid max-h-60 gap-1 overflow-auto p-0">
      {items.map((item, index) => <li key={`${item.request_id ?? index}:${item.event ?? ''}`} className="list-none rounded-md border border-line/60 px-2 py-1.5 text-[11px]">
        <div className="flex flex-wrap gap-x-2 text-fg-2"><span>{item.timestamp ? timestamp(item.timestamp) : ''}</span><span>运行 {item.run_id ?? '未知'}</span><span>{item.provider}</span><span>{item.method} {item.host}{item.path}</span><span>{item.status ?? item.exception_category ?? item.event}</span></div>
        <p className="m-0 mt-0.5 text-fg-3">请求 {item.request_bytes ?? '—'} B · 响应 {item.response_bytes ?? '—'} B · {item.duration_ms ?? item.response_duration_ms ?? '—'} ms{item.stream_complete === false ? ' · 流未完整读取' : item.completion_source === 'response_headers_fallback' ? ' · 请求体长度为响应头回退值' : ''}</p>
      </li>)}
    </ol>}
  </section>;
}
