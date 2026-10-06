/**
 * IntentView（T12.1）—— 待办（意图）视图。
 * GET /api/unified-memory/intents?status&cursor（契约 §6：UI 与触发器读同一意图）。
 * 当前服务端 501 FEATURE_NOT_READY：组件实现完整，数据层 501 时显示
 * 「功能未启用」degraded 态，不报错、不假装空列表。
 */
import { useCallback, useEffect, useState } from 'react';
import { ListTodo, LoaderCircle, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';
import { enumLabel, formatMoment, isFeatureDisabled, isNotEnabled, pageOf, str } from './common';

export interface IntentItem {
  id: string;
  title: string;
  status: string;
  due: string;
  scope: string;
  revision: number | null;
}

const INTENT_STATUS: Record<string, string> = {
  PROPOSED: '待确认', ACTIVE: '进行中', SCHEDULED: '已排期',
  DONE: '已完成', COMPLETED: '已完成', CANCELLED: '已取消',
  UNKNOWN: '待对账', FAILED: '未完成',
};

export function normalizeIntent(value: unknown): IntentItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const id = str(raw.id ?? raw.intent_id ?? raw.intent_ref);
  if (!id) return null;
  const content = (raw.content && typeof raw.content === 'object' ? raw.content : {}) as Record<string, unknown>;
  return {
    id,
    title: str(raw.title ?? raw.action ?? content.action ?? content.text ?? raw.description) || '(未写明内容)',
    status: str(raw.status ?? raw.state),
    due: str(raw.due ?? raw.due_at ?? raw.valid_time),
    scope: str(raw.scope ?? raw.project),
    revision: typeof raw.revision === 'number' ? raw.revision : null,
  };
}

export function normalizeIntents(payload: unknown): { items: IntentItem[]; nextCursor: string | null } {
  const page = pageOf(payload);
  return { items: page.items.map(normalizeIntent).filter((item): item is IntentItem => item !== null), nextCursor: page.nextCursor };
}

export async function fetchIntents(
  apiBaseUrl: string,
  opts: { status?: string; cursor?: string | null; limit?: number } = {},
): Promise<unknown> {
  const params = new URLSearchParams();
  if (opts.status) params.set('status', opts.status);
  if (opts.cursor) params.set('cursor', opts.cursor);
  if (opts.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return api<unknown>(apiBaseUrl, `/api/unified-memory/intents${query ? `?${query}` : ''}`);
}

export function IntentRow({ intent }: { intent: IntentItem }) {
  const status = enumLabel(intent.status, INTENT_STATUS);
  return <div className="fact">
    <div>
      <div>{intent.title}</div>
      <small>{[intent.due ? `到期 ${formatMoment(intent.due)}` : '', intent.scope].filter(Boolean).join(' · ')}</small>
    </div>
    {status && <span className="tag" style={{ marginTop: 0 }}>{status}</span>}
  </div>;
}

export default function IntentView({ apiBaseUrl, connected }: { apiBaseUrl: string; connected: boolean }) {
  const [items, setItems] = useState<IntentItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (opts: { cursor?: string | null } = {}) => {
    if (!connected) return;
    if (opts.cursor) setLoadingMore(true); else setLoading(true);
    try {
      const payload = await fetchIntents(apiBaseUrl, { cursor: opts.cursor ?? null, limit: 50 });
      const page = normalizeIntents(payload);
      setItems((current) => (opts.cursor ? [...current, ...page.items] : page.items));
      setCursor(page.nextCursor);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); setLoadingMore(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { void load(); }, [load]);

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  if (!connected) return <section aria-label="待办"><div className="note">等待 Atlas 后端连接后读取待办。</div></section>;

  return <section aria-label="待办">
    <div className="filterbar" style={{ marginBottom: 10 }}>
      <button className="btn ghost" disabled={loading || !connected} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
      <span className="empty-note">你交代过的事与到期事项，来自真实对话与确认，不会自动把猜测算作承诺。</span>
    </div>

    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取待办…</b></div></div>}
    {!loading && degraded && <div className="note">待办功能未启用：服务端尚未接线（501）。组件已就绪，等后端启用后会自动可用。</div>}
    {!loading && !degraded && error && <div className="error-note" role="alert"><span>读取待办失败：{error}</span></div>}
    {!loading && !error && items.length === 0 &&
      <div className="list glass"><div className="empty"><ListTodo size={22} /><b>没有待办</b>你在对话里交代、并且确认过的事项会出现在这里。</div></div>}

    {!loading && !error && items.length > 0 && <div className="list glass">
      {items.map((intent) => <IntentRow key={intent.id} intent={intent} />)}
    </div>}

    {cursor && !loading && !error && <div style={{ textAlign: 'center', marginTop: 14 }}>
      <button className="btn" disabled={loadingMore || !connected} onClick={() => void load({ cursor })}>
        {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}加载更多
      </button>
    </div>}
  </section>;
}
