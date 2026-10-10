/**
 * LibraryView —— 「经验与技能」：MemOS 从对话中提炼出的技能、策略和世界模型。
 * GET /api/memory/library/{skills|policies|world_model}；删除（技能为归档）走 /api/memory/delete。
 */
import { useCallback, useEffect, useState } from 'react';
import { LoaderCircle, RefreshCw, Sparkles } from 'lucide-react';
import { api, relativeTime } from '../../services/api';
import { ConfirmButton } from './common';

type Kind = 'skills' | 'policies' | 'world_model';

const KINDS: Array<{ value: Kind; label: string; hint: string }> = [
  { value: 'skills', label: '技能', hint: '反复做成的事结晶成的做法，Atlas 遇到同类任务会直接调用。' },
  { value: 'policies', label: '策略', hint: '从多次经历里归纳出的「遇到什么情况该怎么做 / 不该怎么做」。' },
  { value: 'world_model', label: '世界模型', hint: '对你的环境和工具的认识，比如项目结构、命令怎么用。' },
];

const STATUS: Record<string, string> = { candidate: '候选', active: '生效', archived: '已归档' };

export interface LibraryItem { id: string; title: string; detail: string; status: string; updatedAt: string }

/** Normalise the three MemOS DTO shapes into one row. */
export function toItems(kind: Kind, page: Record<string, unknown>): LibraryItem[] {
  const list = (kind === 'skills' ? page.skills : kind === 'policies' ? page.policies : page.worldModels);
  if (!Array.isArray(list)) return [];
  return list.map((raw) => {
    const r = raw as Record<string, unknown>;
    const text = (value: unknown) => (typeof value === 'string' ? value : '');
    const updated = r.updatedAt ?? r.createdAt;
    return {
      id: text(r.id),
      title: text(kind === 'skills' ? r.name : r.title),
      detail: text(kind === 'skills' ? r.invocationGuide : kind === 'policies' ? (r.trigger || r.procedure) : r.body),
      status: text(r.status),
      updatedAt: typeof updated === 'number' ? new Date(updated).toISOString() : text(updated),
    };
  }).filter((item) => item.id);
}

export default function LibraryView({ apiBaseUrl, connected, onToast }: {
  apiBaseUrl: string; connected: boolean; onToast: (text: string) => void;
}) {
  const [kind, setKind] = useState<Kind>('skills');
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    try {
      const page = await api<Record<string, unknown>>(apiBaseUrl, `/api/memory/library/${kind}?limit=100`);
      setItems(toItems(kind, page));
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); }
  }, [apiBaseUrl, connected, kind]);

  useEffect(() => { void load(); }, [load]);

  const remove = async (item: LibraryItem) => {
    setBusy(item.id);
    try {
      await api(apiBaseUrl, '/api/memory/delete', { method: 'POST', json: { entity: kind, ids: [item.id] } });
      onToast(kind === 'skills' ? '已归档这个技能' : '已删除');
      await load();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  if (!connected) return <section aria-label="经验与技能"><div className="note">等待 Atlas 后端连接后读取。</div></section>;
  const current = KINDS.find((k) => k.value === kind)!;

  return <section aria-label="经验与技能">
    <div className="filterbar" style={{ marginBottom: 10, gap: 8 }}>
      <div className="seg" role="tablist">
        {KINDS.map((k) => <button key={k.value} aria-pressed={kind === k.value} onClick={() => setKind(k.value)}>{k.label}</button>)}
      </div>
      <button className="btn ghost" disabled={loading} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
    </div>
    <div className="note">{current.hint}</div>
    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取…</b></div></div>}
    {!loading && error && <div className="error-note" role="alert"><span>读取失败：{error}</span></div>}
    {!loading && !error && items.length === 0 &&
      <div className="list glass"><div className="empty"><Sparkles size={22} /><b>还没有{current.label}</b>多用 Atlas 做几次同类的事，它会自己总结出来。</div></div>}
    {!loading && !error && items.length > 0 && <div className="list glass">
      {items.map((item) => <div className="fact" key={item.id}>
        <div style={{ minWidth: 0 }}>
          <div>{item.title || item.id}</div>
          <small>
            {STATUS[item.status] ?? item.status}{item.updatedAt ? ` · ${relativeTime(item.updatedAt)}更新` : ''}
            {item.detail ? ` · ${item.detail.length > 160 ? `${item.detail.slice(0, 160)}…` : item.detail}` : ''}
          </small>
        </div>
        {item.status !== 'archived' &&
          <ConfirmButton label={kind === 'skills' ? '归档' : '删除'} confirm={kind === 'skills' ? '确认归档' : '确认删除'}
            disabled={busy === item.id} onConfirm={() => void remove(item)} />}
      </div>)}
    </div>}
  </section>;
}
