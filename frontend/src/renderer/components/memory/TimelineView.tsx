/**
 * TimelineView（T12.1）—— 日常时间线。
 * GET /api/unified-memory/timeline?start&end&cursor（契约 §6：事件时间排序，
 * 时间未知单独分组 → 服务端 items/unknown 两段原样呈现，不在前端伪造时间排序）。
 * 每条带「依据 / 纠错」入口：条目点开弹 EvidencePanel，纠错走 CorrectionDialog。
 */
import { useCallback, useEffect, useState } from 'react';
import { CalendarClock, HelpCircle, LoaderCircle, RefreshCw } from 'lucide-react';
import { api, relativeTime } from '../../services/api';
import {
  enumLabel, epistemicLabel, formatMoment, isFeatureDisabled, isNotEnabled,
  pageOf, roleLabel, stripPrefix, str,
} from './common';

export interface TimelineItem {
  recordRef: string;
  revision: number | null;
  facet: string;
  timeStatus: string;
  from: string | null;
  to: string | null;
  title: string;
  text: string;
  participants: string[];
  speakerRole: string;
  epistemic: string;
  sourceRefCount: number;
}

function firstText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map((entry) => str(entry)).filter(Boolean).join('；');
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>;
    return firstText(record.text ?? record.value ?? record.summary ?? '');
  }
  return '';
}

/** 服务端事件条目 → 页面模型；缺 record_ref 的条目丢弃（没有依据可看的条目不假装可点）。 */
export function normalizeTimelineItem(value: unknown): TimelineItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const recordRef = str(raw.record_ref ?? raw.id);
  if (!recordRef) return null;
  const content = (raw.content && typeof raw.content === 'object' ? raw.content : {}) as Record<string, unknown>;
  const validTime = (raw.valid_time && typeof raw.valid_time === 'object' ? raw.valid_time : {}) as Record<string, unknown>;
  const participants = Array.isArray(content.participants)
    ? content.participants.map((entry) => firstText((entry as Record<string, unknown>)?.name ?? entry)).filter(Boolean)
    : [];
  const topic = stripPrefix(str(content.topic));
  const text = firstText(content.text ?? content);
  const sourceRefs = raw.source_refs;
  return {
    recordRef,
    revision: typeof raw.revision === 'number' ? raw.revision : null,
    facet: str(raw.facet),
    timeStatus: str(validTime.time_status) || str(raw.time_status),
    from: str(validTime.valid_from) || null,
    to: str(validTime.valid_to) || null,
    title: topic,
    text,
    participants,
    speakerRole: str(raw.speaker_role) || str(content.speaker_role),
    epistemic: str(raw.epistemic_kind) || str(content.epistemic_kind),
    sourceRefCount: Array.isArray(sourceRefs) ? sourceRefs.length : 0,
  };
}

export function normalizeTimeline(payload: unknown): { items: TimelineItem[]; unknown: TimelineItem[]; nextCursor: string | null } {
  const record = (payload && typeof payload === 'object' ? payload : {}) as Record<string, unknown>;
  const timed = pageOf({ items: record.items ?? payload, next_cursor: record.next_cursor });
  const untimed = pageOf({ items: record.unknown ?? [] });
  const pick = (values: unknown[]) => values.map(normalizeTimelineItem).filter((item): item is TimelineItem => item !== null);
  return {
    items: pick(timed.items),
    unknown: pick(untimed.items),
    nextCursor: timed.nextCursor,
  };
}

