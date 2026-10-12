/**
 * MemoryChangesView —— 记忆变动记录。
 * GET /api/memory/changes：后端对 MemOS 本地库做快照对比，记录每一次新增 / 删除 / 修改 /
 * 淡忘 / 归档 / 评分变化，并附改动前后的字段内容与变动原因（来自 MemOS 事件）。
 */
import { Fragment, useCallback, useEffect, useState } from 'react';
import { Archive, ChevronDown, ChevronRight, ExternalLink, GitCompare, LoaderCircle, Pause, Play, RefreshCw, Trash2 } from 'lucide-react';
import { api, relativeTime } from '../../services/api';

interface ChangeField { key: string; label: string }
export interface ChangeItem {
  id: number;
  ts: string;
  entity: string;
  entity_label: string;
  entity_id: string;
  op: string;
  op_label: string;
  title: string;
  reason: string;
  fields: ChangeField[];
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}
interface ChangesPayload {
  items: ChangeItem[];
  next_before: number | null;
  stats: Record<string, number>;
  memos_db: boolean;
}

// 能在这里删除（技能是归档）的记忆类型，对应后端 /api/memory/delete
const DELETABLE = new Set(['user_facts', 'traces', 'policies', 'world_model', 'skills']);
const OPS: Array<{ value: string; label: string }> = [
  { value: '', label: '全部' },
  { value: 'added', label: '新增' },
  { value: 'updated', label: '修改' },
  { value: 'removed', label: '删除' },
  { value: 'decayed', label: '淡忘' },
  { value: 'archived', label: '归档' },
  { value: 'scored', label: '评分变化' },
];
const ENTITIES: Array<{ value: string; label: string }> = [
  { value: '', label: '全部类型' },
  { value: 'user_facts', label: '关于你' },
  { value: 'traces', label: '对话记录' },
  { value: 'episodes', label: '情节' },
  { value: 'policies', label: '策略' },
  { value: 'world_model', label: '世界模型' },
  { value: 'skills', label: '技能' },
  { value: 'feedback', label: '反馈' },
];
const OP_COLOR: Record<string, string> = {
  added: '#1a7f37', removed: '#cf222e', updated: '#9a6700', decayed: '#6e7781',
  archived: '#8250df', scored: '#0969da',
};

function show(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if ((trimmed.startsWith('[') || trimmed.startsWith('{')) && trimmed.length < 4000) {
      try { return JSON.stringify(JSON.parse(trimmed), null, 2); } catch { /* plain text */ }
    }
    return value;
  }
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3);
  return JSON.stringify(value, null, 2);
}

function FieldTable({ item }: { item: ChangeItem }) {
  const keys = item.op === 'updated' || item.op === 'scored' || item.op === 'decayed' || item.op === 'archived'
    ? item.fields
    : item.fields.filter((f) => show((item.after ?? item.before)?.[f.key]) !== '—');
  const both = item.before !== null && item.after !== null;
  const cell = { padding: '6px 8px', borderTop: '1px solid var(--line)', verticalAlign: 'top' as const, textAlign: 'left' as const };
  const pre = { margin: 0, whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const, fontFamily: 'inherit', fontSize: 12 };
  return <table style={{ width: '100%', borderCollapse: 'collapse', marginTop: 6, fontSize: 12, tableLayout: 'fixed' }}>
    <thead><tr>
      <th style={{ ...cell, width: 110 }}>字段</th>
      {item.before !== null && <th style={cell}>{both ? '之前' : '删除前的内容'}</th>}
      {item.after !== null && <th style={cell}>{both ? '之后' : '内容'}</th>}
    </tr></thead>
    <tbody>
      {keys.map((f) => <tr key={f.key}>
        <td style={cell}>{f.label}</td>
        {item.before !== null && <td style={{ ...cell, background: both ? 'rgba(207,34,46,0.06)' : undefined }}><pre style={pre}>{show(item.before?.[f.key])}</pre></td>}
        {item.after !== null && <td style={{ ...cell, background: both ? 'rgba(26,127,55,0.06)' : undefined }}><pre style={pre}>{show(item.after?.[f.key])}</pre></td>}
      </tr>)}
    </tbody>
  </table>;
}

