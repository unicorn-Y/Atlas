import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { BookMarked, Brain, Check, LoaderCircle, Plus, RefreshCw, Search, Sparkles, X } from 'lucide-react';
import { api, relativeTime } from '../services/api';

interface Fact { key: string; value: string; category: string; confidence?: number | null; memory_type?: string | null; updated_at?: string }
interface Candidate { id: string; key: string; value: string; category: string; confidence?: number; status: string; memory_type?: string; created_at?: string }
interface Knowledge { id: string; content: string; source?: string; category?: string; created_at?: string; score?: number }
type Tab = 'facts' | 'pending' | 'knowledge';

const CATEGORY: Record<string, string> = { general: '通用', preference: '偏好', preferences: '偏好', profile: '个人信息', personal: '个人信息', project: '项目', work: '工作', habit: '习惯', contact: '联系人', schedule: '日程' };
const categoryName = (value?: string) => CATEGORY[value ?? 'general'] ?? value ?? '通用';
const HIDDEN_KEY = 'atlas.memory.hidden-candidates';
const readHidden = (): string[] => { try { const value = JSON.parse(localStorage.getItem(HIDDEN_KEY) ?? '[]'); return Array.isArray(value) ? value : []; } catch { return []; } };

function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const index = text.toLowerCase().indexOf(q.toLowerCase());
  if (index < 0) return <>{text}</>;
  return <>{text.slice(0, index)}<mark>{text.slice(index, index + q.length)}</mark>{text.slice(index + q.length)}</>;
}

function ConfirmButton({ label, confirm, onConfirm, disabled }: { label: string; confirm: string; onConfirm: () => void; disabled?: boolean }) {
  const [armed, setArmed] = useState(false);
  useEffect(() => { if (!armed) return; const timer = window.setTimeout(() => setArmed(false), 3000); return () => window.clearTimeout(timer); }, [armed]);
  return <button className={`btn ${armed ? 'danger' : 'ghost'}`} disabled={disabled} onClick={() => { if (armed) { setArmed(false); onConfirm(); } else setArmed(true); }}>{armed ? confirm : label}</button>;
}