export async function fetchTimelinePage(
  apiBaseUrl: string,
  opts: { start?: string; end?: string; cursor?: string | null; limit?: number } = {},
): Promise<unknown> {
  const params = new URLSearchParams();
  if (opts.start) params.set('start', opts.start);
  if (opts.end) params.set('end', opts.end);
  if (opts.cursor) params.set('cursor', opts.cursor);
  if (opts.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return api<unknown>(apiBaseUrl, `/api/unified-memory/timeline${query ? `?${query}` : ''}`);
}

const FACETS: Record<string, string> = {
  EPISODE: '事件', SUMMARY: '总结', STATE: '状态', PREFERENCE: '偏好',
  GOAL: '目标', COMMITMENT: '承诺', WORKING_FOCUS: '焦点',
};

export function ItemRow({ item, onOpenEvidence, onCorrect }: {
  item: TimelineItem;
  onOpenEvidence?: (item: TimelineItem) => void;
  onCorrect?: (item: TimelineItem) => void;
}) {
  const epistemic = epistemicLabel(item.epistemic);
  const role = roleLabel(item.speakerRole);
  return <div className="fact">
    <div>
      <div>{item.title || item.text || '(无文字内容)'}</div>
      {item.title && item.text && item.title !== item.text && <small>{item.text}</small>}
      <small>
        {[
          item.from ? formatMoment(item.from) : '',
          item.from ? relativeTime(item.from) : '',
          role,
          enumLabel(item.facet, FACETS),
          ...item.participants,
        ].filter(Boolean).join(' · ')}
        {item.sourceRefCount > 0 ? ` · 原话 ${item.sourceRefCount} 条` : ''}
      </small>
      <div className="chips" style={{ marginTop: 6 }}>
        {epistemic && <span>{epistemic}</span>}
        {item.revision !== null && <span>版本 {item.revision}</span>}
      </div>
    </div>
    <div className="btns">
      <button className="btn ghost" onClick={() => onOpenEvidence?.(item)}>依据</button>
      <button className="btn ghost" onClick={() => onCorrect?.(item)}>纠错</button>
    </div>
  </div>;
}

export default function TimelineView({ apiBaseUrl, connected, onOpenEvidence, onCorrect }: {
  apiBaseUrl: string;
  connected: boolean;
  onOpenEvidence?: (item: TimelineItem) => void;
  onCorrect?: (item: TimelineItem) => void;
}) {
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [unknown, setUnknown] = useState<TimelineItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [range, setRange] = useState({ start: '', end: '' });
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (opts: { cursor?: string | null }) => {
    if (!connected) return;
    if (opts.cursor) setLoadingMore(true); else setLoading(true);
    try {
      const payload = await fetchTimelinePage(apiBaseUrl, {
        start: range.start || undefined, end: range.end || undefined, cursor: opts.cursor ?? null, limit: 50,
      });
      const page = normalizeTimeline(payload);
      setItems((current) => (opts.cursor ? [...current, ...page.items] : page.items));
      setUnknown((current) => (opts.cursor ? [...current, ...page.unknown] : page.unknown));
      setCursor(page.nextCursor);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false); setLoadingMore(false);
    }
  }, [apiBaseUrl, connected, range]);

  useEffect(() => { void load({}); }, [load]);

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  const hasContent = items.length > 0 || unknown.length > 0;
  // 未连接：显示等待提示，不卡在「正在读取」（页面级离线说明照常显示）。
  if (!connected) return <section aria-label="日常时间线"><div className="note">等待 Atlas 后端连接后读取时间线。</div></section>;

  return <section aria-label="日常时间线">
    <div className="filterbar" style={{ marginBottom: 10 }}>
      <label className="field" style={{ flex: 'none', minWidth: 170 }}>
        <CalendarClock size={16} />
        <input type="date" aria-label="开始日期" value={start} onChange={(event) => setStart(event.target.value)} />
      </label>
      <label className="field" style={{ flex: 'none', minWidth: 170 }}>
        <CalendarClock size={16} />
        <input type="date" aria-label="结束日期" value={end} onChange={(event) => setEnd(event.target.value)} />
      </label>
      <button className="btn" disabled={!connected} onClick={() => setRange({ start, end })}>按时间过滤</button>
      <button className="btn ghost" disabled={loading || !connected} onClick={() => { setStart(''); setEnd(''); setRange({ start: '', end: '' }); }}>清除</button>
      <button className="btn ghost" disabled={loading || !connected} onClick={() => void load({})}><RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新</button>
    </div>

    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取时间线…</b></div></div>}
    {!loading && degraded && <div className="note">时间线功能未启用：服务端尚未接线或统一记忆未开启。这不是错误，等后端启用后会自动可用。</div>}
    {!loading && !degraded && error && <div className="error-note" role="alert"><span>读取时间线失败：{error}</span></div>}
    {!loading && !error && !hasContent && <div className="list glass"><div className="empty"><CalendarClock size={22} /><b>还没有可显示的经历</b>和 Atlas 聊天、使用工具的经历会按时间出现在这里。</div></div>}

    {!loading && !error && items.length > 0 && <div className="list glass">{items.map((item) =>
      <ItemRow key={item.recordRef} item={item} onOpenEvidence={onOpenEvidence} onCorrect={onCorrect} />)}
    </div>}

    {!loading && !error && unknown.length > 0 && <section className="mem-group" style={{ marginTop: 22 }}>
      <h3><HelpCircle size={14} aria-hidden /> 时间未知<span>{unknown.length}</span></h3>
      <div className="list glass">{unknown.map((item) =>
        <ItemRow key={item.recordRef} item={item} onOpenEvidence={onOpenEvidence} onCorrect={onCorrect} />)}
      </div>
      <p className="empty-note">这些经历没有可靠的发生时间，单独列出，不混入上面的时间排序。</p>
    </section>}

    {cursor && !loading && !error && <div style={{ textAlign: 'center', marginTop: 14 }}>
      <button className="btn" disabled={loadingMore || !connected} onClick={() => void load({ cursor })}>
        {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}加载更早的经历
      </button>
    </div>}
  </section>;
}