export default function MemoryChangesView({ apiBaseUrl, connected }: { apiBaseUrl: string; connected: boolean }) {
  const [items, setItems] = useState<ChangeItem[]>([]);
  const [stats, setStats] = useState<Record<string, number>>({});
  const [next, setNext] = useState<number | null>(null);
  const [op, setOp] = useState('');
  const [entity, setEntity] = useState('');
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [auto, setAuto] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [memosDb, setMemosDb] = useState(true);
  const [paused, setPaused] = useState(false);
  const [viewerUrl, setViewerUrl] = useState('http://127.0.0.1:18800');
  const [busy, setBusy] = useState('');
  const [canPause, setCanPause] = useState(false);

  const loadState = useCallback(async () => {
    if (!connected) return;
    try {
      const state = await api<{ paused: boolean; viewer_url: string; can_pause?: boolean }>(apiBaseUrl, '/api/memory/state');
      setPaused(state.paused); setViewerUrl(state.viewer_url);
      setCanPause(state.can_pause !== false);
    } catch { /* state is optional */ }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void loadState(); }, [loadState]);

  const togglePause = async () => {
    setBusy('pause');
    try {
      const state = await api<{ paused: boolean }>(apiBaseUrl, '/api/memory/pause', { method: 'POST', json: { paused: !paused } });
      setPaused(state.paused);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const remove = async (item: ChangeItem) => {
    const verb = item.entity === 'skills' ? '归档' : '删除';
    if (!window.confirm(`${verb}这条${item.entity_label}？
${item.title}`)) return;
    setBusy(`del-${item.id}`);
    try {
      await api(apiBaseUrl, '/api/memory/delete', { method: 'POST', json: { entity: item.entity, ids: [item.entity_id] } });
      await load(null, true);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const load = useCallback(async (before?: number | null, quiet = false) => {
    if (!connected) return;
    if (before) setLoadingMore(true); else if (!quiet) setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (before) params.set('before', String(before));
      if (op) params.set('op', op);
      if (entity) params.set('entity', entity);
      const page = await api<ChangesPayload>(apiBaseUrl, `/api/memory/changes?${params}`);
      setItems((current) => (before ? [...current, ...page.items] : page.items));
      setNext(page.next_before);
      setStats(page.stats ?? {});
      setMemosDb(page.memos_db);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); setLoadingMore(false); }
  }, [apiBaseUrl, connected, op, entity]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!auto) return undefined;
    const timer = window.setInterval(() => { void load(null, true); }, 10000);
    return () => window.clearInterval(timer);
  }, [auto, load]);

  const toggle = (id: number) => setOpen((current) => {
    const nextOpen = new Set(current);
    if (nextOpen.has(id)) nextOpen.delete(id); else nextOpen.add(id);
    return nextOpen;
  });

  if (!connected) return <section aria-label="记忆变动"><div className="note">等待 Atlas 后端连接后读取记忆变动。</div></section>;

  return <section aria-label="记忆变动">
    <div className="filterbar" style={{ marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
      <div className="seg" role="tablist">
        {OPS.map((o) => <button key={o.value || 'all'} aria-pressed={op === o.value} onClick={() => setOp(o.value)}>
          {o.label}{o.value && stats[o.value] ? ` ${stats[o.value]}` : ''}
        </button>)}
      </div>
      <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="记忆类型">
        {ENTITIES.map((e) => <option key={e.value || 'all'} value={e.value}>{e.label}</option>)}
      </select>
      <label className="empty-note" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />自动刷新
      </label>
      <button className="btn ghost" disabled={loading} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
      {canPause && <button className="btn ghost" disabled={busy === 'pause'} onClick={() => void togglePause()}
        title={paused ? '恢复后 Atlas 会重新读取和记录记忆' : '暂停后 Atlas 不再读取也不再记录记忆（下一轮对话起生效）'}>
        {paused ? <Play size={14} /> : <Pause size={14} />}{paused ? '恢复记忆' : '暂停记忆'}
      </button>}
      {viewerUrl && <a className="btn ghost" href={viewerUrl} target="_blank" rel="noreferrer">
        <ExternalLink size={14} />打开 MemOS 面板
      </a>}
    </div>
    {paused && <div className="note">记忆已暂停：Atlas 现在既不读取也不记录记忆。点「恢复记忆」重新开启。</div>}

    {!memosDb && <div className="note">还没有记忆数据：开始和 Atlas 对话后，记忆的每一次变动都会出现在这里。</div>}
    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取记忆变动…</b></div></div>}
    {!loading && error && <div className="error-note" role="alert"><span>读取记忆变动失败：{error}</span></div>}
    {!loading && !error && memosDb && items.length === 0 &&
      <div className="list glass"><div className="empty"><GitCompare size={22} /><b>还没有变动</b>新增、修改、删除、淡忘、归档都会记录在这里，并保留改动前后的内容。</div></div>}

    {!loading && !error && items.length > 0 && <div className="list glass">
      {items.map((item) => <Fragment key={item.id}>
        <div className="fact" style={{ cursor: 'pointer' }} onClick={() => toggle(item.id)}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', minWidth: 0 }}>
            {open.has(item.id) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span className="tag" style={{ marginTop: 0, color: '#fff', background: OP_COLOR[item.op] ?? '#57606a' }}>{item.op_label}</span>
            <span className="tag" style={{ marginTop: 0 }}>{item.entity_label}</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{item.title || item.entity_id}</div>
              <small>
                {[relativeTime(item.ts), item.ts.replace('T', ' '),
                  item.fields.length && item.op !== 'added' && item.op !== 'removed'
                    ? `改动：${item.fields.map((f) => f.label).join('、')}` : '',
                  item.reason ? `原因：${item.reason}` : ''].filter(Boolean).join(' · ')}
              </small>
            </div>
          </div>
        </div>
        {open.has(item.id) && <div style={{ padding: '4px 12px 12px 34px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <small className="empty-note">编号 {item.entity_id}</small>
            {item.op !== 'removed' && DELETABLE.has(item.entity) &&
              <button className="btn ghost" disabled={busy === `del-${item.id}`} onClick={() => void remove(item)}>
                {item.entity === 'skills' ? <Archive size={14} /> : <Trash2 size={14} />}{item.entity === 'skills' ? '归档这个技能' : `删除这条${item.entity_label}`}
              </button>}
          </div>
          <FieldTable item={item} />
        </div>}
      </Fragment>)}
    </div>}

    {next && !loading && !error && <div style={{ textAlign: 'center', marginTop: 14 }}>
      <button className="btn" disabled={loadingMore} onClick={() => void load(next)}>
        {loadingMore ? <LoaderCircle size={14} className="spin" /> : null}加载更多
      </button>
    </div>}
  </section>;
}
