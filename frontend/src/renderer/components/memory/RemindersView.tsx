/**
 * RemindersView —— 聊天里说「…提醒我」建出的提醒（Automation 中名字以「提醒：」开头的记录）。
 * 列表走 GET /api/automations；取消 = PATCH enabled=false（保留记录，引擎撤掉调度）。
 */
import { useCallback, useEffect, useState } from 'react';
import { BellRing, LoaderCircle, RefreshCw } from 'lucide-react';
import { api } from '../../services/api';
import { ConfirmButton } from './common';

const PREFIX = '提醒：';

interface Automation {
  id: string;
  name: string;
  enabled: boolean;
  trigger?: { kind?: string; at?: string };
  state?: { last_run_at?: string; last_status?: string };
}

export interface Reminder { id: string; text: string; at: string; state: 'pending' | 'done' | 'cancelled' }

export function toReminders(list: Automation[]): Reminder[] {
  return list
    .filter((a) => a.name?.startsWith(PREFIX))
    .map((a) => ({
      id: a.id,
      text: a.name.slice(PREFIX.length),
      at: a.trigger?.at ?? '',
      state: a.state?.last_run_at ? 'done' as const : a.enabled ? 'pending' as const : 'cancelled' as const,
    }))
    .sort((x, y) => (x.state === 'pending' ? 0 : 1) - (y.state === 'pending' ? 0 : 1) || y.at.localeCompare(x.at));
}

const when = (iso: string) => (iso ? new Date(iso).toLocaleString('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }) : '');
const LABEL = { pending: '待提醒', done: '已提醒', cancelled: '已取消' };

export default function RemindersView({ apiBaseUrl, connected, onToast }: {
  apiBaseUrl: string; connected: boolean; onToast: (text: string) => void;
}) {
  const [items, setItems] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    try {
      const page = await api<{ automations: Automation[] }>(apiBaseUrl, '/api/automations');
      setItems(toReminders(page.automations ?? []));
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { void load(); }, [load]);

  const cancel = async (item: Reminder) => {
    setBusy(item.id);
    try {
      await api(apiBaseUrl, `/api/automations/${encodeURIComponent(item.id)}`, { method: 'PATCH', json: { enabled: false } });
      onToast('已取消提醒');
      await load();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  if (!connected) return <section aria-label="提醒"><div className="note">等待 Atlas 后端连接后读取提醒。</div></section>;

  return <section aria-label="提醒">
    <div className="filterbar" style={{ marginBottom: 10, gap: 8 }}>
      <small className="empty-note">在聊天里说「明天上午 9 点提醒我…」就会建一个提醒，到点弹出 Windows 通知。改时间或取消也可以直接在聊天里说。</small>
      <button className="btn ghost" disabled={loading} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
    </div>
    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取…</b></div></div>}
    {!loading && error && <div className="error-note" role="alert"><span>读取失败：{error}</span></div>}
    {!loading && !error && items.length === 0 &&
      <div className="list glass"><div className="empty"><BellRing size={22} /><b>还没有提醒</b>在聊天里让 Atlas 提醒你一件事试试。</div></div>}
    {!loading && !error && items.length > 0 && <div className="list glass">
      {items.map((item) => <div className="fact" key={item.id}>
        <div style={{ minWidth: 0, opacity: item.state === 'pending' ? 1 : 0.6 }}>
          <div>{item.text}</div>
          <small>{when(item.at)} · {LABEL[item.state]}</small>
        </div>
        {item.state === 'pending' &&
          <ConfirmButton label="取消" confirm="确认取消" disabled={busy === item.id} onConfirm={() => void cancel(item)} />}
      </div>)}
    </div>}
  </section>;
}
