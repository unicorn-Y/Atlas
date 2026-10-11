// Adapted interaction patterns from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015c: packages/ui/src/TaskListItem.tsx (Apache-2.0).
// This details view is Atlas-specific and only displays fields present in its conversation summary.
import { useEffect, useState } from 'react';
import type { ConversationSummary } from '@atlas/backend-adapter';
import { X } from 'lucide-react';
import { api } from '../../services/api';
import { backend } from '../../store/useAtlasStore';
import { Dialog } from '../../ui/Dialog';

interface ConversationStats {
  message_count: number;
  user_turns: number;
  runs: number;
  input_tokens: number;
  output_tokens: number;
  est_cost: number | null;
}
interface SearchResult {
  id: string;
  role: string;
  created_at: string;
  snippet: string;
}

function display(value: unknown): string | null {
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) {
    const entries = value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0);
    return entries.length ? entries.join('、') : null;
  }
  return null;
}

function date(value: unknown): string | null {
  const raw = display(value);
  if (!raw) return null;
  const parsed = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(raw) ? raw : raw + 'Z');
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleString();
}

export default function SidebarConversationDetails({ conversation, open, onOpenChange, running, unread, waiting }: {
  conversation: ConversationSummary | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  running: boolean;
  unread: boolean;
  waiting: boolean;
}) {
  const [stats, setStats] = useState<ConversationStats | null>(null);
  const [statsError, setStatsError] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');

  useEffect(() => {
    if (!open || !conversation) return;
    let stale = false;
    setStats(null);
    setStatsError('');
    void api<ConversationStats>(backend.apiBaseUrl, `/api/conversations/${encodeURIComponent(conversation.id)}/stats`)
      .then((value) => { if (!stale) setStats(value); })
      .catch((error) => { if (!stale) setStatsError(error instanceof Error ? error.message : String(error)); });
    return () => { stale = true; };
  }, [open, conversation?.id]);

  useEffect(() => {
    const term = query.trim();
    if (!open || !conversation || !term) {
      setResults([]);
      setSearching(false);
      setSearchError('');
      return;
    }
    let stale = false;
    const timer = window.setTimeout(() => {
      setSearching(true);
      setSearchError('');
      void api<{ results: SearchResult[] }>(backend.apiBaseUrl,
        `/api/conversations/${encodeURIComponent(conversation.id)}/search?q=${encodeURIComponent(term)}`)
        .then((value) => { if (!stale) setResults(value.results); })
        .catch((error) => { if (!stale) setSearchError(error instanceof Error ? error.message : String(error)); })
        .finally(() => { if (!stale) setSearching(false); });
    }, 250);
    return () => { stale = true; window.clearTimeout(timer); };
  }, [open, conversation?.id, query]);

  const metadata = conversation as Record<string, unknown> | null;
  const status = waiting ? '等待输入或审批' : running ? '运行中' : unread ? '有新结果' : '空闲';
  const rows: Array<[string, string | null]> = metadata ? [
    ['会话 ID', display(metadata.id)],
    ['模型', display(metadata.model_name) ?? display(metadata.model)],
    ['工作区', display(metadata.worktree_path) ?? display(metadata.workspace)],
    ['工作区分支', display(metadata.worktree_branch) ?? display(metadata.branch)],
    ['目标分支', display(metadata.base_branch)],
    ['执行器', display(metadata.executor)],
    ['权限模式', display(metadata.permission_mode)],
    ['来源', display(metadata.source)],
    ['父会话', display(metadata.parent_conversation_id)],
    ['分叉消息', display(metadata.fork_message_id)],
    ['额外目录', display(metadata.extra_roots) ?? display(metadata.allowed_paths)],
    ['创建时间', date(metadata.created_at)],
    ['最近更新', date(metadata.updated_at)],
  ] : [];

  return <Dialog open={open && Boolean(conversation)} onOpenChange={onOpenChange} label="会话信息" className="w-[min(520px,calc(100vw-28px))] border border-line bg-overlay p-0 shadow-2xl">
    {conversation && <div className="max-h-[78vh] overflow-auto">
      <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-line bg-overlay px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="text-[12px] text-fg-3">会话信息</div>
          <h2 className="mt-0.5 truncate text-[16px] font-semibold text-heading">{conversation.title || '未命名会话'}</h2>
          <p className="mt-1 text-[12px] text-fg-2" aria-live="polite">状态：{status}</p>
        </div>
        <button aria-label="关闭会话信息" onClick={() => onOpenChange(false)} className="grid size-7 shrink-0 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg"><X size={15} /></button>
      </header>
      <dl className="grid gap-0 px-5 py-2">
        {rows.filter(([, value]) => value).map(([label, value]) => <div key={label} className="grid grid-cols-[112px_minmax(0,1fr)] gap-3 border-b border-line/70 py-2.5 last:border-0">
          <dt className="text-[12px] text-fg-3">{label}</dt>
          <dd className="m-0 break-all text-[12.5px] text-fg">{value}</dd>
        </div>)}
      </dl>
      <section className="border-t border-line px-5 py-3" aria-label="会话统计">
        <h3 className="m-0 text-[13px] font-medium text-heading">轮次与用量</h3>
        {statsError ? <p role="status" className="mb-0 text-[12px] text-danger">统计加载失败：{statsError}</p>
          : stats ? <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
            <div><dt className="text-fg-3">用户轮次</dt><dd className="m-0 text-fg">{stats.user_turns}</dd></div>
            <div><dt className="text-fg-3">运行记录</dt><dd className="m-0 text-fg">{stats.runs}</dd></div>
            <div><dt className="text-fg-3">输入 Token</dt><dd className="m-0 text-fg">{stats.input_tokens.toLocaleString()}</dd></div>
            <div><dt className="text-fg-3">输出 Token</dt><dd className="m-0 text-fg">{stats.output_tokens.toLocaleString()}</dd></div>
            <div className="col-span-2"><dt className="text-fg-3">估算费用（USD）</dt><dd className="m-0 text-fg">{stats.est_cost == null ? '暂无价格数据' : `$${stats.est_cost.toFixed(4)}`}</dd></div>
          </dl> : <p role="status" className="mb-0 text-[12px] text-fg-3">正在加载统计…</p>}
      </section>
      <section className="border-t border-line px-5 py-3" aria-label="会话内文本查找">
        <label className="grid gap-1.5 text-[13px] font-medium text-heading" htmlFor="conversation-transcript-search">查找会话内容</label>
        <input id="conversation-transcript-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder="输入要查找的文字" className="mt-2 h-8 w-full rounded-md bg-sunken px-2.5 text-[12px] text-fg outline-none focus:ring-1 focus:ring-brand" />
        {searching && <p role="status" className="mb-0 text-[11px] text-fg-3">正在查找…</p>}
        {searchError && <p role="status" className="mb-0 text-[11px] text-danger">查找失败：{searchError}</p>}
        {query.trim() && !searching && !searchError && !results.length && <p className="mb-0 text-[11px] text-fg-3">没有匹配内容。</p>}
        {results.length > 0 && <ul className="mt-2 mb-0 grid max-h-56 gap-1.5 overflow-auto p-0">
          {results.map((result) => <li key={result.id} className="list-none rounded-md bg-sunken px-2.5 py-2">
            <div className="mb-1 text-[10.5px] text-fg-3">{result.role === 'user' ? '你' : result.role === 'assistant' ? '助手' : result.role} · {date(result.created_at) ?? '时间未知'}</div>
            <p className="m-0 whitespace-pre-wrap break-words text-[11.5px] text-fg-2">{result.snippet}</p>
          </li>)}
        </ul>}
        {results.length === 50 && <p className="mb-0 text-[10.5px] text-fg-3">仅显示最近 50 条匹配。</p>}
      </section>
    </div>}
  </Dialog>;
}
