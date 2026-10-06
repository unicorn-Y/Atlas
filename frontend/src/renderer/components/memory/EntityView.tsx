/**
 * EntityView（T12.1）—— 人事（人物/事物）视图。
 * GET /api/unified-memory/entities?query&cursor（契约 §6：实体和候选别名，
 * 未决关联不装成已确认 → PROPOSED/VERIFIED 徽标如实显示，不洗白文案）。
 */
import { useEffect, useState } from 'react';
import { LoaderCircle, Users } from 'lucide-react';
import { api } from '../../services/api';
import { enumLabel, isFeatureDisabled, isNotEnabled, pageOf, str } from './common';

export interface EntityItem {
  id: string;
  name: string;
  type: string;
  aliases: string[];
  aliasStatus: string;
  status: string;
}

const ENTITY_TYPES: Record<string, string> = {
  PERSON: '人物', ORGANIZATION: '组织', ORG: '组织', PLACE: '地点', LOCATION: '地点',
  PROJECT: '项目', THING: '事物', OBJECT: '物品', CONCEPT: '概念', DATE: '时间',
};

/** alias_status / status 原样映射；未知状态不翻译，直接显示原值（不装成已确认）。 */
export function entityStatusLabel(item: Pick<EntityItem, 'aliasStatus' | 'status'>): { text: string; verified: boolean; proposed: boolean } {
  const raw = item.aliasStatus || item.status;
  const key = raw.toUpperCase();
  if (key === 'VERIFIED' || key === 'CONFIRMED' || key === 'RESOLVED') return { text: '已确认', verified: true, proposed: false };
  if (key === 'PROPOSED' || key === 'CANDIDATE' || key === 'PENDING') return { text: '待确认', verified: false, proposed: true };
  return { text: raw, verified: false, proposed: false };
}

export function normalizeEntity(value: unknown): EntityItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const id = str(raw.id ?? raw.entity_id);
  if (!id) return null;
  const aliases = Array.isArray(raw.aliases) ? raw.aliases.map((entry) => str(entry)).filter(Boolean) : [];
  return {
    id,
    name: str(raw.name) || aliases[0] || id,
    type: str(raw.type ?? raw.kind),
    aliases,
    aliasStatus: str(raw.alias_status ?? raw.aliasStatus),
    status: str(raw.status),
  };
}

export function normalizeEntities(payload: unknown): { items: EntityItem[]; nextCursor: string | null } {
  const page = pageOf(payload);
  return { items: page.items.map(normalizeEntity).filter((item): item is EntityItem => item !== null), nextCursor: page.nextCursor };
}

export async function fetchEntities(
  apiBaseUrl: string,
  opts: { query?: string; cursor?: string | null; limit?: number } = {},
): Promise<unknown> {
  const params = new URLSearchParams();
  if (opts.query) params.set('query', opts.query);
  if (opts.cursor) params.set('cursor', opts.cursor);
  if (opts.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return api<unknown>(apiBaseUrl, `/api/unified-memory/entities${query ? `?${query}` : ''}`);
}

export function EntityRow({ entity }: { entity: EntityItem }) {
  const badge = entityStatusLabel(entity);
  return <div className="fact">
    <div>
      <div>{entity.name}</div>
      <small>{[enumLabel(entity.type, ENTITY_TYPES), ...entity.aliases.filter((alias) => alias !== entity.name)].filter(Boolean).join(' · ')}</small>
      <div className="chips" style={{ marginTop: 6 }}>
        {badge.text && <span style={badge.verified ? { background: 'var(--ok-soft)', color: 'var(--ok)' } : undefined}>{badge.text}</span>}
      </div>
    </div>
  </div>;
}

export default function EntityView({ apiBaseUrl, connected }: { apiBaseUrl: string; connected: boolean }) {
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [items, setItems] = useState<EntityItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!connected) return;
    let alive = true;
    setLoading(true);
    fetchEntities(apiBaseUrl, { query: search, limit: 50 })
      .then((payload) => {
        if (!alive) return;
        const page = normalizeEntities(payload);
        setItems(page.items); setCursor(page.nextCursor); setError('');
      })
      .catch((exc: unknown) => { if (alive) setError(exc instanceof Error ? exc.message : String(exc)); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [apiBaseUrl, connected, search]);

  const loadMore = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = normalizeEntities(await fetchEntities(apiBaseUrl, { query: search, cursor, limit: 50 }));
      setItems((current) => [...current, ...page.items]); setCursor(page.nextCursor); setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoadingMore(false); }
  };

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  if (!connected) return <section aria-label="人事"><div className="note">等待 Atlas 后端连接后读取人物与事物。</div></section>;

  return <section aria-label="人事">
    <div className="filterbar" style={{ marginBottom: 10 }}>
      <label className="field">
        <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按名字搜索人物或事物" aria-label="搜索实体" />
      </label>
    </div>

    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取人物与事物…</b></div></div>}
    {!loading && degraded && <div className="note">人事视图功能未启用：服务端尚未接线或统一记忆未开启。这不是错误，等后端启用后会自动可用。</div>}
    {!loading && !degraded && error && <div className="error-note" role="alert"><span>读取实体失败：{error}</span></div>}
    {!loading && !error && items.length === 0 &&
      <div className="list glass"><div className="empty"><Users size={22} /><b>{search ? '没有匹配的人物或事物' : '还没有人物或事物'}</b>Atlas 从经历里整理出的人物、项目与事物会出现在这里。</div></div>}

    {!loading && !error && items.length > 0 && <div className="list glass">
      {items.map((entity) => <EntityRow key={entity.id} entity={entity} />)}
    </div>}

    {cursor && !loading && !error && <div style={{ textAlign: 'center', marginTop: 14 }}>
      <button className="btn" disabled={loadingMore || !connected} onClick={() => void loadMore()}>
        {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}加载更多
      </button>
    </div>}
  </section>;
}