export default function MemoryPage({ apiBaseUrl, connected, onToast, onPendingChange }: { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void; onPendingChange?: (count: number) => void }) {
  const [tab, setTab] = useState<Tab>('facts');
  const [facts, setFacts] = useState<Fact[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [knowledge, setKnowledge] = useState<Knowledge[]>([]);
  const [hits, setHits] = useState<Knowledge[] | null>(null);
  const [hidden, setHidden] = useState<string[]>(readHidden);
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [factForm, setFactForm] = useState({ key: '', value: '', category: 'general' });
  const [docForm, setDocForm] = useState({ content: '', source: '', category: 'general' });

  const refresh = useCallback(async () => {
    if (!connected) return;
    setBusy(true);
    try {
      const [nextFacts, nextCandidates, nextKnowledge] = await Promise.all([
        api<Fact[]>(apiBaseUrl, '/api/facts'),
        api<Candidate[]>(apiBaseUrl, '/api/memory/candidates?status=pending').catch(() => [] as Candidate[]),
        api<Knowledge[]>(apiBaseUrl, '/api/knowledge?limit=200').catch(() => [] as Knowledge[]),
      ]);
      setFacts(nextFacts); setCandidates(nextCandidates); setKnowledge(nextKnowledge); setError('');
    } catch (exc) {
      setError(`读取记忆失败：${exc instanceof Error ? exc.message : String(exc)}`);
    } finally { setBusy(false); }
  }, [apiBaseUrl, connected]);
  useEffect(() => { void refresh(); }, [refresh]);

  const pending = useMemo(() => candidates.filter((item) => !hidden.includes(item.id)), [candidates, hidden]);
  useEffect(() => onPendingChange?.(pending.length), [pending.length, onPendingChange]);

  // Knowledge search goes to the backend; facts and candidates filter locally.
  useEffect(() => {
    const q = query.trim();
    if (tab !== 'knowledge' || !q || !connected) { setHits(null); return; }
    const timer = window.setTimeout(() => {
      api<Knowledge[]>(apiBaseUrl, `/api/knowledge/search?q=${encodeURIComponent(q)}&limit=50`).then(setHits).catch(() => setHits(null));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [apiBaseUrl, connected, query, tab]);

  const hide = (id: string) => setHidden((current) => { const next = [...current, id]; localStorage.setItem(HIDDEN_KEY, JSON.stringify(next.slice(-500))); return next; });
  const run = async (task: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try { await task(); onToast(done); setError(''); await refresh(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const remember = (item: Candidate) => run(async () => { await api(apiBaseUrl, '/api/facts', { method: 'POST', json: { key: item.key, value: item.value, category: item.category || 'general' } }); hide(item.id); }, '已记住');
  const saveFact = (event: FormEvent) => { event.preventDefault(); void run(async () => { await api(apiBaseUrl, '/api/facts', { method: 'POST', json: { key: factForm.key.trim(), value: factForm.value.trim(), category: factForm.category.trim() || 'general' } }); setFactForm({ key: '', value: '', category: 'general' }); setAdding(false); }, '已添加记忆'); };
  const saveDoc = (event: FormEvent) => { event.preventDefault(); void run(async () => { await api(apiBaseUrl, '/api/knowledge', { method: 'POST', json: { content: docForm.content.trim(), source: docForm.source.trim(), category: docForm.category.trim() || 'general' } }); setDocForm({ content: '', source: '', category: 'general' }); setAdding(false); }, '已加入资料'); };

  const q = query.trim().toLowerCase();
  const shownFacts = facts.filter((item) => !q || `${item.key} ${item.value} ${categoryName(item.category)}`.toLowerCase().includes(q));
  const groups = shownFacts.reduce<Record<string, Fact[]>>((all, item) => { (all[categoryName(item.category)] ??= []).push(item); return all; }, {});
  const shownPending = pending.filter((item) => !q || `${item.key} ${item.value}`.toLowerCase().includes(q));
  const shownDocs = hits ?? knowledge;

  return <div className="screen page"><div className="page-inner narrow">
    <header className="page-head">
      <div><h1>记忆与资料</h1><p>Atlas 记住的关于你的事，以及你交给它的资料。每一条都可以查看、修改或删除。</p></div>
      <div className="btns">
        <button className="btn ghost" onClick={() => void refresh()} disabled={busy || !connected}>{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}刷新</button>
        {tab !== 'pending' && <button className="btn primary" disabled={!connected} onClick={() => setAdding((value) => !value)}><Plus size={15} />{tab === 'facts' ? '添加记忆' : '添加资料'}</button>}
      </div>
    </header>

    <div className="filterbar">
      <div className="seg" role="tablist">
        <button aria-pressed={tab === 'facts'} onClick={() => { setTab('facts'); setAdding(false); }}>记忆 {facts.length || ''}</button>
        <button aria-pressed={tab === 'pending'} onClick={() => { setTab('pending'); setAdding(false); }}>待确认 {pending.length || ''}</button>
        <button aria-pressed={tab === 'knowledge'} onClick={() => { setTab('knowledge'); setAdding(false); }}>资料 {knowledge.length || ''}</button>
      </div>
      <label className="field"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tab === 'knowledge' ? '按内容搜索资料' : '搜索记忆'} aria-label="搜索记忆" /></label>
    </div>

    {!connected && <div className="error-note">Atlas 后端未连接，暂时无法读取记忆。</div>}
    {error && <div className="error-note" role="alert"><span>{error}</span><button className="iconbtn" aria-label="关闭错误提示" onClick={() => setError('')}><X size={15} /></button></div>}

    {adding && tab === 'facts' && <form className="card glass form" onSubmit={saveFact}>
      <h2>添加一条记忆</h2>
      <div className="two"><label>名称<input required value={factForm.key} onChange={(event) => setFactForm({ ...factForm, key: event.target.value })} placeholder="例如：常用编辑器" /></label>
        <label>分类<input value={factForm.category} onChange={(event) => setFactForm({ ...factForm, category: event.target.value })} placeholder="general" /></label></div>
      <label>内容<textarea required value={factForm.value} onChange={(event) => setFactForm({ ...factForm, value: event.target.value })} placeholder="例如：写代码用 VS Code，主题偏暗" /></label>
      <div className="foot"><button type="button" className="btn ghost" onClick={() => setAdding(false)}>取消</button><button className="btn primary" disabled={busy}>保存记忆</button></div>
    </form>}
    {adding && tab === 'knowledge' && <form className="card glass form" onSubmit={saveDoc}>
      <h2>添加资料</h2>
      <label>内容<textarea required value={docForm.content} onChange={(event) => setDocForm({ ...docForm, content: event.target.value })} placeholder="粘贴一段文字、笔记或说明，Atlas 会在需要时检索它" /></label>
      <div className="two"><label>来源<input value={docForm.source} onChange={(event) => setDocForm({ ...docForm, source: event.target.value })} placeholder="链接或文件名（可选）" /></label>
        <label>分类<input value={docForm.category} onChange={(event) => setDocForm({ ...docForm, category: event.target.value })} placeholder="general" /></label></div>
      <div className="foot"><button type="button" className="btn ghost" onClick={() => setAdding(false)}>取消</button><button className="btn primary" disabled={busy}>加入资料</button></div>
    </form>}

    {tab === 'facts' && (Object.keys(groups).length ? Object.entries(groups).map(([name, items]) => <section className="mem-group" key={name}>
      <h3>{name}<span>{items.length}</span></h3>
      <div className="list glass">{items.map((item) => <div className="fact" key={item.key}>
        <div><Highlight text={item.value} query={query} /><small><Highlight text={item.key} query={query} />{item.updated_at ? ` · ${relativeTime(item.updated_at)}更新` : ''}</small></div>
        <ConfirmButton label="忘掉" confirm="确认忘掉" disabled={busy} onConfirm={() => void run(() => api(apiBaseUrl, `/api/facts/${encodeURIComponent(item.key)}`, { method: 'DELETE' }), '已忘掉这条记忆')} />
      </div>)}</div>
    </section>) : <div className="list glass"><div className="empty"><Brain size={22} /><b>{q ? '没有匹配的记忆' : '还没有记忆'}</b>{q ? '换个关键词试试。' : '和 Atlas 聊天时它会提出想记住的内容，也可以点「添加记忆」手动告诉它。'}</div></div>)}

    {tab === 'pending' && (shownPending.length ? <div className="list glass">{shownPending.map((item) => <div className="fact" key={item.id}>
      <div><Highlight text={item.value} query={query} /><small>{categoryName(item.category)}{typeof item.confidence === 'number' ? ` · 把握 ${Math.round(item.confidence * 100)}%` : ''}{item.created_at ? ` · ${relativeTime(item.created_at)}` : ''}</small></div>
      <div className="btns"><button className="btn ghost" disabled={busy} onClick={() => { hide(item.id); onToast('已忽略，只在本机隐藏'); }}>忽略</button><button className="btn" disabled={busy} onClick={() => void remember(item)}><Check size={14} />记住</button></div>
    </div>)}</div> : <div className="list glass"><div className="empty"><Sparkles size={22} /><b>没有待确认的内容</b>Atlas 从对话中发现值得记住的事时，会先放在这里等你确认。</div></div>)}

    {tab === 'knowledge' && (shownDocs.length ? <div className="list glass">{shownDocs.map((item) => <div className="fact" key={item.id}>
      <div><Highlight text={item.content.length > 280 ? `${item.content.slice(0, 280)}…` : item.content} query={query} /><small>{[item.source, categoryName(item.category), relativeTime(item.created_at)].filter(Boolean).join('，')}</small></div>
      <ConfirmButton label="删除" confirm="确认删除" disabled={busy} onConfirm={() => void run(() => api(apiBaseUrl, `/api/knowledge/${encodeURIComponent(item.id)}`, { method: 'DELETE' }), '已删除资料')} />
    </div>)}</div> : <div className="list glass"><div className="empty"><BookMarked size={22} /><b>{q ? '没有找到相关资料' : '资料库是空的'}</b>{q ? '换个说法试试，搜索会按意思匹配。' : '把常用的说明、笔记加进来，Atlas 回答时会参考它们。'}</div></div>)}
  </div></div>;
}
