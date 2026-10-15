/**
 * 记忆库三页（docs/memory/PLAN-V1.md）：今天 / 人和事 / 变动记录。
 * 数据来自 /api/memlib/*；底层是 data/memory 下的 Markdown + git，每条都能改、能忘掉、能撤销。
 */
import { useCallback, useEffect, useState } from 'react';
import { BookUser, Check, GitCommitHorizontal, History, LoaderCircle, Pencil, Plus, RefreshCw, Undo2, UserRound, X } from 'lucide-react';
import { api } from '../../services/api';
import { ConfirmButton } from './common';

export interface MemEntry {
  id: string; text: string; src: string; at: string; until?: string;
  quote?: string; ended?: string; why?: string; key?: string;
  outcome?: string; steps?: string[]; verified?: boolean;
}
interface MemPage {
  path: string; title: string; kind: string; aliases: string[];
  current: MemEntry[]; history: MemEntry[]; notes: string[];
}
interface PageSummary { path: string; title: string; kind: string; aliases: string[]; count: number; history: number; updated: string }
interface ChangeFile { path: string; added: string[]; removed: string[]; ended: string[] }
interface Change { sha: string; time: number; message: string; files: ChangeFile[] }

type Props = { apiBaseUrl: string; connected: boolean; onToast: (text: string) => void };

const SRC_STYLE: Record<string, { bg: string; fg: string }> = {
  你说的: { bg: 'var(--ok-soft)', fg: 'var(--ok)' },
  你改的: { bg: 'var(--brand-soft)', fg: 'var(--brand)' },
  推测: { bg: 'var(--danger-soft)', fg: 'var(--danger)' },
  它自己: { bg: 'var(--sunken)', fg: 'var(--fg-2)' },
};

const day = (iso?: string) => (iso ? iso.slice(0, 10) : '');
const clock = (unix: number) => new Date(unix * 1000).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const pageName = (path: string) => path.replace(/\.md$/, '').replace(/^(人|事)\//, '');

function SrcChip({ src }: { src: string }) {
  const style = SRC_STYLE[src] ?? { bg: 'var(--sunken)', fg: 'var(--fg-3)' };
  return <span style={{ fontSize: 11.5, padding: '1px 7px', borderRadius: 99, background: style.bg, color: style.fg, marginRight: 6, whiteSpace: 'nowrap' }}>{src || '来源不明'}</span>;
}

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await fn()); setError(''); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setLoading(false); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => { void load(); }, [load]);
  return { data, error, loading, load };
}

