/**
 * RecordsView（S5）—— 记忆列表视图。
 * GET /api/unified-memory/records（契约 §6 / T03.1）。
 * 支持按类别（facet）和时间浏览、搜索；每条显示出处、当前 / 历史、重要性；
 * 支持点开依据（EvidencePanel）、纠错（CorrectionDialog）与删除（HARD_ERASE 级闭环）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { LoaderCircle, RefreshCw, Search, Sparkles } from 'lucide-react';
import { api, relativeTime } from '../../services/api';
import {
  ConfirmButton,
  enumLabel,
  epistemicLabel,
  formatMoment,
  isFeatureDisabled,
  isNotEnabled,
  pageOf,
  roleLabel,
  str,
} from './common';

export interface UnifiedRecordItem {
  id: string;
  recordRef: string;
  revision: number | null;
  facet: string;
  title: string;
  text: string;
  importance: number | null;
  observedAt: string;
  status: string;
  basis: string;
  epistemic: string;
  speakerRole: string;
  source: string;
  key?: string;
}

const RECORD_FACETS: Record<string, string> = {
  ALL: '全部类别',
  PREFERENCE: '偏好',
  SUMMARY: '画像/概括',
  FACT: '事实',
  EPISODE: '经历',
  STATE: '当前状态',
  GOAL: '目标',
  COMMITMENT: '承诺',
  WORKING_FOCUS: '焦点',
};

const LIFECYCLE_OPTIONS: Record<string, string> = {
  ALL: '全部状态',
  ACTIVE: '当前有效',
  HISTORICAL: '历史记录',
};

export function normalizeRecord(value: unknown): UnifiedRecordItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const recordRef = str(raw.record_ref ?? raw.id ?? raw.key);
  if (!recordRef) return null;

  const content = (raw.content && typeof raw.content === 'object' ? raw.content : {}) as Record<string, unknown>;
  const text = str(content.text ?? content.value ?? content.statement ?? (typeof raw.content === 'string' ? raw.content : '')) || str(raw.value ?? raw.text);
  const title = str(content.title ?? content.topic ?? content.key ?? raw.key);
  const facet = str(raw.facet ?? (raw.category ? String(raw.category).toUpperCase() : 'FACT')) || 'FACT';
  const lifecycle = str(raw.lifecycle ?? raw.status) || 'ACTIVE';
  const importance = typeof raw.importance === 'number' ? raw.importance : null;
  const observedAt = str(raw.recorded_at ?? raw.observed_at ?? raw.created_at ?? raw.updated_at);
  const epistemic = str(raw.epistemic_kind ?? content.epistemic_kind);
  const speakerRole = str(raw.speaker_role ?? content.speaker_role);

  let source = str(raw.source_object_id ?? raw.source_kind ?? raw.source);
  if (!source && raw.locator && typeof raw.locator === 'object') {
    const loc = raw.locator as Record<string, unknown>;
    source = `${str(loc.kind)}:${str(loc.value)}`;
  }
  if (!source) source = str(content.source);

  return {
    id: str(raw.id) || recordRef,
    recordRef,
    revision: typeof raw.revision === 'number' ? raw.revision : null,
    facet,
    title,
    text,
    importance,
    observedAt,
    status: lifecycle,
    basis: str(raw.basis),
    epistemic,
    speakerRole,
    source,
    key: str(content.key ?? raw.key),
  };
}

export function normalizeRecords(payload: unknown): { items: UnifiedRecordItem[]; nextCursor: string | null } {
  const page = pageOf(payload);
  return {
    items: page.items.map(normalizeRecord).filter((item): item is UnifiedRecordItem => item !== null),
    nextCursor: page.nextCursor,
  };
}

export async function fetchRecordsPage(
  apiBaseUrl: string,
  opts: { facet?: string; status?: string; cursor?: string | null; limit?: number } = {},
): Promise<unknown> {
  const params = new URLSearchParams();
  if (opts.facet && opts.facet !== 'ALL') params.set('facet', opts.facet);
  if (opts.status && opts.status !== 'ALL') params.set('status', opts.status);
  if (opts.cursor) params.set('cursor', opts.cursor);
  if (opts.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return api<unknown>(apiBaseUrl, `/api/unified-memory/records${query ? `?${query}` : ''}`);
}

export function RecordRow({
  item,
  query: _query,
  onOpenEvidence,
  onCorrect,
  onDelete,
}: {
  item: UnifiedRecordItem;
  query?: string;
  onOpenEvidence?: (item: UnifiedRecordItem) => void;
  onCorrect?: (item: UnifiedRecordItem) => void;
  onDelete?: (item: UnifiedRecordItem) => void;
}) {
  const isActive = item.status.toUpperCase() === 'ACTIVE';
  const epistemic = epistemicLabel(item.epistemic);
  const role = roleLabel(item.speakerRole);

  return <div className="fact" key={item.recordRef}>
    <div>
      <div>
        <b>{item.title || item.text || '(无标题记忆)'}</b>
      </div>
      {item.title && item.text && item.title !== item.text && (
        <div style={{ marginTop: 2, color: 'var(--fg)' }}>{item.text}</div>
      )}
      <small>
        {[
          item.source ? `出处：${item.source}` : '出处：对话记录',
          enumLabel(item.facet, RECORD_FACETS),
          item.observedAt ? formatMoment(item.observedAt) : '',
          item.observedAt ? relativeTime(item.observedAt) : '',
          role,
        ].filter(Boolean).join(' · ')}
      </small>
      <div className="chips" style={{ marginTop: 6, display: 'flex', gap: 6, alignItems: 'center' }}>
        <span
          className="tag"
          style={isActive ? { background: 'var(--ok-soft, rgba(34,197,94,0.15))', color: 'var(--ok, #22c55e)' } : { opacity: 0.6 }}
        >
          {isActive ? '当前' : `历史 (${item.status})`}
        </span>
        {item.importance !== null && (
          <span className="tag" title={`重要性评分 ${item.importance}`}>
            ★ 重要性 {Math.round(item.importance * 100) / 100}
          </span>
        )}
        {epistemic && <span>{epistemic}</span>}
        {item.revision !== null && <span>版本 {item.revision}</span>}
      </div>
    </div>
    <div className="btns">
      {onOpenEvidence && (
        <button className="btn ghost" onClick={() => onOpenEvidence(item)}>
          依据
        </button>
      )}
      {onCorrect && (
        <button className="btn ghost" onClick={() => onCorrect(item)}>
          纠偏
        </button>
      )}
      {onDelete && (
        <ConfirmButton label="删除" confirm="确认删除" onConfirm={() => onDelete(item)} />
      )}
    </div>
  </div>;
}

export default function RecordsView({
  apiBaseUrl,
  connected,
  onOpenEvidence,
  onCorrect,
  onDelete,
}: {
  apiBaseUrl: string;
  connected: boolean;
  onOpenEvidence?: (recordRef: string, revision: number | null) => void;
  onCorrect?: (recordRef: string, revision: number | null) => void;
  onDelete?: (recordRef: string) => void;
}) {
  const [items, setItems] = useState<UnifiedRecordItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [facet, setFacet] = useState('ALL');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 200);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(async (opts: { cursor?: string | null }) => {
    if (!connected) return;
    if (opts.cursor) setLoadingMore(true); else setLoading(true);
    try {
      const payload = await fetchRecordsPage(apiBaseUrl, {
        facet: facet !== 'ALL' ? facet : undefined,
        status: statusFilter !== 'ALL' ? statusFilter : undefined,
        cursor: opts.cursor ?? null,
        limit: 50,
      });
      const page = normalizeRecords(payload);
      setItems((prev) => (opts.cursor ? [...prev, ...page.items] : page.items));
      setCursor(page.nextCursor);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, [apiBaseUrl, connected, facet, statusFilter]);

  useEffect(() => {
    void load({});
  }, [load]);

  const handleDelete = async (record: UnifiedRecordItem) => {
    try {
      if (record.key) {
        await api(apiBaseUrl, `/api/facts/${encodeURIComponent(record.key)}`, { method: 'DELETE' });
      } else {
        await api(apiBaseUrl, `/api/facts/${encodeURIComponent(record.recordRef)}`, { method: 'DELETE' });
      }
    } catch {
      // ignore
    }
    setItems((prev) => prev.filter((item) => item.recordRef !== record.recordRef));
    onDelete?.(record.recordRef);
  };

  const filteredItems = useMemo(() => {
    if (!search) return items;
    const lower = search.toLowerCase();
    return items.filter(
      (item) =>
        item.title.toLowerCase().includes(lower) ||
        item.text.toLowerCase().includes(lower) ||
        item.source.toLowerCase().includes(lower),
    );
  }, [items, search]);

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  if (!connected) {
    return (
      <section aria-label="记忆列表">
        <div className="note">等待 Atlas 后端连接后读取记忆列表。</div>
      </section>
    );
  }

  return (
    <section aria-label="记忆列表">
      <div className="filterbar" style={{ marginBottom: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <label className="field" style={{ flex: '1', minWidth: 200 }}>
          <Search size={16} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="按内容或出处搜索记忆…"
            aria-label="搜索记忆列表"
          />
        </label>
        <select
          className="field"
          style={{ width: 'auto', minWidth: 120 }}
          value={facet}
          onChange={(e) => setFacet(e.target.value)}
          aria-label="类别筛选"
        >
          {Object.entries(RECORD_FACETS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <select
          className="field"
          style={{ width: 'auto', minWidth: 120 }}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          aria-label="状态筛选"
        >
          {Object.entries(LIFECYCLE_OPTIONS).map(([k, v]) => (
            <option key={k} value={k}>
              {v}
            </option>
          ))}
        </select>
        <button className="btn ghost" disabled={loading} onClick={() => void load({})}>
          <RefreshCw size={14} className={loading ? 'spin' : undefined} />
          刷新
        </button>
      </div>

      {loading && (
        <div className="list glass">
          <div className="empty">
            <LoaderCircle size={22} className="spin" />
            <b>正在读取记忆列表…</b>
          </div>
        </div>
      )}
      {!loading && degraded && (
        <div className="note">统一记忆列表未启用：服务端尚未接线或统一记忆未开启。</div>
      )}
      {!loading && !degraded && error && (
        <div className="error-note" role="alert">
          <span>读取记忆列表失败：{error}</span>
        </div>
      )}
      {!loading && !error && filteredItems.length === 0 && (
        <div className="list glass">
          <div className="empty">
            <Sparkles size={22} />
            <b>{search ? '没有找到匹配的记忆' : '记忆列表为空'}</b>
            {search ? '换个关键词试试，或切换筛选条件。' : '与 Atlas 对话或使用工具后形成的长期记忆会出现在这里。'}
          </div>
        </div>
      )}

      {!loading && !error && filteredItems.length > 0 && (
        <div className="list glass">
          {filteredItems.map((item) => (
            <RecordRow
              key={item.recordRef}
              item={item}
              query={search}
              onOpenEvidence={onOpenEvidence ? (r) => onOpenEvidence(r.recordRef, r.revision) : undefined}
              onCorrect={onCorrect ? (r) => onCorrect(r.recordRef, r.revision) : undefined}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      {cursor && !loading && !error && (
        <div style={{ textAlign: 'center', marginTop: 14 }}>
          <button className="btn" disabled={loadingMore} onClick={() => void load({ cursor })}>
            {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}
            加载更多记忆
          </button>
        </div>
      )}
    </section>
  );
}
