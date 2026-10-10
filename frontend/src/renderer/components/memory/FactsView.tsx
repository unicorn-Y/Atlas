/**
 * FactsView —— 「关于你」：MemOS fork 的 user_facts。
 * GET /api/memory/facts?history=1：当前事实（每轮自动带进对话）+ 被改掉、撤销、过期的历史版本，
 * 每条附用户原话；删除走 /api/memory/delete（entity=user_facts）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { History, LoaderCircle, RefreshCw, UserRound } from 'lucide-react';
import { api } from '../../services/api';
import { ConfirmButton } from './common';

export interface UserFact {
  id: string;
  factKey: string;
  value: string;
  text: string;
  status: 'active' | 'superseded' | 'retracted';
  evidenceQuote: string;
  createdAt: number;
  updatedAt: number;
  forgetAfter: number | null;
}

const day = (ms: number) => new Date(ms).toLocaleDateString('zh-CN');

/** 当前 = 生效且没过期；其余进历史，并说明为什么不再生效。 */
export function splitFacts(facts: UserFact[], now = Date.now()) {
  const current: UserFact[] = [];
  const history: Array<UserFact & { why: string }> = [];
  for (const fact of facts) {
    if (fact.status === 'active' && (!fact.forgetAfter || fact.forgetAfter > now)) current.push(fact);
    else history.push({
      ...fact,
      why: fact.status === 'superseded' ? '已被新说法替代'
        : fact.status === 'retracted' ? '已撤销' : `${day(fact.forgetAfter ?? now)} 已过期`,
    });
  }
  return { current, history };
}

export default function FactsView({ apiBaseUrl, connected, onToast }: {
  apiBaseUrl: string; connected: boolean; onToast: (text: string) => void;
}) {
  const [facts, setFacts] = useState<UserFact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    if (!connected) return;
    setLoading(true);
    try {
      const page = await api<{ facts: UserFact[] }>(apiBaseUrl, '/api/memory/facts?history=1');
      setFacts(page.facts ?? []);
      setError('');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally { setLoading(false); }
  }, [apiBaseUrl, connected]);

  useEffect(() => { void load(); }, [load]);

  const { current, history } = useMemo(() => splitFacts(facts), [facts]);

  const remove = async (fact: UserFact) => {
    setBusy(fact.id);
    try {
      await api(apiBaseUrl, '/api/memory/delete', { method: 'POST', json: { entity: 'user_facts', ids: [fact.id] } });
      onToast('已删除这条记忆');
      await load();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  if (!connected) return <section aria-label="关于你"><div className="note">等待 Atlas 后端连接后读取记忆。</div></section>;

  const row = (fact: UserFact, note: string) => <div className="fact" key={fact.id}>
    <div style={{ minWidth: 0 }}>
      <div>{fact.text}</div>
      <small>
        原话「{fact.evidenceQuote}」 · {note}
      </small>
    </div>
    <ConfirmButton label="删除" confirm="确认删除" disabled={busy === fact.id} onConfirm={() => void remove(fact)} />
  </div>;

  return <section aria-label="关于你">
    <div className="filterbar" style={{ marginBottom: 10, gap: 8 }}>
      <small className="empty-note">Atlas 从你自己说的话里记下这些事，每轮对话都会带上。你改口时新的作数，旧的留在历史里。</small>
      <button className="btn ghost" disabled={loading} onClick={() => void load()}>
        <RefreshCw size={14} className={loading ? 'spin' : undefined} />刷新
      </button>
      <button className="btn ghost" aria-pressed={showHistory} onClick={() => setShowHistory((v) => !v)}>
        <History size={14} />{showHistory ? '隐藏历史' : `历史 ${history.length || ''}`}
      </button>
    </div>
    {loading && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取…</b></div></div>}
    {!loading && error && <div className="error-note" role="alert"><span>读取失败：{error}</span></div>}
    {!loading && !error && current.length === 0 &&
      <div className="list glass"><div className="empty"><UserRound size={22} /><b>还没有记下关于你的事</b>聊天时说起自己的情况、偏好或计划，Atlas 会自动记住。</div></div>}
    {!loading && !error && current.length > 0 && <div className="list glass">
      {current.map((fact) => row(fact, fact.forgetAfter
        ? `${day(fact.updatedAt)} 记下，到 ${day(fact.forgetAfter)} 为止`
        : `${day(fact.updatedAt)} 记下`))}
    </div>}
    {!loading && !error && showHistory && <>
      <h3 style={{ margin: '16px 0 8px' }}>历史</h3>
      {history.length === 0
        ? <div className="note">还没有被替代、撤销或过期的记忆。</div>
        : <div className="list glass">{history.map((fact) => row(fact, `${day(fact.updatedAt)} · ${fact.why}`))}</div>}
    </>}
  </section>;
}