/** 一条记忆：文字 + 来源 + 原话；可以就地改、忘掉。 */
function EntryRow({ entry, apiBaseUrl, onChanged, onToast, past = false }: {
  entry: MemEntry; apiBaseUrl: string; onChanged: () => void; onToast: (t: string) => void; past?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(entry.text);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    if (!text.trim() || text.trim() === entry.text) { setEditing(false); return; }
    setBusy(true);
    try {
      await api(apiBaseUrl, '/api/memlib/entry', { method: 'POST', json: { id: entry.id, text: text.trim() } });
      onToast('已改好，下一轮对话就按这个来');
      setEditing(false);
      onChanged();
    } catch (exc) { onToast(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const forget = async () => {
    setBusy(true);
    try {
      const report = await api<{ diary_pages: number; history: { rewritten: boolean; error?: string } }>(
        apiBaseUrl, '/api/memlib/forget', { method: 'POST', json: { id: entry.id } },
      );
      const history = report.history.error
        ? `历史记录没改成（${report.history.error}）`
        : report.history.rewritten ? '历史记录也已改写' : '历史里本来就没有';
      onToast(`已忘掉：页面、日记${report.diary_pages}页、${history}。没覆盖：原始聊天记录。`);
      onChanged();
    } catch (exc) { onToast(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(false); }
  };
  const meta = [
    entry.quote ? `原话「${entry.quote}」` : '',
    past ? `${day(entry.ended)} ${entry.why ?? ''}` : `${day(entry.at)} 记下`,
    !past && entry.until ? `到 ${entry.until.slice(0, 16).replace('T', ' ')} 为止` : '',
  ].filter(Boolean).join(' · ');
  return <div className="fact">
    <div style={{ minWidth: 0, opacity: past ? 0.65 : 1 }}>
      {editing
        ? <div style={{ display: 'flex', gap: 6 }}>
          <input autoFocus value={text} onChange={(e) => setText(e.target.value)} style={{ flex: 1, minWidth: 0 }}
            onKeyDown={(e) => { if (e.key === 'Enter') void save(); if (e.key === 'Escape') setEditing(false); }} />
          <button className="iconbtn" aria-label="保存" disabled={busy} onClick={() => void save()}><Check size={15} /></button>
          <button className="iconbtn" aria-label="取消" onClick={() => { setText(entry.text); setEditing(false); }}><X size={15} /></button>
        </div>
        : <div><SrcChip src={entry.src} />{entry.text}</div>}
      <small>{meta}</small>
    </div>
    {!editing && <div style={{ display: 'flex', gap: 4 }}>
      {!past && <button className="btn ghost" disabled={busy} onClick={() => setEditing(true)}><Pencil size={13} />改</button>}
      <ConfirmButton label="忘掉" confirm="确认忘掉" disabled={busy} onConfirm={() => void forget()} />
    </div>}
  </div>;
}

function AddRow({ path, apiBaseUrl, onChanged, onToast }: { path: string; apiBaseUrl: string; onChanged: () => void; onToast: (t: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState('');
  const submit = async () => {
    if (!text.trim()) return;
    try {
      await api(apiBaseUrl, '/api/memlib/add', { method: 'POST', json: { path, text: text.trim() } });
      setText(''); setOpen(false); onToast('已加上'); onChanged();
    } catch (exc) { onToast(exc instanceof Error ? exc.message : String(exc)); }
  };
  if (!open) return <button className="btn ghost" onClick={() => setOpen(true)}><Plus size={13} />加一条</button>;
  return <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
    <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="写下要它记住的事" style={{ flex: 1 }}
      onKeyDown={(e) => { if (e.key === 'Enter') void submit(); if (e.key === 'Escape') setOpen(false); }} />
    <button className="btn primary" onClick={() => void submit()}>加上</button>
    <button className="btn ghost" onClick={() => setOpen(false)}>取消</button>
  </div>;
}

function PageBlock({ page, apiBaseUrl, onChanged, onToast, emptyText }: {
  page: MemPage; apiBaseUrl: string; onChanged: () => void; onToast: (t: string) => void; emptyText: string;
}) {
  const [showHistory, setShowHistory] = useState(false);
  return <>
    {page.current.length
      ? <div className="list glass">{page.current.map((e) => <EntryRow key={e.id} entry={e} apiBaseUrl={apiBaseUrl} onChanged={onChanged} onToast={onToast} />)}</div>
      : <div className="note">{emptyText}</div>}
    <div style={{ display: 'flex', gap: 8, margin: '8px 0 4px' }}>
      <AddRow path={page.path} apiBaseUrl={apiBaseUrl} onChanged={onChanged} onToast={onToast} />
      {page.history.length > 0 && <button className="btn ghost" aria-pressed={showHistory} onClick={() => setShowHistory((v) => !v)}>
        <History size={13} />{showHistory ? '收起历史' : `历史 ${page.history.length}`}
      </button>}
    </div>
    {showHistory && <div className="list glass">{page.history.map((e) => <EntryRow key={e.id} entry={e} past apiBaseUrl={apiBaseUrl} onChanged={onChanged} onToast={onToast} />)}</div>}
  </>;
}

function ChangeCard({ change, apiBaseUrl, onChanged, onToast }: { change: Change; apiBaseUrl: string; onChanged?: () => void; onToast: (t: string) => void }) {
  const undo = async () => {
    try {
      await api(apiBaseUrl, '/api/memlib/revert', { method: 'POST', json: { sha: change.sha } });
      onToast('已撤销这次变动'); onChanged?.();
    } catch (exc) { onToast(exc instanceof Error ? exc.message : String(exc)); }
  };
  return <div className="fact" style={{ alignItems: 'start' }}>
    <div style={{ minWidth: 0 }}>
      <div style={{ fontWeight: 500 }}>{change.message}</div>
      {change.files.map((f) => <div key={f.path} style={{ marginTop: 4, fontSize: 13 }}>
        <span style={{ color: 'var(--fg-3)' }}>{pageName(f.path)}：</span>
        {f.added.map((t) => <span key={`+${t}`} style={{ color: 'var(--ok)', marginRight: 10 }}>＋{t}</span>)}
        {f.ended.map((t) => <span key={`~${t}`} style={{ color: 'var(--fg-3)', marginRight: 10 }}>→ 历史：{t}</span>)}
        {f.removed.map((t) => <span key={`-${t}`} style={{ color: 'var(--danger)', textDecoration: 'line-through', marginRight: 10 }}>{t}</span>)}
      </div>)}
      <small>{clock(change.time)} · {change.sha.slice(0, 7)}</small>
    </div>
    {onChanged && <ConfirmButton label="撤销" confirm="确认撤销" onConfirm={() => void undo()} />}
  </div>;
}

export function TodayView({ apiBaseUrl, connected, onToast }: Props) {
  const today = useLoad(() => api<{ changes: Change[]; now: MemPage; turns: number; episodes: MemEntry[] }>(apiBaseUrl, '/api/memlib/today'), [apiBaseUrl, connected]);
  const me = useLoad(() => api<MemPage>(apiBaseUrl, `/api/memlib/page?path=${encodeURIComponent('我.md')}`), [apiBaseUrl, connected]);
  const self = useLoad(() => api<MemPage>(apiBaseUrl, `/api/memlib/page?path=${encodeURIComponent('它自己.md')}`), [apiBaseUrl, connected]);
  const reload = () => { void today.load(); void me.load(); void self.load(); };
  if (!connected) return <div className="note">等待 Atlas 后端连接后读取记忆。</div>;
  const error = today.error || me.error || self.error;
  if (error) return <div className="error-note" role="alert"><span>读取失败：{error}</span></div>;
  if (!today.data || !me.data || !self.data) return <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取…</b></div></div>;
  const { changes, now, turns, episodes } = today.data;
  return <section aria-label="今天">
    <div className="filterbar" style={{ marginBottom: 6, gap: 8 }}>
      <small className="empty-note">今天聊了 {turns} 轮，记忆变动 {changes.length} 次。下面每一条都会自动带进对话；不对就直接改或忘掉。</small>
      <button className="btn ghost" onClick={reload}><RefreshCw size={14} className={today.loading ? 'spin' : undefined} />刷新</button>
    </div>
    <h3 className="cap">今天的变动</h3>
    {changes.length
      ? <div className="list glass">{changes.map((c) => <ChangeCard key={c.sha} change={c} apiBaseUrl={apiBaseUrl} onToast={onToast} />)}</div>
      : <div className="note">今天还没有新记下的事。</div>}
    <h3 className="cap">进行中 / 有时限的事</h3>
    <PageBlock page={now} apiBaseUrl={apiBaseUrl} onChanged={reload} onToast={onToast} emptyText="没有进行中的事。你提到面试、出差、要办的事时，它会记在这里，到时间自动移到历史。" />
    <h3 className="cap">关于你</h3>
    <PageBlock page={me.data} apiBaseUrl={apiBaseUrl} onChanged={reload} onToast={onToast} emptyText="还没有记下关于你的事。聊天时说起自己的情况、偏好或计划，它会自动记住。" />
    <h3 className="cap">它自己</h3>
    <PageBlock page={self.data} apiBaseUrl={apiBaseUrl} onChanged={reload} onToast={onToast} emptyText="它对自己的记录（表过的态、犯过的错）。第一版只能由你来写。" />
    {episodes.length > 0 && <>
      <h3 className="cap">今天做过的事</h3>
      <div className="list glass">{episodes.map((entry) => <div key={entry.id}>
        <EntryRow entry={entry} apiBaseUrl={apiBaseUrl} onChanged={reload} onToast={onToast} />
        <small style={{ display: 'block', color: 'var(--fg-3)', padding: '0 12px 8px' }}>
          {entry.outcome}{entry.verified ? ' · 已验证' : ''}
        </small>
      </div>)}</div>
    </>}
  </section>;
}

export function PeopleView({ apiBaseUrl, connected, onToast }: Props) {
  const overview = useLoad(() => api<{ pages: PageSummary[]; root: string }>(apiBaseUrl, '/api/memlib/overview'), [apiBaseUrl, connected]);
  const [selected, setSelected] = useState('');
  const pages = (overview.data?.pages ?? []).filter((p) => p.kind === 'person' || p.kind === 'thing');
  const active = selected || pages[0]?.path || '';
  const page = useLoad(
    () => (active ? api<MemPage>(apiBaseUrl, `/api/memlib/page?path=${encodeURIComponent(active)}`) : Promise.resolve(null)),
    [apiBaseUrl, active, connected],
  );
  const [aliasText, setAliasText] = useState('');
  useEffect(() => { setAliasText((page.data?.aliases ?? []).join('、')); }, [page.data]);
  const saveAliases = async () => {
    try {
      await api(apiBaseUrl, '/api/memlib/aliases', { method: 'POST', json: { path: active, aliases: aliasText.split(/[、,，]/) } });
      onToast('别名已保存'); void page.load(); void overview.load();
    } catch (exc) { onToast(exc instanceof Error ? exc.message : String(exc)); }
  };
  if (!connected) return <div className="note">等待 Atlas 后端连接后读取记忆。</div>;
  if (overview.error) return <div className="error-note" role="alert"><span>读取失败：{overview.error}</span></div>;
  if (!overview.data) return <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取…</b></div></div>;
  if (!pages.length) return <div className="list glass"><div className="empty"><BookUser size={22} /><b>还没有记下任何人或事</b>聊天时提到家人、同事、朋友或项目，它会给每个人、每件事建一页。</div></div>;
  const people = pages.filter((p) => p.kind === 'person');
  const things = pages.filter((p) => p.kind === 'thing');
  const item = (p: PageSummary) => <button key={p.path} className="row" aria-selected={p.path === active} onClick={() => setSelected(p.path)}
    style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}>
    <div style={{ minWidth: 0 }}><p>{p.title}</p><small>{p.aliases.length ? `也叫 ${p.aliases.join('、')}` : `${p.count} 条`}</small></div>
    <small>{p.count}</small>
  </button>;
  return <section aria-label="人和事" style={{ display: 'grid', gridTemplateColumns: 'minmax(160px, 220px) minmax(0, 1fr)', gap: 16, alignItems: 'start' }}>
    <div>
      {people.length > 0 && <><h3 className="cap">人</h3><div className="list glass">{people.map(item)}</div></>}
      {things.length > 0 && <><h3 className="cap">事</h3><div className="list glass">{things.map(item)}</div></>}
    </div>
    <div style={{ minWidth: 0 }}>
      {page.data && <>
        <h2 style={{ margin: '0 0 6px', display: 'flex', alignItems: 'center', gap: 8 }}><UserRound size={18} />{page.data.title}</h2>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 10 }}>
          <small className="empty-note" style={{ padding: 0 }}>别名</small>
          <input value={aliasText} onChange={(e) => setAliasText(e.target.value)} placeholder="用顿号分开，比如：王总、王建国" style={{ flex: 1 }} />
          <button className="btn ghost" onClick={() => void saveAliases()}>保存</button>
        </div>
        <PageBlock page={page.data} apiBaseUrl={apiBaseUrl} onChanged={() => { void page.load(); void overview.load(); }} onToast={onToast} emptyText="这一页现在是空的。" />
      </>}
    </div>
  </section>;
}

export function LibChangesView({ apiBaseUrl, connected, onToast, sourceFilter = [] }: Props & { sourceFilter?: string[] }) {
  const [diary, setDiary] = useState(false);
  const changes = useLoad(() => api<{ changes: Change[] }>(apiBaseUrl, `/api/memlib/changes?limit=100&diary=${diary ? 1 : 0}`), [apiBaseUrl, connected, diary]);
  if (!connected) return <div className="note">等待 Atlas 后端连接后读取记忆。</div>;
  return <section aria-label="变动记录">
    <div className="filterbar" style={{ marginBottom: 10, gap: 8 }}>
      <small className="empty-note">每次变动都是记忆库里的一次 git 提交，可以撤销。</small>
      <button className="btn ghost" aria-pressed={diary} onClick={() => setDiary((v) => !v)}><GitCommitHorizontal size={14} />{diary ? '隐藏日记提交' : '显示日记提交'}</button>
      <button className="btn ghost" onClick={() => void changes.load()}><RefreshCw size={14} className={changes.loading ? 'spin' : undefined} />刷新</button>
    </div>
    {changes.error && <div className="error-note" role="alert"><span>读取失败：{changes.error}</span></div>}
    {!changes.data && !changes.error && <div className="list glass"><div className="empty"><LoaderCircle size={22} className="spin" /><b>正在读取…</b></div></div>}
    {changes.data && (() => {
      const visible = changes.data.changes.filter((change) => !sourceFilter.length || sourceFilter.some((source) => {
        const names: Record<string, string[]> = { '你说的': ['said', '你说的', '记下'], '你改的': ['edited', '你改的', '修改'], '推测': ['guess', '推测'], '经历': ['episode', '经历'], '整理': ['dream', '整理'], '原对话': ['raw', '原对话', '对话'] };
        return (names[source] ?? [source]).some((name) => change.message.toLocaleLowerCase().includes(name.toLocaleLowerCase()));
      }));
      return visible.length
        ? <div className="list glass">{visible.map((c) => <ChangeCard key={c.sha} change={c} apiBaseUrl={apiBaseUrl} onChanged={() => void changes.load()} onToast={onToast} />)}</div>
        : <div className="list glass"><div className="empty"><Undo2 size={22} /><b>{sourceFilter.length ? '没有符合来源筛选的变动' : '还没有变动'}</b>聊几轮之后，这里会列出它每次记下、改掉、忘掉了什么。</div></div>;
    })()}
  </section>;
}
