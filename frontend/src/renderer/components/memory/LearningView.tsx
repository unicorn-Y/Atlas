/**
 * LearningView（T12.1）—— 学到的方法视图。
 * GET /api/unified-memory/learning?stage&type&cursor（契约 §6/§6.1：方法、
 * 试验、能力缺口；试验候选与已验证方法分开显示，诊断字段不当成功证明）。
 * 当前服务端 501：degraded「功能未启用」，不报错。
 */
import { useCallback, useEffect, useState } from 'react';
import { GraduationCap, LoaderCircle, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';
import { enumLabel, isFeatureDisabled, isNotEnabled, pageOf, str } from './common';

export interface LearningItem {
  id: string;
  title: string;
  kind: string;
  stage: string;
  status: string;
  detail: string;
}

const LEARNING_KINDS: Record<string, string> = {
  METHOD: '方法', KNOWLEDGE: '知识', STATE_UPDATE: '状态更新', STATE: '状态更新',
  COUNTEREXAMPLE: '反例', STRATEGY: '策略', PREDICTION: '预测', CAPABILITY_GAP: '能力缺口',
  EXPERIENCE: '经历',
};

/** 已验证 vs 候选：按 status/stage 判断；两者都不是时归入候选（宁保守，不装成已验证）。 */
export function isVerifiedMethod(item: Pick<LearningItem, 'status' | 'stage'>): boolean {
  const key = (item.status || item.stage).toUpperCase();
  return key === 'VERIFIED' || key === 'ACTIVE' || key === 'VALIDATED';
}

export function normalizeLearningItem(value: unknown): LearningItem | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const id = str(raw.id ?? raw.skill_id ?? raw.item_id ?? raw.ref);
  const title = str(raw.title ?? raw.name ?? raw.method ?? raw.summary);
  if (!id && !title) return null;
  return {
    id: id || title,
    title: title || '(未写明内容)',
    kind: str(raw.type ?? raw.kind),
    stage: str(raw.stage),
    status: str(raw.status),
    detail: str(raw.detail ?? raw.description ?? raw.note),
  };
}

export function normalizeLearning(payload: unknown): { items: LearningItem[]; nextCursor: string | null } {
  const page = pageOf(payload);
  return { items: page.items.map(normalizeLearningItem).filter((item): item is LearningItem => item !== null), nextCursor: page.nextCursor };
}

export async function fetchLearning(
  apiBaseUrl: string,
  opts: { stage?: string; type?: string; cursor?: string | null; limit?: number } = {},
): Promise<unknown> {
  const params = new URLSearchParams();
  if (opts.stage) params.set('stage', opts.stage);
  if (opts.type) params.set('type', opts.type);
  if (opts.cursor) params.set('cursor', opts.cursor);
  if (opts.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return api<unknown>(apiBaseUrl, `/api/unified-memory/learning${query ? `?${query}` : ''}`);
}

export function LearningRow({ item }: { item: LearningItem }) {
  const kind = enumLabel(item.kind, LEARNING_KINDS);
  return <div className="fact">
    <div>
      <div>{item.title}</div>
      {item.detail && <small>{item.detail}</small>}
    </div>
    {kind && <span className="tag" style={{ marginTop: 0 }}>{kind}</span>}
  </div>;
}

function Group({ title, note, items }: { title: string; note: string; items: LearningItem[] }) {
  if (items.length === 0) return null;
  return <section className="mem-group" style={{ marginBottom: 22 }}>
    <h3>{title}<span>{items.length}</span></h3>
    <div className="list glass">{items.map((item, index) => <LearningRow key={item.id + index} item={item} />)}</div>
    <p className="empty-note">{note}</p>
  </section>;
}

export default function LearningView({ apiBaseUrl, connected }: { apiBaseUrl: string; connected: boolean }) {
  const [items, setItems] = useState<LearningItem[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async (opts: { cursor?: string | null } = {}) => {
    if (!connected) return;
    if (opts.cursor) setLoadingMore(true); else setLoading(true);
    try {
      const payload = await fetchLearning(apiBaseUrl, { cursor: opts.cursor ?? null, limit: 50 });
      const page = normalizeLearning(payload);
      setItems((current) => (opts.cursor ? [...current, ...page.items] : page.items));
      setCursor(page.nextCursor);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); setLoadingMore(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { void load(); }, [load]);

  const degraded = isFeatureDisabled(error) || isNotEnabled(error);
  if (!connected) return <section aria-label="学到的方法"><div className="note">等待 Atlas 后端连接后读取学到的方法。</div></section>;
  const verified = items.filter((item) => isVerifiedMethod(item));
  const candidates = items.filter((item) => !isVerifiedMethod(item));

  return <section aria-label="学到的方法">
    <div className="filterbar" style={{ marginBottom: 10 }}>
      <button className="btn ghost" disabled={loading || !connected} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
      <span className="empty-note">只统计有真实结果的改进；试验候选不会标成已验证。</span>
    </div>

    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取学到的方法…</b></div></div>}
    {!loading && degraded && <div className="note">学习方法功能未启用：服务端尚未接线（501）。组件已就绪，等后端启用后会自动可用。</div>}
    {!loading && !degraded && error && <div className="error-note" role="alert"><span>读取学习记录失败：{error}</span></div>}
    {!loading && !error && items.length === 0 &&
      <div className="list glass"><div className="empty"><GraduationCap size={22} /><b>还没有记录到学到的内容</b>Atlas 在真实任务里验证过的方法与反例会出现在这里。</div></div>}

    {!loading && !error && items.length > 0 && <>
      <Group title="已验证的方法" note="在真实结果里验证过的方法。" items={verified} />
      <Group title="试验候选（未验证）" note="候选改进，还没有真实结果确认，不会当成功展示。" items={candidates} />
    </>}

    {cursor && !loading && !error && <div style={{ textAlign: 'center', marginTop: 14 }}>
      <button className="btn" disabled={loadingMore || !connected} onClick={() => void load({ cursor })}>
        {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}加载更多
      </button>
    </div>}
  </section>;
}
